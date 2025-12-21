"""
ASGI Application - Dual-Mode MCP Transport

Creates Starlette ASGI app with SSE and JSON-RPC endpoints for MCP protocol.
Supports both SSE (with session tracking) and synchronous HTTP transports.

SSE Queue Management:
- Each SSE connection gets a per-session message queue (configurable size)
- If client doesn't consume messages fast enough, oldest messages are dropped
- Clients are notified when messages are dropped via a special event
- Queue is created on GET /sse and cleaned up on disconnect
- Background tasks push responses to queue, SSE stream pops and sends

Execution Queue:
- All requests (tools/resources) execute on Blender's main thread via timers
- Blender processes timers sequentially - natural serialization
- No shared execution queue needed, bpy.app.timers handles scheduling

Shutdown Handling:
- Returns 503 Service Unavailable when server is shutting down
- Prevents new requests from starting during shutdown
"""

import asyncio
import json
import secrets
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional

from sse_starlette.sse import EventSourceResponse
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..core import MCPServer
from ..handlers import dispatch_request
from ..logger import clear_request_id, get_logger, set_request_id
from ..utils.config import SSE_POLL_INTERVAL, SSE_QUEUE_SIZE

# Logger for request logging
request_logger = get_logger("bmcp-requests")
# Logger for authentication events
auth_logger = get_logger("bmcp-auth")

# Track background tasks for cleanup on shutdown
_background_tasks: set[asyncio.Task] = set()

# SSE session timeout (30 minutes)
SSE_SESSION_TIMEOUT: float = 1800.0
# SSE cleanup interval (5 minutes)
SSE_CLEANUP_INTERVAL: float = 300.0

# Reference to cleanup task for cancellation
_cleanup_task: Optional[asyncio.Task] = None


async def cancel_background_tasks() -> int:
    """Cancel all tracked background tasks (called on shutdown).

    Returns:
        Number of tasks that were cancelled.
    """
    global _cleanup_task

    # Cancel cleanup task first
    if _cleanup_task and not _cleanup_task.done():
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            pass

    # Cancel all tracked tasks
    count = len(_background_tasks)
    for task in list(_background_tasks):
        task.cancel()

    # Wait for all to complete
    if _background_tasks:
        await asyncio.gather(*_background_tasks, return_exceptions=True)

    _background_tasks.clear()
    return count


async def cleanup_stale_sse_sessions(sse_queues: dict) -> int:
    """Remove stale SSE sessions that haven't had activity.

    Args:
        sse_queues: Dictionary of session_id -> SSEQueue

    Returns:
        Number of sessions cleaned up.
    """
    now = time.time()
    stale_sessions = [
        session_id
        for session_id, queue in sse_queues.items()
        if now - queue.last_activity > SSE_SESSION_TIMEOUT
    ]

    for session_id in stale_sessions:
        sse_queues.pop(session_id, None)
        request_logger.debug("Cleaned up stale SSE session: %s", session_id[:8])

    if stale_sessions:
        request_logger.info("Cleaned up %d stale SSE sessions", len(stale_sessions))

    return len(stale_sessions)


async def _sse_cleanup_loop(sse_queues: dict) -> None:
    """Periodic cleanup task for stale SSE sessions."""
    while True:
        try:
            await asyncio.sleep(SSE_CLEANUP_INTERVAL)
            await cleanup_stale_sse_sessions(sse_queues)
        except asyncio.CancelledError:
            break
        except Exception as e:
            request_logger.debug("SSE cleanup error (non-fatal): %s", e)


