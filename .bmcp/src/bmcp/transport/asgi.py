"""
ASGI Application — MCP Transport (Streamable HTTP + Legacy SSE)

Endpoints:
- /mcp          — Streamable HTTP (MCP 2025-11-25): POST + DELETE only
- /sse          — Legacy SSE transport (backward compat for older clients)
- /messages     — Legacy POST endpoint (paired with /sse)
- /health       — Health check (no auth)
- /debug        — Debug stats (requires auth)

Session Management:
- Sessions are created on initialize and tracked as {id: timestamp}
- Stale sessions are cleaned up periodically
- Clients must send Mcp-Session-Id header after initialization

Execution Queue:
- All requests (tools/resources) execute on Blender's main thread via timers
- Blender processes timers sequentially — natural serialization
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
from contextlib import asynccontextmanager
from typing import Callable, Optional

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from ..core import MCPServer
from ..handlers import dispatch_request
from ..logger import clear_request_id, get_logger, set_request_id
from ..config import PROTOCOL_VERSION, PROTOCOL_VERSION_LEGACY, SESSION_TIMEOUT, SESSION_CLEANUP_INTERVAL

# Logger for request logging
request_logger = get_logger("bmcp-requests")
# Logger for authentication events
auth_logger = get_logger("bmcp-auth")

# Maximum request body size (10MB) to prevent DoS attacks
MAX_REQUEST_BODY_SIZE = 10 * 1024 * 1024


async def _session_cleanup_loop(
    sessions: dict, sessions_lock: threading.Lock
) -> None:
    """Periodic cleanup task for expired sessions."""
    while True:
        try:
            await asyncio.sleep(SESSION_CLEANUP_INTERVAL)
            now = time.time()
            with sessions_lock:
                expired = [
                    sid
                    for sid, created in sessions.items()
                    if now - created > SESSION_TIMEOUT
                ]
                for sid in expired:
                    del sessions[sid]
            if expired:
                request_logger.info("Cleaned up %d expired sessions", len(expired))
        except asyncio.CancelledError:
            break
        except Exception as e:
            request_logger.debug("Session cleanup error (non-fatal): %s", e)


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
    2. Query parameter: '?token=<token>' (fallback, localhost only)
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
    """Health check endpoint — no auth required for monitoring tools."""
    start_time = getattr(request.app.state, "start_time", time.time())

    return JSONResponse(
        {
            "status": "healthy",
            "uptime_seconds": round(time.time() - start_time, 2),
        }
    )


async def debug_endpoint(request: Request):
    """Debug endpoint with detailed server stats — requires auth."""
    mcp_server = request.app.state.mcp_server
    sessions = request.app.state.sessions
    start_time = getattr(request.app.state, "start_time", time.time())
    stats = getattr(request.app.state, "stats", {})

    return JSONResponse(
        {
            "status": "healthy",
            "uptime_seconds": round(time.time() - start_time, 2),
            "connections": {"active_sessions": len(sessions)},
            "statistics": {
                "total_requests": stats.get("request_count", 0),
                "error_count": stats.get("error_count", 0),
            },
            "server": {
                "name": mcp_server.name,
                "version": "1.0.0",
                "protocol_version": PROTOCOL_VERSION,
                "tools_count": mcp_server.tool_count,
                "resources_count": mcp_server.resource_count,
            },
        }
    )


async def mcp_endpoint(request: Request):
    """
    Streamable HTTP endpoint for MCP protocol 2025-11-25.

    Handles POST (main JSON-RPC handler) and DELETE (session termination).
    """
    mcp_server = request.app.state.mcp_server
    sessions = request.app.state.sessions
    sessions_lock = request.app.state.sessions_lock

    # --- DELETE: terminate session ---
    if request.method == "DELETE":
        session_id = request.headers.get("mcp-session-id")
        if not session_id:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32600,
                        "message": "Missing Mcp-Session-Id header",
                    },
                },
                status_code=400,
            )
        with sessions_lock:
            removed = sessions.pop(session_id, None)
        if removed is not None:
            request_logger.debug("Session terminated: %s", session_id[:8])
            return Response(status_code=200)
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32600, "message": "Unknown session"},
            },
            status_code=404,
        )

    # --- POST: main JSON-RPC handler ---
    try:
        body = await request.body()
        data = json.loads(body)
    except Exception as e:
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {e}"},
            },
            status_code=400,
        )

    # Reject batch requests (arrays)
    if isinstance(data, list):
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32600,
                    "message": "Batch requests are not supported",
                },
            },
            status_code=400,
        )

    method = data.get("method")
    params = data.get("params")
    msg_id = data.get("id")
    jsonrpc_version = data.get("jsonrpc", "2.0")
    is_notification = msg_id is None

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

    # --- Initialize: create session ---
    if method == "initialize":
        try:
            result = await dispatch_request(mcp_server, method, params)

            session_id = str(uuid.uuid4())
            with sessions_lock:
                sessions[session_id] = time.time()
            request_logger.debug("New session: %s", session_id[:8])
            return JSONResponse(
                {"jsonrpc": jsonrpc_version, "id": msg_id, "result": result},
                headers={"Mcp-Session-Id": session_id},
            )
        except Exception as e:
            return JSONResponse(
                {
                    "jsonrpc": jsonrpc_version,
                    "id": msg_id,
                    "error": {"code": -32603, "message": f"Internal error: {e}"},
                }
            )

    # --- All other methods: validate session ---
    # (Notifications have no id — never return error responses for them,
    #  per JSON-RPC spec. Accept them silently to avoid "id: null" responses
    #  that break strict Zod validators like Claude Desktop's.)
    session_id = request.headers.get("mcp-session-id")
    if not session_id:
        if is_notification:
            return Response(status_code=202)
        return JSONResponse(
            {
                "jsonrpc": jsonrpc_version,
                "id": msg_id,
                "error": {
                    "code": -32600,
                    "message": "Missing Mcp-Session-Id header. Call initialize first.",
                },
            },
            status_code=400,
        )

    with sessions_lock:
        valid_session = session_id in sessions
        if valid_session:
            sessions[session_id] = time.time()
    if not valid_session:
        if is_notification:
            return Response(status_code=202)
        return JSONResponse(
            {
                "jsonrpc": jsonrpc_version,
                "id": msg_id,
                "error": {
                    "code": -32600,
                    "message": "Invalid or expired session. Call initialize again.",
                },
            },
            status_code=404,
        )

    # Dispatch
    try:
        result = await dispatch_request(mcp_server, method, params)

        if is_notification:
            return Response(status_code=202)

        return JSONResponse(
            {"jsonrpc": jsonrpc_version, "id": msg_id, "result": result}
        )

    except ValueError as e:
        error_code = getattr(e, "code", -32602)
        if is_notification:
            return Response(status_code=202)
        return JSONResponse(
            {
                "jsonrpc": jsonrpc_version,
                "id": msg_id,
                "error": {"code": error_code, "message": str(e)},
            }
        )

    except Exception as e:
        if is_notification:
            return Response(status_code=202)
        return JSONResponse(
            {
                "jsonrpc": jsonrpc_version,
                "id": msg_id,
                "error": {"code": -32603, "message": f"Internal error: {e}"},
            }
        )


async def sse_endpoint(request: Request):
    """
    Legacy SSE endpoint for backward compatibility with pre-2025-11-25 MCP clients.

    Opens an SSE stream and sends an `endpoint` event telling the client
    where to POST JSON-RPC messages. Responses are pushed back through
    this SSE stream as `message` events.
    """
    sse_queues = request.app.state.sse_queues
    sse_queues_lock = request.app.state.sse_queues_lock

    session_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()

    with sse_queues_lock:
        sse_queues[session_id] = queue

    request_logger.debug("SSE connection opened: %s", session_id[:8])

    async def event_generator():
        try:
            # Tell the client where to POST messages
            yield f"event: endpoint\ndata: /messages?sessionId={session_id}\n\n"

            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"event: message\ndata: {json.dumps(message)}\n\n"
                except asyncio.TimeoutError:
                    # Keep-alive comment to prevent connection timeout
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            with sse_queues_lock:
                sse_queues.pop(session_id, None)
            sessions_lock = request.app.state.sessions_lock
            sessions = request.app.state.sessions
            with sessions_lock:
                sessions.pop(session_id, None)
            request_logger.debug("SSE connection closed: %s", session_id[:8])

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def messages_endpoint(request: Request):
    """
    Legacy messages endpoint for SSE transport.

    Receives JSON-RPC POSTs and pushes responses through the paired SSE stream.
    """
    mcp_server = request.app.state.mcp_server
    sessions = request.app.state.sessions
    sessions_lock = request.app.state.sessions_lock
    sse_queues = request.app.state.sse_queues
    sse_queues_lock = request.app.state.sse_queues_lock

    session_id = request.query_params.get("sessionId")
    if not session_id:
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32600,
                    "message": "Missing sessionId query parameter",
                },
            },
            status_code=400,
        )

    with sse_queues_lock:
        queue = sse_queues.get(session_id)

    if queue is None:
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32600,
                    "message": "Unknown or expired SSE session",
                },
            },
            status_code=404,
        )

    try:
        body = await request.body()
        data = json.loads(body)
    except Exception as e:
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {e}"},
            },
            status_code=400,
        )

    if isinstance(data, list):
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32600,
                    "message": "Batch requests are not supported",
                },
            },
            status_code=400,
        )

    method = data.get("method")
    params = data.get("params")
    msg_id = data.get("id")
    jsonrpc_version = data.get("jsonrpc", "2.0")
    is_notification = msg_id is None

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

    # Register session on initialize
    if method == "initialize":
        with sessions_lock:
            sessions[session_id] = time.time()

    try:
        result = await dispatch_request(mcp_server, method, params)

        # SSE transport is always legacy — force protocol version regardless
        # of what the client requests (e.g. LM Studio sends 2025-11-25 but
        # its SSE client only supports 2024-11-05)
        if method == "initialize" and isinstance(result, dict):
            result["protocolVersion"] = PROTOCOL_VERSION_LEGACY

        if not is_notification:
            response = {"jsonrpc": jsonrpc_version, "id": msg_id, "result": result}
            await queue.put(response)

        return Response(status_code=202)

    except ValueError as e:
        error_code = getattr(e, "code", -32602)
        if not is_notification:
            response = {
                "jsonrpc": jsonrpc_version,
                "id": msg_id,
                "error": {"code": error_code, "message": str(e)},
            }
            await queue.put(response)
        return Response(status_code=202)

    except Exception as e:
        if not is_notification:
            response = {
                "jsonrpc": jsonrpc_version,
                "id": msg_id,
                "error": {"code": -32603, "message": f"Internal error: {e}"},
            }
            await queue.put(response)
        return Response(status_code=202)


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
        app.state.sessions_lock = threading.Lock()
        app.state.sessions = {}
        app.state.sse_queues_lock = threading.Lock()
        app.state.sse_queues = {}
        app.state.start_time = time.time()
        app.state.stats = {"request_count": 0, "error_count": 0}
        app.state.mcp_server = mcp_server
        app.state.is_shutting_down = is_shutting_down_fn or (lambda: False)

        # Start session cleanup task
        cleanup_task = asyncio.create_task(
            _session_cleanup_loop(app.state.sessions, app.state.sessions_lock)
        )
        request_logger.debug("Started session cleanup task")

        yield

        # Shutdown
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass

    app = Starlette(
        routes=[
            Route("/health", health_endpoint, methods=["GET"]),
            Route("/debug", debug_endpoint, methods=["GET"]),
            Route("/mcp", mcp_endpoint, methods=["POST", "DELETE"]),
            # Legacy SSE transport (backward compat for older MCP clients)
            Route("/sse", sse_endpoint, methods=["GET"]),
            Route("/messages", messages_endpoint, methods=["POST"]),
        ],
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=allowed_origins,
                allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
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
