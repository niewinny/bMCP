"""
HTTP MCP Server for Blender using MCP SDK

This module provides an HTTP-based Model Context Protocol (MCP) server that runs
inside Blender using the official MCP SDK. It provides tools, resources, and
prompts for controlling Blender through AI assistants.

Architecture:
- MCP HTTP server runs in a background thread with asyncio event loop
- Tool handlers use anyio.to_thread to bridge async to sync execution
- All bpy operations run on Blender's main thread via bpy.app.timers
- Thread-safe result passing using threading.Event()

Execution Model:
- Requests are scheduled via bpy.app.timers.register() on Blender's main thread
- Blender processes timers sequentially (one at a time) - automatic serialization
- This prevents race conditions since bpy API is not thread-safe
- Multiple requests queue naturally through Blender's timer system

Timeout Behavior:
- Tool execution has a configurable timeout (default: 5 minutes)
- Set TOOL_EXECUTION_TIMEOUT to None in config.py for infinite wait
- Timeouts raise clear error messages explaining the situation
- Note: Python exec() cannot be truly interrupted, so timeouts only affect the wait

Transport:
- HTTP/SSE for direct clients (Claude Code, Cursor, VS Code)
- Can be bridged to stdio for Claude Desktop via stdio_server.py
"""

import asyncio
import json
import logging
import threading
import time
import traceback
import uuid

# Import dependencies (from bundled wheels)
import anyio
import bpy
import uvicorn

from ... import __package__ as base_package

# Import MCP modules
from .. import prompts, resources, tools
from ..core import MCPServer
from ..logger import get_logger, setup_logging
from ..resources._internal.executor import (
    cleanup_stale_properties,
    clear_pending_operations,
)
from ..utils.config import (
    DEFAULT_SERVER_PORT,
    GRACEFUL_SHUTDOWN_TIMEOUT,
    SERVER_STARTUP_TIMEOUT,
    TOOL_EXECUTION_TIMEOUT,
    validate_config,
)
from .asgi import create_asgi_app
from .result_queue import ResultQueue

# Get logger for this module
logger = get_logger("bmcp-mcp-http")