@dataclass
class SSEQueue:
    """SSE message queue with drop tracking and event-based notification."""

    messages: deque
    dropped_count: int = 0
    last_drop_notified: bool = True  # True = no pending notification
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    _event: asyncio.Event = field(default_factory=asyncio.Event)

    def append(self, message: dict) -> bool:
        """
        Append a message to the queue and signal waiting consumers.
        Returns True if message was added, False if dropped.
        """
        self.last_activity = time.time()
        if len(self.messages) >= self.messages.maxlen:
            # Queue is full - oldest message will be dropped
            self.dropped_count += 1
            self.last_drop_notified = False
            self.messages.append(message)
            self._event.set()  # Signal even when dropping - consumer needs to know
            return False
        self.messages.append(message)
        self._event.set()  # Signal that a new message is available
        return True

    def popleft(self) -> Optional[dict]:
        """Pop the oldest message from the queue."""
        if self.messages:
            return self.messages.popleft()
        return None

    async def wait_for_message(self, timeout: float = SSE_POLL_INTERVAL) -> bool:
        """
        Wait for a message to be available (event-based, not polling).

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            True if a message is available, False if timeout occurred
        """
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
            self._event.clear()  # Reset for next wait
            return True
        except asyncio.TimeoutError:
            return False

    def get_drop_notification(self) -> Optional[dict]:
        """
        Get a drop notification if messages were dropped since last check.
        Returns None if no notification needed.
        """
        if not self.last_drop_notified and self.dropped_count > 0:
            self.last_drop_notified = True
            count = self.dropped_count
            self.dropped_count = 0
            return {
                "event": "warning",
                "data": json.dumps(
                    {
                        "type": "messages_dropped",
                        "count": count,
                        "message": f"{count} message(s) were dropped due to slow consumption. "
                        f"Consider processing messages faster or increasing SSE_QUEUE_SIZE.",
                    }
                ),
            }
        return None

    def __len__(self):
        return len(self.messages)

    def __bool__(self):
        return bool(self.messages)


class ShutdownMiddleware(BaseHTTPMiddleware):
    """
    Middleware to reject requests during server shutdown.

    Returns 503 Service Unavailable when the server is shutting down,
    preventing new requests from starting during the shutdown process.
    """

    async def dispatch(self, request, call_next):
        # Check if server is shutting down
        if hasattr(request.app.state, "is_shutting_down"):
            if request.app.state.is_shutting_down():
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {
                            "code": -32000,
                            "message": "Server is shutting down. Please retry after the server restarts.",
                        },
                    },
                    status_code=503,
                    headers={"Retry-After": "5"},
                )
        return await call_next(request)


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware to enforce token-based authentication.

    Checks for token in:
    1. Authorization header: 'Bearer <token>' (preferred, secure)
    2. Query parameter: '?token=<token>' (fallback for SSE/EventSource, localhost only)

    Security notes:
    - Uses constant-time comparison to prevent timing attacks
    - Query parameter auth is DISABLED when network_access=True (tokens leak in URLs)
    - Logs warning when query parameter auth is used
    """

    def __init__(
        self,
        app,
        auth_token: str,
        auth_required: bool = True,
        network_access: bool = False,
    ):
        super().__init__(app)
        self.auth_token = auth_token
        self.auth_required = auth_required
        self.network_access = network_access

    async def dispatch(self, request, call_next):
        # Skip auth for health check (allows load balancers/monitoring)
        if request.url.path == "/health":
            return await call_next(request)

        # Skip auth if not required
        if not self.auth_required:
            return await call_next(request)

        # Skip auth if no token is configured (insecure mode) - fallback
        if not self.auth_token:
            return await call_next(request)

        # Check Authorization header (preferred method)
        auth_header = request.headers.get("Authorization")
        if auth_header:
            if auth_header.startswith("Bearer "):
                # Extract token after "Bearer " prefix (7 characters)
                # Use slicing instead of split to handle edge cases safely
                token = auth_header[7:].strip()
                if token and secrets.compare_digest(token, self.auth_token):
                    return await call_next(request)

        # Check query parameter (fallback for EventSource/SSE which cannot set headers)
        # WARNING: Tokens in URLs can leak in logs, browser history, and referrer headers
        # SECURITY: Query param auth is DISABLED in network mode to prevent token leakage
        query_token = request.query_params.get("token")
        if query_token:
            if self.network_access:
                # Reject query param auth in network mode - tokens in URLs are insecure
                auth_logger.warning(
                    "Query parameter authentication rejected in network mode. "
                    "Use Bearer token in Authorization header instead. Client: %s, Path: %s",
                    request.client.host if request.client else "unknown",
                    request.url.path,
                )
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {
                            "code": -32001,
                            "message": "Query parameter authentication is disabled in network mode. "
                            "Use Bearer token in Authorization header instead.",
                        },
                    },
                    status_code=401,
                )
            elif secrets.compare_digest(query_token, self.auth_token):
                auth_logger.warning(
                    "Authentication via query parameter (less secure). Client: %s, Path: %s",
                    request.client.host if request.client else "unknown",
                    request.url.path,
                )
                return await call_next(request)

        # Authentication failed
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32001,
                    "message": "Unauthorized: Invalid or missing token",
                },
            },
            status_code=401,
        )


class StatsMiddleware(BaseHTTPMiddleware):
    """Track request statistics for health endpoint."""

    async def dispatch(self, request, call_next):
        # Increment request count
        if hasattr(request.app.state, "stats"):
            request.app.state.stats["request_count"] += 1

        try:
            response = await call_next(request)
            # Track errors (5xx status codes)
            if response.status_code >= 500 and hasattr(request.app.state, "stats"):
                request.app.state.stats["error_count"] += 1
            return response
        except Exception:
            if hasattr(request.app.state, "stats"):
                request.app.state.stats["error_count"] += 1
            raise


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log all requests with timing and request ID context."""

    async def dispatch(self, request, call_next):
        # Use existing request ID from header, or generate new one
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        set_request_id(request_id)
        start = time.perf_counter()

        try:
            response = await call_next(request)
            ms = (time.perf_counter() - start) * 1000
            request_logger.info(
                "%s %s -> %d (%.2fms)",
                request.method,
                request.url.path,
                response.status_code,
                ms,
            )
            # Add request ID to response headers for tracing
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception as e:
            ms = (time.perf_counter() - start) * 1000
            request_logger.error(
                "%s %s -> ERROR (%.2fms): %s",
                request.method,
                request.url.path,
                ms,
                e,
            )
            raise
        finally:
            clear_request_id()


