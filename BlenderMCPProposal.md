# bMCP: Let the Blender Speak AI

## Why Build This
Artists, TDs, and scripters burn time on repetitive Blender chores: naming cleanups, modifier audits, small procedural tweaks.
```
    (╯°□°)╯︵ ┻━┻   <- after the 100th obj renaming
```
AI assistants(LLMs) can already write the `bpy` code to solve these instantly, but they lack safe, structured access to blender scene context and data. I propose building **Blender MCP**, a Blender extension that exposes Blender through the Model Context Protocol so assistants can read context and run code safely.

## Who Benefits

**Artists**: Skip manual naming cleanup, batch operations, and repetitive node setups. Ask Blender "rename all objects with 'Cube' to 'Building'" and it's done all with plain language.
**Coders**: Build custom tools using MCP protocol (stdio/HTTP/SSE) without forking bMCP—register new tools with a simple `@tool()` decorator.

## What Will Be Done
We're building an MCP (Model Context Protocol) server that lets AI assistants interact with Blender through natural language. Instead of exposing hundreds of specific tools, we're taking the modern approach: provide one powerful execution tool where the AI writes the actual code, and server safely orchestrates it. MCP that exposes moder MCP schema tools, resources and promts.  This is perfect for Blender's API. LLM already knows bpy from training data, so why wrap every operator individually? The focus is on building rock-solid core components (execution safety, resource readers, multi-transport support) without dragging in 30MB of dependencies. Artists get to say "prefix all my selected models with LEFT_" in plain English, and the AI handles the scripting. No macros to write, no repeted task, just conversation that gets work done.

PLan is also to expose API too our MCP server. The idea is to provide the base layer other coders can benefit from as well. If someone have addon and would love to introduce and AI tool for it. he do not need to ship full http server with it. Idea is he can just write the tool or resource(description how to write code to use addon) and it will be added to server we expose. Plain and simple.

Main Points are:
- **Server + transports**: stdio, HTTP, and SSE endpoints; HTTP/SSE follow MCP JSON-RPC (`tools/list`, `resources/list`, `tools/call`) so any MCP client can discover and call the It.
- **API exposure**: predictable surface to expose tools and resources, including hooks to add more tools/resources later without core changes, also via other addons and scripts.

## What That project is not about
This project is not about AI Agents nor AI models. 
It is not about training models to write better bpy code or undestands blender better nor RAG or prompt injection mechanizms, that may be a future scope.
It will not include any executables for agents nor expand blender with chat system, that may be usefull but should be scope of another project.
3D model generation or any generation at all, it may be usefull and scope of other projects but it is not what MCP is about

## How It Works (in practice)
1. User enables Addon
2. User starts MCP
3. MCP server exposes /sse and /http so any agent can call those for POST, GET
4. User adds MCP path to his agent of choice like LMStudio, Ollama, Claude
5. Ask Agent to do stuff in blender
6. Agent pull the available tools and decides what to use
7. Agent generates python code and sent it via POST to execute in blender
8. Blender executes code and returns resposne( Errors, Prints agents asked for)
9. Agent recives response and finishes his response to user


**Single tool Call example**
agent calls`blender_run_code` tool on /sse

Request:
```json
{
  "method": "tools/call",
  "params": {
    "name": "blender_run_code",
    "arguments": {
      "code": "import bpy\n\n# Add a cube to the scene\nbpy.ops.mesh.primitive_cube_add(location=(0, 0, 0))\n\n# Get the newly created cube\ncube = bpy.context.active_object\nprint(f\"Added cube: {cube.name}\")\nprint(f\"Location: {cube.location}\")"
    }
  }
}
```
Response:
```
Added cube: Cube
Location: <Vector (0.0000, 0.0000, 0.0000)>
```

## Tool Execution Flow

```
┌─────────┐    ┌────────────┐    ┌──────────────┐    ┌─────────────┐
│  Client │───→│ HTTP/SSE   │───→│  handlers.py │───→│ MCPServer   │
└─────────┘    │ Endpoint   │    │  dispatch()  │    │ call_tool() │
               └────────────┘    └──────────────┘    └──────┬──────┘
                                                            │
                                                            ↓
┌──────────────────────────────────────────────────────────────────┐
│                    execute_on_main_thread()                       │
│  1. Generate UUID job_id                                          │
│  2. Create threading.Event()                                      │
│  3. Register ResultQueue entry                                    │
│  4. Schedule timer: bpy.app.timers.register(run_on_main_thread)  │
│  5. Wait on Event (5 min timeout)                                 │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│                    MAIN THREAD (Timer fires)                      │
│  1. Check if job cancelled (timeout)                              │
│  2. Execute: bpy.ops.bmcp.run_code(code=..., job_id=...)         │
│  3. Operator: ast.parse → compile → exec                          │
│  4. Capture stdout to buffer                                      │
│  5. Store result: window_manager["mcp_result_{job_id}"]          │
│  6. Signal completion: event.set()                                │
└──────────────────────────────────────────────────────────────────┘
                              │
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│                    BACKGROUND THREAD (Resumes)                    │
│  1. Read result from window_manager                               │
│  2. Parse JSON result                                             │
│  3. Clean up properties immediately                               │
│  4. Return MCP response to client                                 │
└──────────────────────────────────────────────────────────────────┘
```


