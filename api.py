"""
Public API for bMCP addon.

Provides lazy-loading wrappers for tools, resources, and server control.
External addons can use: `from bmcp import tool, resource, start_server`
"""

from importlib import import_module


def tool(*args, **kwargs):
    """
    Decorator to register an MCP tool.

    Tool name and description are automatically extracted from the function.

    Example:
        from bmcp import tool

        @tool
        async def my_tool(arg: str) -> str:
            '''My tool description.'''
            return f"Result: {arg}"
    """
    return import_module(f"{__package__}.mcp.tools._internal.registry").tool(
        *args, **kwargs
    )


def resource(*args, **kwargs):
    """
    Decorator to register an MCP resource.

    URI, name, and description are automatically generated from the function.
    The URI will be "blender://{function_name}".

    Example:
        from bmcp import resource

        @resource
        def my_resource() -> str:
            '''Resource description.'''
            return "Resource content"
    """
    return import_module(f"{__package__}.mcp.resources._internal.registry").resource(
        *args, **kwargs
    )


def prompt(*args, **kwargs):
    """
    Decorator to register an MCP prompt.

    Name, description, and arguments are automatically extracted from the function.
    Prompts return a list of messages for LLM interaction.

    Example:
        from bmcp import prompt

        @prompt
        def my_prompt(focus: str = "all") -> list[dict]:
            '''Prompt description.

            Args:
                focus: Area to focus on
            '''
            return [{"role": "user", "content": {"type": "text", "text": "..."}}]
    """
    return import_module(f"{__package__}.mcp.prompts._internal.registry").prompt(
        *args, **kwargs
    )


def iter_tools():
    """Return all registered tools."""
    return import_module(f"{__package__}.mcp.tools._internal.registry").iter_tools()


def iter_resources():
    """Return all registered resources."""
    return import_module(
        f"{__package__}.mcp.resources._internal.registry"
    ).iter_resources()


def iter_prompts():
    """Return all registered prompts."""
    return import_module(f"{__package__}.mcp.prompts._internal.registry").iter_prompts()


def start_server():
    """Start the MCP server."""
    return import_module(f"{__package__}.mcp").start_server()


def stop_server():
    """Stop the MCP server."""
    return import_module(f"{__package__}.mcp").stop_server()


def is_running():
    """Check if MCP server is running."""
    return import_module(f"{__package__}.mcp").is_running()


def is_shutting_down():
    """Check if MCP server is shutting down."""
    return import_module(f"{__package__}.mcp").is_shutting_down()


def wait_shutdown(timeout=None):
    """Wait for MCP server to shut down."""
    return import_module(f"{__package__}.mcp").wait_shutdown(timeout)


__all__ = [
    "tool",
    "resource",
    "prompt",
    "iter_tools",
    "iter_resources",
    "iter_prompts",
    "start_server",
    "stop_server",
    "is_running",
    "is_shutting_down",
    "wait_shutdown",
]
