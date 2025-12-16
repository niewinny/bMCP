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

1. Install the bMCP extension in Blender
2. Open **Blender Preferences → Add-ons → bMCP**
3. Choose your configuration:
   - **Stdio**
   - **HTTP**
4. Click **"Copy Configuration"**
5. Add to your client's config file (see client documentation)
6. Restart your client
7. Start the server: **Blender → bMCP menu → Start Server**

## Transport Options

The addon supports three transport types. Choose based on your MCP client:

### 1. Stdio (Claude Desktop)

For CLI-based MCP clients that use stdin/stdout.

```json
{
  "mcpServers": {
    "blender": {
      "command": "/path/to/blender/python",
      "args": ["/path/to/stdio.py"]
    }
  }
}
```

**Use with:** Claude Desktop

### 2. HTTP (LM Studio)

For clients that use simple HTTP request-response (synchronous JSON-RPC).

```json
{
  "mcpServers": {
    "blender": {
      "url": "http://localhost:12097/http"
    }
  }
}
```

**Use with:** LM Studio, simple HTTP clients

### 3. SSE (Claude Code, Cursor)

For clients that support Server-Sent Events (streaming responses).

```json
{
  "mcpServers": {
    "blender": {
      "url": "http://localhost:12097/sse"
    }
  }
}
```

**Use with:** Claude Code, Cursor, any SSE-capable client

## License

GPL-3.0