**Adding your own tool (tiny script)**
Paste this into Blender's Text Editor and run it:

```python
from bmcp import tool

@tool
async def hello_blender() -> str:
    """
    This tool Says Hello Blender
    """
    return "Hello Blender"
```

That's it! agents now see new tool and can use it.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                       BLENDER PROCESS                            │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                  MAIN THREAD (Blender)                     │ │
│  │                                                            │ │
│  │   bpy.app.timers ──→ Operators ──→ WindowManager Props    │ │
│  │         ↑                              ↓                   │ │
│  └─────────┼──────────────────────────────┼───────────────────┘ │
│            │ Timer Registration           │ Property Read       │
│  ┌─────────┼──────────────────────────────┼───────────────────┐ │
│  │         │    BACKGROUND THREAD         │                   │ │
│  │         │    (Asyncio Event Loop)      │                   │ │
│  │         │                              ↓                   │ │
│  │  ┌──────────────────────────────────────────────────────┐ │ │
│  │  │                 ServerManager                         │ │ │
│  │  │                      ↓                                │ │ │
│  │  │  Uvicorn ──→ ASGI App (Starlette)                    │ │ │
│  │  │                      ↓                                │ │ │
│  │  │              Middleware Stack                         │ │ │
│  │  │     (CORS → Auth → Shutdown → Stats → Logging)       │ │ │
│  │  │                      ↓                                │ │ │
│  │  │              Routes: /health /sse /http               │ │ │
│  │  │                      ↓                                │ │ │
│  │  │           handlers.py (JSON-RPC)                      │ │ │
│  │  │                      ↓                                │ │ │
│  │  │           MCPServer (core.py)                         │ │ │
│  │  │                      ↓                                │ │ │
│  │  │      Decorator Registries (@tool @resource @prompt)   │ │ │
│  │  └──────────────────────────────────────────────────────┘ │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              ↑
                              │ HTTP/SSE
          ┌───────────────────┴───────────────────┐
          │                                       │
    ┌───────────┐                         ┌──────────────┐
    │MCP Clients│                         │ stdio Bridge │
    │ (Direct)  │←─────── stdio ──────────│  stdio.py    │
    │           │                         └──────────────┘
    │- Claude   │
    │- LM Studio│
    │- VS Code  │
    └───────────┘
```

### Add-on Architecture (brief) and Implementation Details
- **Core MCP brain**: async JSON-RPC loop with decorator registries (`@tool`, `@resource`, `@promt`); one canonical default tool (`blender_run_code`) plus caches for tools/resources so everything stays in sync.
- **Transports**: HTTP/SSE endpoints and stdio script to connect to it. HTTP/SSE speak MCP (`tools/list`, `resources/list`, `tools/call`) and run on uvicorn/ASGI. Registration hooks let you add new tools/resources without touching the core.
- **Execution pipeline**: `bpy.app.timers` schedules on main thread → stdout capture → MCP response. Background thread coordinates via `threading.Event()` with 5-minute timeout (configurable). Queue management with max 50 concurrent operations (oldest cancelled when full). Security via auth tokens + localhost-only binding (no AST sandboxing - full bpy access).

### Bundled Dependencies
Minimal dependencies bundled in `wheels/` — no pip installs at runtime:

- `uvicorn` (0.38.0) - ASGI server
- `starlette` (0.50.0) - ASGI web framework
- `sse_starlette` (3.0.3) - Server-Sent Events support
- `anyio` (4.11.0) - Async I/O abstraction layer
- `h11` (0.16.0) - HTTP/1.1 protocol implementation
- `websockets` (15.0.1) - WebSocket protocol (platform-specific: Windows, macOS ARM/Universal, Linux)
- `sniffio` (1.3.1) - Async library detection
- `click` (8.3.0) - CLI parsing (uvicorn dependency)

**Total bundle**: ~1MB (8 wheels). Custom MCP implementation (no external MCP SDK) keeps dependencies minimal.

### Technical Approach
- **Thread-safe execution**: Async server coordinates with Blender's main thread via `bpy.app.timers` and `threading.Event()`; results cached in window_manager and returned via MCP with stdout/error.
- **Transport abstraction**: One core, many faces. stdio/HTTP/SSE adapters reuse the same handlers and schemas.
- **Property cleanup**: Window manager properties are cleaned up immediately after use. Stale properties from crashed operations are cleaned on server start.

### Server Infrastructure
- **ASGI** = Asynchronous Server Gateway Interface (next-gen Python server spec supporting async, websockets, SSE). We use Starlette so HTTP and SSE endpoints run on one app.
- **Uvicorn** = Fast ASGI server with hot reload-free setup—perfect for running in a Blender background thread. It serves the MCP API and streams SSE responses.
- **Custom MCP implementation**: Built from scratch (no external MCP SDK dependency) for minimal footprint and full control.

## Blender 4.2+ Extension Compliance
Made as extension, and following all best practicies.

## Why This Extension Is Different From other MCP addosn
- **Core stuff written no need for 30mb dependencies**
- **Modern Aprouch to MCP servers. Small amount of tools, support for resources and propmts**
- **Support for all protocols in one place, no matter waht agent you use it will connect** 
