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
import threading
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Callable, Optional

from sse_starlette.sse import EventSourceResponse
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..core import MCPServer
from ..handlers import dispatch_request
from ..logger import clear_request_id, get_logger, set_request_id
from ..config import SSE_POLL_INTERVAL, SSE_QUEUE_SIZE

# Logger for request logging
request_logger = get_logger("bmcp-requests")
# Logger for authentication events
auth_logger = get_logger("bmcp-auth")

# SSE session timeout (30 minutes)
SSE_SESSION_TIMEOUT: float = 1800.0
# SSE cleanup interval (5 minutes)
SSE_CLEANUP_INTERVAL: float = 300.0

# Maximum request body size (10MB) to prevent DoS attacks
MAX_REQUEST_BODY_SIZE = 10 * 1024 * 1024


async def cancel_background_tasks(app: Starlette) -> int:
    """Cancel all tracked background tasks (called on shutdown).

    Args:
        app: Starlette application instance.

    Returns:
        Number of tasks that were cancelled.
    """
    cleanup_task = app.state.cleanup_task
    sse_queues_lock = app.state.sse_queues_lock
    background_tasks = app.state.background_tasks

    # Cancel cleanup task first with timeout to prevent hanging
    if cleanup_task and not cleanup_task.done():
        cleanup_task.cancel()
        try:
            await asyncio.wait_for(cleanup_task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    # Cancel all tracked tasks
    with sse_queues_lock:
        count = len(background_tasks)
        tasks_to_cancel = list(background_tasks)

    for task in tasks_to_cancel:
        task.cancel()

    # Wait for all to complete
    if tasks_to_cancel:
        await asyncio.gather(*tasks_to_cancel, return_exceptions=True)

    with sse_queues_lock:
        background_tasks.clear()
    return count


async def cleanup_stale_sse_sessions(sse_queues: dict, sse_queues_lock: threading.Lock) -> int:
    """Remove stale SSE sessions that haven't had activity.

    Args:
        sse_queues: Dictionary of session_id -> SSEQueue
        sse_queues_lock: Lock for thread-safe access to sse_queues

    Returns:
        Number of sessions cleaned up.
    """
    now = time.time()
    with sse_queues_lock:
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


async def _sse_cleanup_loop(sse_queues: dict, sse_queues_lock: threading.Lock) -> None:
    """Periodic cleanup task for stale SSE sessions."""
    while True:
        try:
            await asyncio.sleep(SSE_CLEANUP_INTERVAL)
            await cleanup_stale_sse_sessions(sse_queues, sse_queues_lock)
        except asyncio.CancelledError:
            break
        except Exception as e:
            request_logger.debug("SSE cleanup error (non-fatal): %s", e)


@dataclass
class SSEQueue:
    """SSE message queue with drop tracking and event-based notification.

    Thread-safe: All public methods use internal lock for synchronization.
    Uses loop.call_soon_threadsafe for safe cross-thread event signaling.
    """

    messages: deque
    dropped_count: int = 0
    last_drop_notified: bool = True  # True = no pending notification
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    _event: asyncio.Event = field(default_factory=asyncio.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _loop: Optional[asyncio.AbstractEventLoop] = field(default=None)

    def _safe_set_event(self) -> None:
        """Signal the event in a thread-safe manner."""
        if self._loop is not None and self._loop.is_running():
            try:
                self._loop.call_soon_threadsafe(self._event.set)
            except RuntimeError:
                pass
        else:
            self._event.set()

    def append(self, message: dict) -> bool:
        """
        Append a message to the queue and signal waiting consumers.
        Returns True if message was added, False if dropped.
        Thread-safe.
        """
        with self._lock:
            self.last_activity = time.time()
            if (
                self.messages.maxlen is not None
                and len(self.messages) >= self.messages.maxlen
            ):
                # Queue is full - oldest message will be dropped
                self.dropped_count += 1
                self.last_drop_notified = False
                self.messages.append(message)
                self._safe_set_event()
                return False
            self.messages.append(message)
            self._safe_set_event()
            return True

    def popleft(self) -> Optional[dict]:
        """Pop the oldest message from the queue. Thread-safe."""
        with self._lock:
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
            self._event.clear()
            return True
        except asyncio.TimeoutError:
            return False

    def get_drop_notification(self) -> Optional[dict]:
        """
        Get a drop notification if messages were dropped since last check.
        Returns None if no notification needed. Thread-safe.
        """
        with self._lock:
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
        with self._lock:
            return len(self.messages)

    def __bool__(self):
        with self._lock:
            return bool(self.messages)


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Middleware to limit request body size and prevent DoS attacks."""

    async def dispatch(self, request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_REQUEST_BODY_SIZE:
                    return JSONResponse(
                        {
                            "jsonrpc": "2.0",
                            "id": None,
                            "error": {
                                "code": -32600,
                                "message": f"Request body too large. Maximum size is {MAX_REQUEST_BODY_SIZE // (1024 * 1024)}MB.",
                            },
                        },
                        status_code=413,
                    )
            except ValueError:
                pass

        # Also enforce actual body size
        if request.method in ("POST", "PUT", "PATCH"):
            body = await request.body()
            if len(body) > MAX_REQUEST_BODY_SIZE:
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {
                            "code": -32600,
                            "message": f"Request body too large. Maximum size is {MAX_REQUEST_BODY_SIZE // (1024 * 1024)}MB.",
                        },
                    },
                    status_code=413,
                )

        return await call_next(request)


class ShutdownMiddleware(BaseHTTPMiddleware):
    """Middleware to reject requests during server shutdown."""

    async def dispatch(self, request, call_next):
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
        if request.url.path == "/health":
            return await call_next(request)

        if not self.auth_required:
            return await call_next(request)

        if not self.auth_token:
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if auth_header:
            if auth_header.startswith("Bearer "):
                token = auth_header[7:].strip()
                if token and secrets.compare_digest(token, self.auth_token):
                    return await call_next(request)

        query_token = request.query_params.get("token")
        if query_token:
            if self.network_access:
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
        if hasattr(request.app.state, "stats"):
            request.app.state.stats["request_count"] += 1

        try:
            response = await call_next(request)
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


async def health_endpoint(request: Request):
    """Health check endpoint - no auth required for monitoring tools."""
    mcp_server = request.app.state.mcp_server
    start_time = getattr(request.app.state, "start_time", time.time())

    return JSONResponse(
        {
            "status": "healthy",
            "uptime_seconds": round(time.time() - start_time, 2),
        }
    )


async def debug_endpoint(request: Request):
    """Debug endpoint with detailed server stats - requires auth."""
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
                "tools_count": mcp_server.tool_count,
                "resources_count": mcp_server.resource_count,
            },
        }
    )


async def sse_endpoint(request: Request):
    """SSE endpoint for MCP-over-SSE transport (/sse)."""
    mcp_server = request.app.state.mcp_server
    sse_queues = request.app.state.sse_queues
    sse_queues_lock = request.app.state.sse_queues_lock
    background_tasks = request.app.state.background_tasks

    if request.method == "POST":
        try:
            data = await request.json()
            method = data.get("method")
            params = data.get("params")
            msg_id = data.get("id")

            session_id = request.headers.get("X-MCP-Session-ID")

            with sse_queues_lock:
                has_session = session_id and session_id in sse_queues
            if has_session:
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

                    with sse_queues_lock:
                        queue = sse_queues.get(session_id)
                    if queue:
                        try:
                            queue.append(response)
                        except AttributeError:
                            pass

                task = asyncio.create_task(process_and_queue())
                with sse_queues_lock:
                    background_tasks.add(task)
                task.add_done_callback(lambda t: background_tasks.discard(t))

                return Response(status_code=202)
            else:
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
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {str(e)}"},
                },
                status_code=400,
            )

    async def event_generator():
        """Generate SSE events for server-to-client messages."""
        session_id = str(uuid.uuid4())

        message_queue = SSEQueue(
            messages=deque(maxlen=SSE_QUEUE_SIZE),
            _loop=asyncio.get_running_loop(),
        )
        with sse_queues_lock:
            sse_queues[session_id] = message_queue

        try:
            yield {"event": "session", "data": json.dumps({"sessionId": session_id})}
            yield {"event": "endpoint", "data": json.dumps({"type": "mcp_endpoint"})}

            while True:
                drop_notification = message_queue.get_drop_notification()
                if drop_notification:
                    yield drop_notification

                while True:
                    response = message_queue.popleft()
                    if response:
                        yield {"event": "message", "data": json.dumps(response)}
                    else:
                        break

                has_message = await message_queue.wait_for_message(
                    timeout=SSE_POLL_INTERVAL
                )
                if not has_message:
                    yield {"event": "ping", "data": ""}

        except asyncio.CancelledError:
            pass
        finally:
            with sse_queues_lock:
                sse_queues.pop(session_id, None)

    return EventSourceResponse(event_generator())


async def rpc_endpoint(request: Request):
    """JSON-RPC endpoint for plain HTTP transport (/http)."""
    mcp_server = request.app.state.mcp_server

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

    method = data.get("method")
    params = data.get("params")
    msg_id = data.get("id")
    jsonrpc_version = data.get("jsonrpc", "2.0")

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

    is_notification = msg_id is None

    try:
        result = await dispatch_request(mcp_server, method, params)

        if is_notification:
            return Response(status_code=204)

        return JSONResponse(
            {"jsonrpc": jsonrpc_version, "id": msg_id, "result": result}
        )

    except ValueError as e:
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
    if host == "0.0.0.0":
        # Network mode: allow all origins but WITHOUT credentials to prevent
        # cross-site attacks. Auth uses Bearer tokens (not cookies), so
        # allow_credentials is not needed.
        allowed_origins = ["*"]
        allow_credentials = False
    else:
        allowed_origins = [
            "http://localhost",
            "http://127.0.0.1",
            f"http://localhost:{port}",
            f"http://127.0.0.1:{port}",
        ]
        allow_credentials = True

    @asynccontextmanager
    async def lifespan(app: Starlette):
        # Initialize mutable state on app.state
        app.state.background_tasks = set()
        app.state.cleanup_task = None
        app.state.sse_queues_lock = threading.Lock()
        app.state.sse_queues = {}
        app.state.start_time = time.time()
        app.state.stats = {"request_count": 0, "error_count": 0}
        app.state.mcp_server = mcp_server
        app.state.is_shutting_down = is_shutting_down_fn or (lambda: False)

        # Start cleanup task
        app.state.cleanup_task = asyncio.create_task(
            _sse_cleanup_loop(app.state.sse_queues, app.state.sse_queues_lock)
        )
        request_logger.debug("Started SSE session cleanup task")

        yield

        # Shutdown
        count = await cancel_background_tasks(app)
        if count > 0:
            request_logger.debug("Cancelled %d background tasks on shutdown", count)

    app = Starlette(
        routes=[
            Route("/health", health_endpoint, methods=["GET"]),
            Route("/debug", debug_endpoint, methods=["GET"]),
            Route("/sse", sse_endpoint, methods=["GET", "POST"]),
            Route("/http", rpc_endpoint, methods=["POST"]),
        ],
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=allowed_origins,
                allow_methods=["GET", "POST", "OPTIONS"],
                allow_headers=["*"],
                allow_credentials=allow_credentials,
            ),
            Middleware(RequestSizeLimitMiddleware),
            Middleware(ShutdownMiddleware),
            Middleware(RequestLoggingMiddleware),
            Middleware(StatsMiddleware),
            Middleware(
                AuthMiddleware,
                auth_token=auth_token,
                auth_required=auth_required,
                network_access=(host == "0.0.0.0"),
            ),
        ],
        lifespan=lifespan,
    )

    return app
