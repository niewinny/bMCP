"""
MCP Tools - Dynamic tool discovery system
"""

from typing import Any, Callable

from ..logger import get_logger
from . import blender_run_code  # noqa: F401
from ._internal.context import ToolContext, set_context
from ._internal.registry import iter_tools

# Get logger
logger = get_logger("bmcp-tools")


def register_tools(execute_fn: Callable[[str, dict], Any], anyio_module):
    """
    Initialize tools system - sets execution context for tools to use.

    No need to register with MCPServer - tools are discovered dynamically!

    Args:
        execute_fn: Function to execute tools on Blender's main thread
        anyio_module: anyio module for async/sync bridging (None for stdio)
    """
    logger.info("Initializing tools system...")

    # Set global context for tools to access
    set_context(execute_fn, anyio_module)
    mode = "HTTP" if anyio_module else "stdio"
    logger.debug("Set context: mode=%s", mode)

    # Count registered tools
    tool_count = len(list(iter_tools()))
    logger.info("Tools system ready - %d tool(s) available", tool_count)


# Public API
__all__ = [
    "ToolContext",  # Type hint for ctx parameter
    "register_tools",  # Register all tools
    "iter_tools",  # Iterate over registered tools
]