class ServerManager:
    """Manages MCP server lifecycle and state"""

    def __init__(self):
        self._mcp_instance = None
        self._result_queue = ResultQueue()
        self._server_loop = None
        self._server_thread = None
        self._server_task = None
        self._uvicorn_server = (
            None  # Direct reference to uvicorn.Server for shutdown control
        )
        self._shutting_down = False
        self._auth_token_masked = None  # Masked auth token for logging
        # Event for shutdown coordination: set() = shutdown complete (not in progress)
        # cleared = shutdown in progress. Used to prevent starting during shutdown.
        self._shutdown_complete = threading.Event()

    def execute_on_main_thread(self, tool_name: str, arguments: dict) -> dict:
        """
        Execute a tool synchronously on Blender's main thread.

        This function schedules the tool execution on Blender's main thread using
        bpy.app.timers and waits for the result using a threading.Event().

        Args:
            tool_name: Name of the tool to execute ('blender_run_code')
            arguments: Tool arguments dictionary

        Returns:
            Tool execution result dictionary

        Raises:
            TimeoutError: If execution times out (configurable via TOOL_EXECUTION_TIMEOUT)
            RuntimeError: If execution fails
        """
        job_id = str(uuid.uuid4())

        # Register job and get synchronization event
        event = self._result_queue.register(job_id)

        def execute_in_main_thread():
            """Inner function that runs on Blender's main thread"""
            try:
                # Check if job was cancelled (timed out) before executing
                # This prevents executing code after the caller has already given up
                if self._result_queue.is_cancelled(job_id):
                    logger.debug(
                        "Skipping cancelled job %s - request already timed out",
                        job_id[:8],
                    )
                    return None

                # Execute the appropriate operator
                if tool_name == "blender_run_code":
                    code = arguments.get("code", "")
                    bpy.ops.bmcp.run_code(code=code, job_id=job_id)
                else:
                    raise ValueError(f"Unknown tool: {tool_name}")

                # Retrieve result from window manager using unique job_id key
                wm = bpy.context.window_manager
                result_key = f"mcp_result_{job_id}"
                result_json = wm.get(result_key, "{}")
                result = (
                    json.loads(result_json)
                    if isinstance(result_json, str)
                    else result_json
                )

                # Cleanup the unique result key after reading
                if result_key in wm:
                    del wm[result_key]

                if result.get("status") == "success":
                    # Pass the full result dict to the tool - it contains "output" key
                    self._result_queue.set_success(job_id, result)
                else:
                    error_msg = result.get("error", "Unknown error")
                    raise RuntimeError(error_msg)

            except Exception as e:
                # Catch all exceptions (but not BaseException like SystemExit/KeyboardInterrupt)
                self._result_queue.set_error(job_id, str(e))

        # Schedule execution on main thread with error handling
        try:
            bpy.app.timers.register(execute_in_main_thread, first_interval=0.0)
        except Exception as e:
            # Timer registration failed - clean up and raise immediately
            self._result_queue.cleanup(job_id)
            raise RuntimeError(
                f"Failed to schedule execution on Blender's main thread: {e}. "
                f"This can happen if Blender is in an invalid state (e.g., headless mode, "
                f"during shutdown, or from a background thread without timer access)."
            )

        # Wait for completion with configurable timeout
        # Note: Python exec() cannot be truly interrupted, but timeout allows the
        # request to fail cleanly instead of hanging forever
        try:
            completed = event.wait(timeout=TOOL_EXECUTION_TIMEOUT)

            if not completed:
                # Timeout occurred - mark as cancelled so timer skips execution
                self._result_queue.mark_cancelled(job_id)
                logger.warning(
                    "Job %s timed out after %s seconds - marked as cancelled",
                    job_id[:8],
                    TOOL_EXECUTION_TIMEOUT,
                )
                timeout_msg = (
                    f"Tool execution timed out after {TOOL_EXECUTION_TIMEOUT} seconds. "
                    f"The scheduled operation was cancelled and will not execute. "
                    f"If Blender appears frozen, it may be processing a previous request. "
                    f"To increase the timeout, modify TOOL_EXECUTION_TIMEOUT in config.py "
                    f"or set it to None for infinite wait."
                )
                raise TimeoutError(timeout_msg)

            # Get result (cleanup is handled in finally block)
            status, result, error = self._result_queue.get_result(job_id)

            if status == "success":
                return result
            else:
                raise RuntimeError(error)

        except KeyError:
            # Entry was already cleaned up (shouldn't happen normally)
            raise RuntimeError("Result entry was unexpectedly removed")
        finally:
            # Always cleanup - this handles both success and error cases
            self._result_queue.cleanup(job_id)

    def _initialize_mcp(self):
        """
        Initialize MCP server with all tools and resources.
        This is called when the server starts.
        """
        if self._mcp_instance is not None:
            return self._mcp_instance  # Already initialized

        try:
            # Create MCP server instance
            mcp = MCPServer("Blender bMCP")

            # Initialize tools, resources, and prompts systems
            tools.register_tools(self.execute_on_main_thread, anyio)
            resources.register_resources()
            prompts.register_prompts()

            # Clean up any stale properties from previous sessions or crashed operations
            cleanup_stale_properties()

            # Sync caches from decorator registries for fast lookup
            mcp.sync_tools()
            mcp.sync_resources()
            mcp.sync_prompts()

            self._mcp_instance = mcp
            logger.info("MCP server initialized successfully")
            return mcp

        except (AttributeError, TypeError, ValueError) as e:
            logger.error("Error initializing MCP server: %s", e)
            traceback.print_exc()
            return None
        except Exception as e:
            # Catch Exception (not BaseException) to allow KeyboardInterrupt/SystemExit to propagate
            logger.error("Unexpected error initializing MCP server: %s", e)
            traceback.print_exc()
            return None

    def _get_server_config(self):
        """
        Get server configuration from preferences.

        Returns:
            tuple: (network_access, port, enable_logs)
        """
        addon_prefs = bpy.context.preferences.addons.get(base_package)
        if addon_prefs:
            network_access = addon_prefs.preferences.network_access
            port = addon_prefs.preferences.server_port
            enable_logs = addon_prefs.preferences.enable_logs
            auth_token = addon_prefs.preferences.auth_token
            auth_required = addon_prefs.preferences.auth_required
        else:
            network_access = False
            port = DEFAULT_SERVER_PORT
            enable_logs = False
            auth_token = ""
            auth_required = False

        return network_access, port, enable_logs, auth_token, auth_required

    def _setup_logging(self, enable_logs):
        """
        Configure logging based on preferences.

        Args:
            enable_logs: Whether to enable debug logging
        """
        setup_logging(logging.DEBUG if enable_logs else logging.WARNING)

        if enable_logs:
            logger.setLevel(logging.DEBUG)
            logger.debug("Debug logging enabled via preferences")
        else:
            logger.setLevel(logging.WARNING)

    def _create_uvicorn_server(
        self, mcp, bind_address, port, enable_logs, auth_token, auth_required
    ):
        """
        Create and configure uvicorn server instance.

        Args:
            mcp: MCPServer instance
            bind_address: Host to bind to
            port: Port to bind to
            enable_logs: Whether to enable debug logging
            auth_token: Authentication token
            auth_required: Whether authentication is required

        Returns:
            BackgroundServer: Configured uvicorn server
        """
        # Create ASGI app with SSE (/sse) and JSON-RPC (/http) endpoints
        # Pass is_shutting_down function for 503 response during shutdown
        app = create_asgi_app(
            mcp,
            bind_address,
            port,
            auth_token,
            auth_required,
            is_shutting_down_fn=self.is_shutting_down,
        )

        # Create uvicorn config with optimizations
        config = uvicorn.Config(
            app=app,
            host=bind_address,
            port=port,
            log_level="warning" if not enable_logs else "debug",
            timeout_graceful_shutdown=1,  # Allow 1 second for graceful shutdown
            lifespan="on",
            ws="websockets",
            limit_concurrency=50,  # Reasonable limit to prevent resource exhaustion
            backlog=2048,  # Larger connection queue
            timeout_keep_alive=5,  # Keep connections alive
        )

        # Custom Server class that disables signal handlers for background thread
        class BackgroundServer(uvicorn.Server):
            def install_signal_handlers(self):
                pass  # Disable signal handlers - we're in a background thread

        return BackgroundServer(config=config)

    def _start_background_loop(self):
        """
        Create and start asyncio event loop in a background thread.

        Returns:
            tuple: (event_loop, thread)
        """
        # Create event loop
        event_loop = asyncio.new_event_loop()

        def start_loop(loop):
            """Run the asyncio event loop in a background thread"""
            asyncio.set_event_loop(loop)
            loop.run_forever()

        # Start background thread
        thread = threading.Thread(
            target=start_loop,
            args=(event_loop,),
            daemon=True,
            name="MCP-Server",
        )
        thread.start()

        return event_loop, thread

    def _run_uvicorn_in_loop(self, uvicorn_server, event_loop):
        """
        Run uvicorn server in the event loop.

        Args:
            uvicorn_server: BackgroundServer instance
            event_loop: asyncio event loop

        Returns:
            Future: Server task future
        """

        async def run_server():
            """Coroutine to run the uvicorn server"""
            try:
                await uvicorn_server.serve()
            except asyncio.CancelledError:
                logger.info("Server stopped gracefully")
                raise
            except (OSError, SystemExit) as e:
                logger.error("Failed to start server: %s", e)
                raise

        return asyncio.run_coroutine_threadsafe(run_server(), event_loop)

    def _wait_for_server_startup(self, timeout: float = SERVER_STARTUP_TIMEOUT):
        """
        Wait for server to start with timeout.

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            bool: True if server started, False if timeout or error
        """
        start_time = time.time()
        while not self._uvicorn_server.started:
            # Check if server task failed
            if self._server_task.done():
                try:
                    self._server_task.result()
                except Exception as e:
                    logger.error("Server failed to start: %s", e)
                    return False

            # Check timeout
            if time.time() - start_time > timeout:
                logger.error("Server startup timeout")
                return False

            time.sleep(0.01)

        return True

    def _log_server_started(self, bind_address, port, network_access):
        """
        Log server startup information.

        Args:
            bind_address: Host the server is bound to
            port: Port the server is bound to
            network_access: Whether network access is enabled
        """
        logger.info("MCP server started")
        logger.info("SSE endpoint: http://%s:%d/sse", bind_address, port)
        logger.info("HTTP endpoint: http://%s:%d/http", bind_address, port)

        if network_access:
            logger.warning(
                "SECURITY: Network access enabled (binds to 0.0.0.0) - "
                "Server allows arbitrary code execution from network! "
                "Only use on trusted networks."
            )
        else:
            logger.info("Localhost only (binds to 127.0.0.1)")

        logger.info(
            "Authentication: %s",
            "ENABLED" if self._auth_token_masked else "DISABLED (Insecure!)",
        )

    def _cleanup_server_state(self):
        """Clean up server state after failed start."""
        self._server_loop = None
        self._server_thread = None
        self._server_task = None
        self._uvicorn_server = None

    def start(self):
        """
        Start the MCP HTTP server in a background thread.

        Returns:
            bool: True if server started successfully, False otherwise
        """
        # Pre-flight checks
        mcp = self._initialize_mcp()
        if mcp is None:
            logger.error("Failed to initialize MCP")
            return False

        if self._server_loop is not None:
            logger.info("Server already running")
            return False

        if self._shutting_down:
            logger.warning("Server is still shutting down, please wait a moment")
            return False

        try:
            # Get configuration from preferences
            network_access, port, enable_logs, auth_token, auth_required = (
                self._get_server_config()
            )
            bind_address = "0.0.0.0" if network_access else "127.0.0.1"

            # Validate configuration before starting
            validation = validate_config(
                port, network_access, auth_required, auth_token
            )
            for warning in validation.warnings:
                logger.warning("Config: %s", warning)
            if not validation.valid:
                for error in validation.errors:
                    logger.error("Config error: %s", error)
                return False

            # Store masked token for logging (only if token is long enough to mask)
            if auth_token and auth_required and len(auth_token) >= 8:
                self._auth_token_masked = f"{auth_token[:4]}...{auth_token[-4:]}"
            elif auth_token and auth_required:
                self._auth_token_masked = "****"  # Token too short to mask safely
            else:
                self._auth_token_masked = None

            # Configure logging
            self._setup_logging(enable_logs)

            # Reset shutdown event
            self._shutdown_complete.set()

            # Create and configure uvicorn server
            self._uvicorn_server = self._create_uvicorn_server(
                mcp, bind_address, port, enable_logs, auth_token, auth_required
            )

            # Start background event loop
            self._server_loop, self._server_thread = self._start_background_loop()

            # Run uvicorn in the event loop
            self._server_task = self._run_uvicorn_in_loop(
                self._uvicorn_server, self._server_loop
            )

            # Wait for server to start
            if not self._wait_for_server_startup():
                self.stop()
                return False

            # Log success
            self._log_server_started(bind_address, port, network_access)
            return True

        except (OSError, RuntimeError, ValueError) as e:
            logger.error("Error starting server: %s", e)
            traceback.print_exc()
            self._cleanup_server_state()
            return False
        except Exception as e:
            # Catch Exception (not BaseException) to allow KeyboardInterrupt/SystemExit to propagate
            logger.error("Unexpected error starting server: %s", e)
            traceback.print_exc()
            self._cleanup_server_state()
            return False

    def stop(self):
        """Stop the MCP server with proper uvicorn shutdown sequence."""
        if self._server_loop is not None:
            try:
                # Mark as shutting down FIRST - this prevents new requests
                self._shutting_down = True
                self._shutdown_complete.clear()

                # Capture references before clearing
                server_loop = self._server_loop
                uvicorn_server = self._uvicorn_server
                server_thread = self._server_thread

                # Clear references immediately to prevent is_running from returning True
                self._server_loop = None
                self._server_thread = None
                self._server_task = None
                self._uvicorn_server = None

                # Proper shutdown in background thread (non-blocking)
                def graceful_shutdown():
                    """Properly shutdown uvicorn server and event loop"""
                    try:
                        # Step 1: Signal uvicorn to exit gracefully
                        if uvicorn_server:
                            uvicorn_server.should_exit = True
                            logger.debug("Signaled uvicorn to exit")

                        # Step 2: Cancel all pending tasks in the event loop
                        # Use safer approach that handles loop state
                        if server_loop is not None:
                            try:
                                if server_loop.is_running():

                                    async def cancel_all_tasks():
                                        """Cancel all running tasks except current one"""
                                        try:
                                            current = asyncio.current_task()
                                            tasks = [
                                                t
                                                for t in asyncio.all_tasks(server_loop)
                                                if not t.done() and t is not current
                                            ]
                                            for task in tasks:
                                                task.cancel()
                                            # Give tasks a moment to cancel
                                            if tasks:
                                                await asyncio.sleep(0.1)
                                        except RuntimeError:
                                            pass  # Loop may be closing

                                    try:
                                        future = asyncio.run_coroutine_threadsafe(
                                            cancel_all_tasks(), server_loop
                                        )
                                        future.result(
                                            timeout=1.0
                                        )  # Wait up to 1 second
                                    except (
                                        RuntimeError,
                                        TimeoutError,
                                        asyncio.CancelledError,
                                    ):
                                        pass  # Loop may already be stopped or closing
                            except RuntimeError:
                                pass  # Loop may be closed

                        # Step 3: Wait for graceful shutdown (shorter timeout)
                        if server_thread and server_thread.is_alive():
                            server_thread.join(timeout=GRACEFUL_SHUTDOWN_TIMEOUT)

                        # Step 4: If still running after timeout, force stop the loop
                        if server_thread and server_thread.is_alive():
                            logger.debug(
                                "Server still running after timeout, forcing stop"
                            )
                            try:
                                if (
                                    server_loop is not None
                                    and not server_loop.is_closed()
                                ):
                                    server_loop.call_soon_threadsafe(server_loop.stop)
                            except RuntimeError:
                                pass  # Loop may already be stopped or closed

                            # Final join with very short timeout
                            server_thread.join(timeout=0.5)

                        logger.info("Server stopped")

                    except Exception as e:
                        logger.warning("Error during shutdown: %s", e)
                    finally:
                        # Clear pending resource operations
                        try:
                            cleared = clear_pending_operations()
                            if cleared:
                                logger.debug("Cleared %d pending operations", cleared)
                        except Exception:
                            pass  # Cleanup is best-effort

                        # Reset MCP instance to force re-initialization on next start
                        # This ensures tools/resources are re-synced from registries
                        if self._mcp_instance:
                            try:
                                self._mcp_instance.clear()
                            except Exception:
                                pass
                            self._mcp_instance = None
                            logger.debug("Reset MCP server instance")

                        # Mark shutdown as complete
                        self._shutdown_complete.set()

                        # Schedule clearing the shutdown flag on main thread
                        def clear_flag():
                            self._shutting_down = False
                            return None

                        try:
                            bpy.app.timers.register(clear_flag, first_interval=0.3)
                        except Exception:
                            # If we can't register timer, just clear the flag directly
                            self._shutting_down = False

                # Run shutdown in a separate thread so we don't block Blender
                shutdown_thread = threading.Thread(
                    target=graceful_shutdown, daemon=True
                )
                shutdown_thread.start()
                return True  # Shutdown initiated successfully

            except (RuntimeError, AttributeError) as e:
                logger.error("Error stopping server: %s", e)
                self._shutting_down = False
                self._shutdown_complete.set()
                return False  # Error during shutdown
            except Exception as e:
                # Catch Exception (not BaseException) to allow KeyboardInterrupt/SystemExit to propagate
                logger.error("Unexpected error stopping server: %s", e)
                traceback.print_exc()
                self._shutting_down = False
                self._shutdown_complete.set()
                return False  # Error during shutdown
        return False  # Server was not running

    def is_running(self) -> bool:
        """Check if the MCP server is currently running.

        Thread-safe: captures local reference to prevent TOCTOU race conditions.
        """
        # Capture local reference to prevent race condition where
        # _server_loop is set to None between the None check and is_running() call
        loop = self._server_loop
        if loop is None:
            return False
        try:
            return loop.is_running()
        except RuntimeError:
            # Loop may have been closed between check and call
            return False

    def is_shutting_down(self):
        """Check if the server is in the process of shutting down."""
        return self._shutting_down

    def wait_for_shutdown(self, timeout=3.0):
        """Wait for shutdown to complete. Returns True if completed, False if timeout."""
        return self._shutdown_complete.wait(timeout=timeout)


