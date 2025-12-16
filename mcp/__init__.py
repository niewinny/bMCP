"""
MCP (Model Context Protocol) Implementation for Blender

This module provides a complete MCP server implementation using the base
MCP SDK with custom decorators. It supports:
- HTTP/SSE transport for web-based MCP clients (transport/http_server.py, transport/asgi.py)
- stdio transport bridge for Claude Desktop (transport/stdio.py)
- Tools (blender_run_code) - defined in tools.py
- Resources (scene, objects, nodes) - auto-discovered from resources/scripts/
- Custom MCPServer class - defined in core.py

Architecture:
    core.py:                   Custom MCPServer implementation
    transport/http_server.py:  ServerManager + uvicorn lifecycle
    transport/asgi.py:         Starlette ASGI application
    transport/stdio.py:        Standalone stdio bridge
"""

from . import transport, utils
from .logger import get_logger, setup_logging

__all__ = [
    # Utilities for submodules
    "get_logger",
    "setup_logging",
    "utils",
    # Public API
    "start_server",
    "stop_server",
    "is_running",
    "is_shutting_down",
    "wait_shutdown",
]

# Public API for external use
start_server = transport.start_mcp_server
stop_server = transport.stop_mcp_server
is_running = transport.is_server_running
is_shutting_down = transport.is_server_shutting_down
wait_shutdown = transport.wait_for_shutdown
