"""
MCP Transport Layer

This module provides transport implementations for the Model Context Protocol:
- HTTP/SSE transport for direct clients (Claude Code, Cursor, LM Studio)
- stdio bridge for CLI clients (Claude Desktop)

Architecture:
    http_server.py: ServerManager + uvicorn lifecycle management
    asgi.py:        Starlette ASGI application with SSE and HTTP endpoints
    stdio.py:       Standalone stdio-to-HTTP bridge (no external dependencies)

Note: http_server is lazily imported to avoid triggering bpy import at module level.
"""

# Lazy imports to avoid triggering bpy import at module level.
# http_server.py uses conditional bpy import - this prevents import errors
# when the library is used standalone (without Blender).
# Uses importlib.import_module instead of 'from . import' to avoid
# infinite recursion via _handle_fromlist on Python 3.13+.

import importlib

_lazy_modules = {}


def __getattr__(name):
    if name == "http_server":
        if "http_server" not in _lazy_modules:
            _lazy_modules["http_server"] = importlib.import_module(
                ".http_server", __name__
            )
        return _lazy_modules["http_server"]

    if name in (
        "ServerManager",
        "execute_on_main_thread",
        "start_mcp_server",
        "stop_mcp_server",
        "is_server_running",
        "is_server_shutting_down",
        "wait_for_shutdown",
    ):
        http_server = __getattr__("http_server")
        return getattr(http_server, name)

    if name == "create_asgi_app":
        from .asgi import create_asgi_app
        return create_asgi_app

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # HTTP Server module
    "http_server",
    # Server Manager
    "ServerManager",
    "execute_on_main_thread",
    "start_mcp_server",
    "stop_mcp_server",
    "is_server_running",
    "is_server_shutting_down",
    "wait_for_shutdown",
    # ASGI App
    "create_asgi_app",
]