# Module-level singleton
_server_manager = ServerManager()


# Module-level wrapper functions for backward compatibility
def execute_on_main_thread(tool_name: str, arguments: dict) -> dict:
    """Wrapper function for ServerManager.execute_on_main_thread"""
    return _server_manager.execute_on_main_thread(tool_name, arguments)


def start_mcp_server():
    """Wrapper function for ServerManager.start"""
    return _server_manager.start()


def stop_mcp_server():
    """Wrapper function for ServerManager.stop"""
    return _server_manager.stop()


def is_server_running():
    """Wrapper function for ServerManager.is_running"""
    return _server_manager.is_running()


def is_server_shutting_down():
    """Wrapper function for ServerManager.is_shutting_down"""
    return _server_manager.is_shutting_down()


def wait_for_shutdown(timeout=3.0):
    """
    Wait for server shutdown to complete.

    Args:
        timeout: Maximum time to wait in seconds (default: 3.0)

    Returns:
        bool: True if shutdown completed, False if timeout
    """
    return _server_manager.wait_for_shutdown(timeout=timeout)


# ============================================================================
# SERVER LIFECYCLE HOOKS
# ============================================================================


def register():
    """Register hook - called when transport module is registered"""
    pass


def unregister():
    """Unregister hook - stop server on addon unload"""
    stop_mcp_server()
