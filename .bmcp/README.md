# bmcp

MCP server SDK. Distributed as a mega-wheel — no pip needed.

## Build

```bash
python3 -m venv /tmp/venv && /tmp/venv/bin/pip install hatchling
/tmp/venv/bin/python .bmcp/scripts/build_wheel.py
# -> wheels/bmcp-0.1.0-py3-none-any.whl
```

## Public API

```python
# Decorators
from bmcp import tool, resource, prompt

# Server control
from bmcp import start_mcp_server, stop_mcp_server, is_server_running

# Configuration
from bmcp.config import DEFAULT_SERVER_PORT, OUTPUT_SIZE_LIMIT
```

### All exports

```python
from bmcp import (
    # Decorators
    tool,              # @tool on async fn — registers MCP tool
    resource,          # @resource on sync fn -> str — registers MCP resource
    prompt,            # @prompt on sync fn -> list[dict] — registers MCP prompt

    # Server
    start_mcp_server,      # () -> bool — start HTTP/SSE server in background thread
    stop_mcp_server,       # () -> bool — graceful shutdown
    is_server_running,     # () -> bool
    is_server_shutting_down,  # () -> bool
    wait_for_shutdown,     # (timeout=3.0) -> bool

    # Core
    MCPServer,         # MCPServer(name) — protocol handler

    # Registries
    iter_tools,        # () -> list[ToolRegistration]
    iter_resources,    # () -> list[ResourceRegistration]
    iter_prompts,      # () -> list[PromptRegistration]
    clear_tools,       # () -> None
    clear_resources,   # () -> None
    clear_prompts,     # () -> None

    # Context
    get_context,       # () -> ToolContext
    set_context,       # (execute_fn, anyio_module) — set execution bridge

    # Logging
    get_logger,        # (name: str) -> Logger
    setup_logging,     # (level=WARNING)
)
```

## Decorators

```python
@tool
async def my_tool(ctx, code: str) -> str:
    """Docstring = tool description. ctx is auto-injected, excluded from schema."""
    result = await ctx.call_blender_operator("my_op", {"code": code})
    return result.get("output", "")

@resource
def my_resource() -> str:
    """Sync only. Returns str. URI auto-generated: blender://{fn_name}"""
    return "# markdown content"

@prompt
def my_prompt(focus: str = "all") -> list[dict]:
    """First paragraph = description. Args parsed from docstring.

    Args:
        focus: "all", "inputs", "outputs"
    """
    return [{"role": "user", "content": {"type": "text", "text": f"..."}}]
```

## ToolContext

Available as `ctx` first parameter in `@tool` functions:

- `ctx.is_http_mode` / `ctx.is_stdio_mode` — transport detection
- `await ctx.call_blender_operator(name, args)` — execute on Blender main thread

## ServerManager

Advanced usage with custom config (no bpy needed):

```python
from bmcp.transport.http_server import ServerManager

# config returns: (network_access, port, enable_logs, auth_token, auth_required)
manager = ServerManager(get_config_fn=lambda: (False, 12097, False, "token", True))
manager.start()
manager.stop()
```

## Config Constants

```python
from bmcp.config import (
    DEFAULT_SERVER_PORT,            # 12097
    DEFAULT_AUTH_TOKEN_LENGTH,      # 32
    TOOL_EXECUTION_TIMEOUT,         # 300s
    RESOURCE_EXECUTION_TIMEOUT,     # 300s
    MAX_PENDING_OPERATIONS,         # 50
    SSE_QUEUE_SIZE,                 # 500
    OUTPUT_SIZE_LIMIT,              # 2MB
)
```

## Transports

| Endpoint | Protocol | Clients |
|---|---|---|
| `/sse` | Server-Sent Events | Claude Code, Cursor |
| `/http` | JSON-RPC POST | LM Studio |
| stdio | stdin/stdout bridge | Claude Desktop |

Stdio bridge: `python -m bmcp.transport.stdio [--port 12097] [--host 127.0.0.1] [--debug]`

## MCP Methods

`initialize`, `tools/list`, `tools/call`, `resources/list`, `resources/read`, `prompts/list`, `prompts/get`

Protocol versions: `2024-11-05`, `2025-06-18`

## License

GPL-3.0-or-later
