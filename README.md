# bMCP - Blender MCP Server

Control Blender through AI using the Model Context Protocol (MCP).

## Features

- Execute Python code directly in Blender
- Query scene state and object properties
- Access real-time context (selected objects, active nodes, etc.)
- Use built-in prompts for common workflows (e.g., explain geometry nodes)
- Automate 3D workflows with AI assistance
- **No Python installation required** for stdio (uses Blender's built-in Python)

## Setup

1. Install the bMCP extension in Blender (4.2+)
2. Open **Blender Preferences → Add-ons → bMCP**
3. Choose your transport tab and click **"Copy Configuration"**
4. Paste into your client's MCP config file
5. Start the server: **Blender → MCP menu → Start Server**

## Transport Options

### Streamable HTTP (Recommended)

Single endpoint using the MCP `2025-11-25` protocol. Works with most modern MCP clients.

```json
{
  "mcpServers": {
    "blender": {
      "url": "http://localhost:12097/mcp"
    }
  }
}
```

**Use with:** Claude Code, Cursor, Windsurf

### SSE (Legacy)

For older MCP clients that only support Server-Sent Events.

```json
{
  "mcpServers": {
    "blender": {
      "url": "http://localhost:12097/sse"
    }
  }
}
```

**Use with:** LM Studio, legacy MCP clients

### Stdio

Bridges stdin/stdout clients to the HTTP server using Blender's bundled Python.

```json
{
  "mcpServers": {
    "blender": {
      "command": "/path/to/blender/python",
      "args": ["-m", "bmcp.transport.stdio", "--port", "12097"],
      "env": {
        "PYTHONPATH": "/path/to/bmcp/wheels/bmcp-1.0.0-py3-none-any.whl"
      }
    }
  }
}
```

The exact paths are filled in automatically when you use **Copy Configuration** in the addon preferences.

**Use with:** Claude Desktop

## Security

- **Localhost only** by default — only `127.0.0.1` connections accepted
- Optional **authentication token** (Bearer header) for all connections
- **Network access** can be enabled in preferences, which forces auth on and binds to `0.0.0.0`

## License

GPL-3.0