async def health_endpoint(request):
    """
    Health check endpoint - no auth required for monitoring tools.

    Returns server status, statistics, and diagnostic info.
    Accessible without authentication for load balancers and monitoring.
    """
    mcp_server = request.app.state.mcp_server
    sse_queues = request.app.state.sse_queues
    start_time = getattr(request.app.state, "start_time", time.time())
    stats = getattr(request.app.state, "stats", {})

    return JSONResponse(
        {
            "status": "healthy",
            "uptime_seconds": round(time.time() - start_time, 2),
            "connections": {"active_sse_sessions": len(sse_queues)},
            "statistics": {
                "total_requests": stats.get("request_count", 0),
                "error_count": stats.get("error_count", 0),
            },
            "server": {
                "name": mcp_server.name,
                "version": "1.0.0",
                "tools_count": len(mcp_server._tool_cache),
                "resources_count": len(mcp_server._resource_cache),
            },
        }
    )


async def sse_endpoint(request):
    """
    SSE endpoint for MCP-over-SSE transport (/sse).

    Follows MCP spec:
    - GET: Opens SSE stream, sends responses as events
    - POST: Accepts message (202), processes in background, sends response via stream
    """
    mcp_server = request.app.state.mcp_server
    sse_queues = request.app.state.sse_queues

    # Handle POST requests - client sending MCP messages
    if request.method == "POST":
        try:
            # Parse JSON-RPC message
            data = await request.json()
            method = data.get("method")
            params = data.get("params")
            msg_id = data.get("id")

            # Check for session ID in header (for SSE clients)
            session_id = request.headers.get("X-MCP-Session-ID")

            # Determine transport mode based on session
            if session_id and session_id in sse_queues:
                # SSE mode: Client has active stream, queue response
                async def process_and_queue():
                    try:
                        result = await dispatch_request(mcp_server, method, params)
                        response = {"jsonrpc": "2.0", "id": msg_id, "result": result}
                    except Exception as e:
                        response = {
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "error": {"code": -32603, "message": str(e)},
                        }

                    # Route to specific client's queue (secure!)
                    # Use try-except to handle race condition where connection closes
                    # between check and append (TOCTOU race)
                    try:
                        sse_queues[session_id].append(response)
                    except (KeyError, AttributeError):
                        # Connection closed before we could queue the response
                        # This is expected during disconnect - response is simply dropped
                        pass

                # Start background task and track it for cleanup
                task = asyncio.create_task(process_and_queue())
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)

                # Return 202 Accepted per MCP spec
                return Response(status_code=202)
            else:
                # Synchronous HTTP mode: No SSE session, return response immediately
                # Used by clients that don't support SSE or don't send session header
                try:
                    result = await dispatch_request(mcp_server, method, params)
                    return JSONResponse(
                        {"jsonrpc": "2.0", "id": msg_id, "result": result}
                    )
                except Exception as e:
                    return JSONResponse(
                        {
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "error": {"code": -32603, "message": str(e)},
                        }
                    )

        except Exception as e:
            # Parse error - return 400
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {str(e)}"},
                },
                status_code=400,
            )

    # Handle GET requests - SSE event stream
    async def event_generator():
        """Generate SSE events for server-to-client messages (event-based, not polling)."""
        # Generate unique session ID for this SSE connection
        session_id = str(uuid.uuid4())

        # Create message queue for this session with configurable limit
        # If client doesn't consume messages fast enough, oldest are dropped
        # and client is notified via warning event
        sse_queues[session_id] = SSEQueue(messages=deque(maxlen=SSE_QUEUE_SIZE))
        message_queue = sse_queues[session_id]

        try:
            # Send session ID to client (for POST request routing)
            yield {"event": "session", "data": json.dumps({"sessionId": session_id})}

            # Send endpoint info event
            yield {"event": "endpoint", "data": json.dumps({"type": "mcp_endpoint"})}

            # Main event loop - wait for events instead of polling
            while True:
                # First, check for drop notifications
                drop_notification = message_queue.get_drop_notification()
                if drop_notification:
                    yield drop_notification

                # Drain all available messages before waiting
                while True:
                    response = message_queue.popleft()
                    if response:
                        yield {"event": "message", "data": json.dumps(response)}
                    else:
                        break

                # Wait for new message or timeout (event-based, not polling)
                has_message = await message_queue.wait_for_message(
                    timeout=SSE_POLL_INTERVAL
                )
                if not has_message:
                    # Timeout - send keep-alive ping
                    yield {"event": "ping", "data": ""}

        except asyncio.CancelledError:
            pass
        finally:
            # Cleanup queue on disconnect
            if session_id in sse_queues:
                del sse_queues[session_id]

    return EventSourceResponse(event_generator())


