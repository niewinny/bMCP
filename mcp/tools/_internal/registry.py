"""
Tools Registry - Decorator and storage for MCP tools.

Provides @tool decorator and registry for tool discovery.
"""

from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Set

# Import directly from submodules to avoid circular import through mcp/__init__.py
from ...logger import get_logger
from ...utils import validators as utils

logger = get_logger("bmcp-tools-registry")


@dataclass
class ToolRegistration:
    """Tool registration entry."""

    handler: Callable[..., Any]
    name: Optional[str] = None
    description: Optional[str] = None


# Internal registry populated by @tool decorator
_tool_registry: List[ToolRegistration] = []
# Track registered tool names to detect duplicates
_registered_tool_names: Set[str] = set()


def tool(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator to register an async MCP tool.

    The decorated function can optionally accept a 'ctx' parameter as its first
    argument. If present, a ToolContext will be automatically injected at runtime.
    The 'ctx' parameter will NOT appear in the tool's JSON schema - it's purely
    for dependency injection.

    The tool name is automatically derived from the function name, and the
    description is extracted from the function's docstring.

    Args:
        func: The async function to register as a tool

    Returns:
        The same function (unmodified)

    Raises:
        ValueError: If a tool with the same name is already registered

    Example without context:
        @tool
        async def get_version() -> str:
            '''Get the current Blender version.'''
            import bpy
            return bpy.app.version_string

    Example with context (using operator bridge):
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            from mcp.tools._internal.context import ToolContext

        @tool
        async def blender_run_code(ctx: "ToolContext", code: str) -> str:
            '''Execute Python code in Blender's context.'''
            result = await ctx.call_blender_operator("blender_run_code", {"code": code})
            return result.get("output", "")
    """
    # Validate function (returns True/False)
    is_valid = (
        utils.validate_callable(func, "tool", logger)
        and utils.validate_has_name(func, "tool", logger)
        and utils.check_docstring(func, logger)
        and utils.check_return_type(func, str, strict=False, logger=logger)
    )

    # Only register if all validations passed
    if is_valid:
        tool_name = func.__name__

        # Check for duplicate tool names
        if tool_name in _registered_tool_names:
            logger.error(
                "Tool name '%s' is already registered. "
                "Each tool must have a unique name. "
                "The duplicate registration will be ignored.",
                tool_name,
            )
            # Return the function without registering to allow graceful degradation
            return func

        _tool_registry.append(ToolRegistration(handler=func))
        _registered_tool_names.add(tool_name)
        logger.debug("Registered tool: %s", tool_name)

    return func


def iter_tools() -> List[ToolRegistration]:
    """Return a snapshot of all registered tools."""
    return list(_tool_registry)


def clear_registry() -> None:
    """Clear all registered tools. Used for testing and server restart."""
    _tool_registry.clear()
    _registered_tool_names.clear()
    logger.debug("Tool registry cleared")


__all__ = ["tool", "iter_tools", "clear_registry"]
