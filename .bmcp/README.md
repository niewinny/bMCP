# bmcp — API Reference

> Python SDK for building MCP servers. Version `0.1.0`

---

# Module Index

- [bmcp](#bmcp-1) — decorators + registry
- [bmcp.server](#bmcpserver) — server lifecycle, config, transport

---

# bmcp

```python
import bmcp
```

## Decorators

**bmcp.tool**(*func*) -> *func*

&ensp; Register an async function as an MCP tool.
&ensp; Name derived from function name. Description from docstring.
&ensp; `ctx` first param is auto-injected and hidden from schema.

```python
@bmcp.tool
async def run_code(ctx, code: str) -> str:
    """Execute code in Blender."""
    return (await ctx.call_blender_operator("run_code", {"code": code})).get("output", "")
```

**bmcp.resource**(*func*) -> *func*

&ensp; Register a sync function as an MCP resource.
&ensp; URI auto-generated as `blender://{function_name}`.
&ensp; Must take no parameters and return `str`.

```python
@bmcp.resource
def scene_info() -> str:
    """Active scene summary."""
    return "..."
```

**bmcp.prompt**(*func*) -> *func*

&ensp; Register a sync function as an MCP prompt.
&ensp; Title from function name. Arguments parsed from docstring `Args:` block.
&ensp; Must return `list[dict]`.

```python
@bmcp.prompt
def explain(focus: str = "all") -> list[dict]:
    """Explain geometry nodes.

    Args:
        focus: "all", "inputs", "outputs"
    """
    return [{"role": "user", "content": {"type": "text", "text": "..."}}]
```

## Registry

**bmcp.iter_tools**() -> *list[ToolRegistration]*

&ensp; Snapshot of all registered tools.

**bmcp.iter_resources**() -> *list[ResourceRegistration]*

&ensp; Snapshot of all registered resources.

**bmcp.iter_prompts**() -> *list[PromptRegistration]*

&ensp; Snapshot of all registered prompts.

**bmcp.clear_tools**() -> *None*

&ensp; Remove all registered tools.

**bmcp.clear_resources**() -> *None*

&ensp; Remove all registered resources.

**bmcp.clear_prompts**() -> *None*

&ensp; Remove all registered prompts.

## Context

**bmcp.get_context**() -> *ToolContext*

&ensp; Get the shared tool execution context. Thread-safe.

**bmcp.set_context**(*execute_fn, anyio_module*) -> *None*

&ensp; Set execution bridge. Called once at server startup.

## Logging

**bmcp.get_logger**(*name*) -> *logging.Logger*

&ensp; Get a named logger instance.

**bmcp.setup_logging**(*level=logging.WARNING*) -> *None*

&ensp; Configure logging level for all bmcp loggers.

---

# bmcp.server

```python
from bmcp.server import start, stop, is_running, DEFAULT_PORT
```

## Lifecycle

**start**() -> *bool*

&ensp; Start HTTP/SSE server in a background thread.

**stop**() -> *bool*

&ensp; Graceful shutdown.

**is_running**() -> *bool*

&ensp; Whether the server is currently running.

**is_shutting_down**() -> *bool*

&ensp; Whether the server is in the process of shutting down.

**wait**(*timeout=3.0*) -> *bool*

&ensp; Block until shutdown completes or timeout expires.

## Constants

**DEFAULT_PORT** : *int* = `12097`

**DEFAULT_AUTH_TOKEN_LENGTH** : *int* = `32`

**TOOL_TIMEOUT** : *float | None* = `300.0`

&ensp; Seconds. `None` disables timeout.

**RESOURCE_TIMEOUT** : *float | None* = `300.0`

**STARTUP_TIMEOUT** : *float* = `5.0`

**SHUTDOWN_TIMEOUT** : *float* = `1.5`

**MAX_PENDING_OPS** : *int* = `50`

**SSE_QUEUE_SIZE** : *int* = `500`

**OUTPUT_LIMIT** : *int* = `2097152`

&ensp; 2 MB.

## Validation

**validate_port**(*port, host, use_cache=True*) -> *(bool, str | None)*

&ensp; Check port range (1024–65535) and availability. Returns `(is_valid, error_message)`.

**validate_config**(*port, network_access, auth_required, auth_token*) -> *ConfigValidationResult*

&ensp; Validate complete server configuration.

**clear_port_validation_cache**() -> *None*

&ensp; Reset cached port checks. Call after stopping the server.

## Classes

### *class* ServerManager(*get_config_fn=None*)

&ensp; Server lifecycle manager. `get_config_fn` returns a tuple:

```python
(network_access: bool, port: int, enable_logs: bool, auth_token: str, auth_required: bool)
```

```python
from bmcp.server import ServerManager

manager = ServerManager(get_config_fn=lambda: (False, 12097, False, "token", True))
manager.start()
```

**start**() -> *bool*

&ensp; Start server in background thread.

**stop**() -> *bool*

&ensp; Graceful shutdown.

**is_running**() -> *bool*

**is_shutting_down**() -> *bool*

**wait_for_shutdown**(*timeout=3.0*) -> *bool*

**execute_on_main_thread**(*tool_name, arguments*) -> *dict*

&ensp; Run a tool on Blender's main thread.

### *class* MCPServer(*name*)

&ensp; MCP protocol handler with cached registries.

**sync_tools**() -> *None*

&ensp; Rebuild tool cache from decorator registry.

**sync_resources**() -> *None*

&ensp; Rebuild resource cache from decorator registry.

**sync_prompts**() -> *None*

&ensp; Rebuild prompt cache from decorator registry.

**clear**() -> *None*

&ensp; Clear all caches.

**list_tools**() -> *list[dict]*

&ensp; All tools in MCP wire format.

**list_resources**() -> *list[dict]*

&ensp; All resources in MCP wire format.

**list_prompts**() -> *list[dict]*

&ensp; All prompts in MCP wire format.

**call_tool**(*name, arguments*) -> *Any*

&ensp; `async` — Execute a tool by name. Auto-injects `ctx`.

**read_resource**(*uri*) -> *str*

&ensp; `async` — Read a resource by URI.

**get_prompt**(*name, arguments*) -> *dict*

&ensp; Execute prompt handler. Returns `{"description": ..., "messages": [...]}`.

---

# Data Types

## *class* ToolContext

&ensp; Execution context available as `ctx` in `@tool` functions.

**is_http_mode** : *bool, read-only*

&ensp; `True` when running via HTTP/SSE transport.

**is_stdio_mode** : *bool, read-only*

&ensp; `True` when running via stdio transport.

**call_blender_operator**(*tool_name, arguments*) -> *dict*

&ensp; `async` — Execute an operation on Blender's main thread.

## *class* ToolRegistration

**handler** : *FunctionType*

**name** : *str | None*

**description** : *str | None*

## *class* ResourceRegistration

**uri** : *str*

**handler** : *FunctionType*

**name** : *str | None*

**description** : *str | None*

## *class* PromptRegistration

**name** : *str*

**handler** : *FunctionType*

**title** : *str | None*

**description** : *str | None*

**arguments** : *list[PromptArgument]*

## *class* PromptArgument

**name** : *str*

**description** : *str, default ""*

**required** : *bool, default True*

## *class* ConfigValidationResult

**valid** : *bool*

**errors** : *list[str]*

**warnings** : *list[str]*

&ensp; Supports `bool()` — `if result:` checks `valid`.

---

# Transport

## bmcp.transport.stdio

&ensp; Stdio-to-HTTP bridge for Claude Desktop.

```bash
python -m bmcp.transport.stdio --port 12097 --host 127.0.0.1 --debug
```

## Endpoints

| Path | Protocol | Clients |
|---|---|---|
| `/sse` | Server-Sent Events | Claude Code, Cursor |
| `/http` | JSON-RPC POST | LM Studio |
| stdio | stdin/stdout | Claude Desktop |

## MCP Protocol

**Methods:** `initialize` `tools/list` `tools/call` `resources/list` `resources/read` `prompts/list` `prompts/get`

**Versions:** `2024-11-05` `2025-06-18`

---

*License: GPL-3.0-or-later*