async def rpc_endpoint(request):
    """
    JSON-RPC endpoint for plain HTTP transport (/http).

    Handles plain JSON-RPC requests from stdio_server.py bridge.
    """
    mcp_server = request.app.state.mcp_server

    # Parse JSON-RPC request
    try:
        data = await request.json()
    except Exception as e:
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {str(e)}"},
            },
            status_code=400,
        )

    # Extract JSON-RPC fields
    method = data.get("method")
    params = data.get("params")
    msg_id = data.get("id")
    jsonrpc_version = data.get("jsonrpc", "2.0")

    # Validate JSON-RPC structure
    if not method:
        return JSONResponse(
            {
                "jsonrpc": jsonrpc_version,
                "id": msg_id,
                "error": {
                    "code": -32600,
                    "message": "Invalid Request: method is required",
                },
            }
        )

    # Handle notifications (requests without id)
    is_notification = msg_id is None

    try:
        # Dispatch to protocol handler
        result = await dispatch_request(mcp_server, method, params)

        # For notifications, return 204 No Content
        if is_notification:
            return Response(status_code=204)

        # Return JSON-RPC success response
        return JSONResponse(
            {"jsonrpc": jsonrpc_version, "id": msg_id, "result": result}
        )

    except ValueError as e:
        # Method not found or invalid parameters
        if is_notification:
            return Response(status_code=204)

        return JSONResponse(
            {
                "jsonrpc": jsonrpc_version,
                "id": msg_id,
                "error": {"code": -32602, "message": f"Invalid params: {str(e)}"},
            }
        )

    except Exception as e:
        # Internal error
        if is_notification:
            return Response(status_code=204)

        return JSONResponse(
            {
                "jsonrpc": jsonrpc_version,
                "id": msg_id,
                "error": {"code": -32603, "message": f"Internal error: {str(e)}"},
            }
        )


