"""
MCP Transport Layer

Provides transport implementations for the Model Context Protocol:
- Streamable HTTP transport (/mcp) for direct clients (Claude Code, Cursor, LM Studio)
- stdio bridge for CLI clients (Claude Desktop)

Architecture:
    http_server.py: ServerManager + uvicorn lifecycle management
    asgi.py:        Starlette ASGI application with Streamable HTTP endpoint
    stdio.py:       Standalone stdio-to-HTTP bridge (no external dependencies)
"""
