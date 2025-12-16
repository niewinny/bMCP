"""
MCP Transport Layer

This module provides transport implementations for the Model Context Protocol:
- HTTP/SSE transport for direct clients (Claude Code, Cursor, LM Studio)
- stdio bridge for CLI clients (Claude Desktop)

Architecture:
    http_server.py: ServerManager + uvicorn lifecycle management
    asgi.py:        Starlette ASGI application with SSE and HTTP endpoints
    stdio.py:       Standalone stdio-to-HTTP bridge (no external dependencies)
"""

from . import http_server
from .asgi import create_asgi_app

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

# Re-export commonly used functions for convenience
ServerManager = http_server.ServerManager
execute_on_main_thread = http_server.execute_on_main_thread
start_mcp_server = http_server.start_mcp_server
stop_mcp_server = http_server.stop_mcp_server
is_server_running = http_server.is_server_running
is_server_shutting_down = http_server.is_server_shutting_down
wait_for_shutdown = http_server.wait_for_shutdown