def create_asgi_app(
    mcp_server: MCPServer,
    host: str = "127.0.0.1",
    port: int = 12097,
    auth_token: str = "",
    auth_required: bool = False,
    is_shutting_down_fn: Optional[Callable[[], bool]] = None,
) -> Starlette:
    """
    Create Starlette ASGI application with MCP endpoints.

    Args:
        mcp_server: MCPServer instance with registered tools and resources
        host: Server host address
        port: Server port
        auth_token: Authentication token (empty for no auth)
        auth_required: Whether authentication is required
        is_shutting_down_fn: Optional callable that returns True if server is shutting down

    Returns:
        Starlette: ASGI application
    """
    # Determine allowed origins based on host
    if host == "0.0.0.0":
        # Network access - allow all origins (security warning should be shown)
        allowed_origins = ["*"]
    else:
        # Localhost only - restrict to local origins
        allowed_origins = [
            "http://localhost",
            "http://127.0.0.1",
            f"http://localhost:{port}",
            f"http://127.0.0.1:{port}",
        ]

    # Create ASGI app with health endpoint (first for priority)
    app = Starlette(
        routes=[
            Route(
                "/health", health_endpoint, methods=["GET"]
            ),  # Health check (no auth)
            Route(
                "/sse", sse_endpoint, methods=["GET", "POST"]
            ),  # SSE + message handling
            Route(
                "/http", rpc_endpoint, methods=["POST"]
            ),  # JSON-RPC for stdio/plain HTTP
        ],
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=allowed_origins,
                allow_methods=["GET", "POST", "OPTIONS"],
                allow_headers=["*"],
                allow_credentials=True,
            ),
            Middleware(ShutdownMiddleware),  # Reject requests during shutdown
            Middleware(RequestLoggingMiddleware),  # Request logging with timing
            Middleware(StatsMiddleware),  # Statistics tracking
            Middleware(
                AuthMiddleware,
                auth_token=auth_token,
                auth_required=auth_required,
                network_access=(
                    host == "0.0.0.0"
                ),  # Disable query param auth in network mode
            ),
        ],
    )

    # Store MCP server instance and SSE queues in app state
    app.state.mcp_server = mcp_server
    app.state.sse_queues = {}  # Per-connection message queues for SSE
    app.state.start_time = time.time()  # Server start time for uptime calculation
    app.state.stats = {"request_count": 0, "error_count": 0}  # Request statistics
    # Store shutdown check function for ShutdownMiddleware
    app.state.is_shutting_down = is_shutting_down_fn or (lambda: False)

    # Startup event to start SSE cleanup task
    @app.on_event("startup")
    async def startup_event():
        global _cleanup_task
        _cleanup_task = asyncio.create_task(_sse_cleanup_loop(app.state.sse_queues))
        request_logger.debug("Started SSE session cleanup task")

    # Shutdown event to cancel background tasks
    @app.on_event("shutdown")
    async def shutdown_event():
        count = await cancel_background_tasks()
        if count > 0:
            request_logger.debug("Cancelled %d background tasks on shutdown", count)

    return app
