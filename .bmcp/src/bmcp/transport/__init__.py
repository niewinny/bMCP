"""
MCP Transport Layer

Provides transport implementations for the Model Context Protocol:
- HTTP/SSE transport for direct clients (Claude Code, Cursor, LM Studio)
- stdio bridge for CLI clients (Claude Desktop)

Architecture:
    http_server.py: ServerManager + uvicorn lifecycle management
    asgi.py:        Starlette ASGI application with SSE and HTTP endpoints
    stdio.py:       Standalone stdio-to-HTTP bridge (no external dependencies)
"""
