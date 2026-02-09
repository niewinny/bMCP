"""
Base Tool Context and Helpers

Provides context access for tool functions to get execution environment details.
Uses a shared global instance with lock protection for thread safety.
"""

import threading
from typing import Any, Callable, Optional


class ToolContext:
    """
    Context object that tools can access to get execution environment.

    Provides methods for executing Blender operators from async tool functions.
    Handles both HTTP mode (direct execution) and stdio mode (forwarded to bridge).

    Attributes:
        execute_fn: Function to execute tools on Blender's main thread
        anyio_module: anyio module for async/sync bridging (None for stdio mode)
    """

    def __init__(self):
        self.execute_fn: Optional[Callable[[str, dict], Any]] = None
        self.anyio_module: Optional[Any] = None

    @property
    def is_http_mode(self) -> bool:
        """Check if running in HTTP mode (vs stdio mode)."""
        return self.anyio_module is not None

    @property
    def is_stdio_mode(self) -> bool:
        """Check if running in stdio mode (vs HTTP mode)."""
        return self.anyio_module is None

    async def call_blender_operator(
        self, tool_name: str, arguments: dict
    ) -> dict[str, Any]:
        """
        Call a Blender operator/tool through the execution bridge.

        Normalizes the result from both HTTP and stdio transports into a
        uniform dict with ``{"output": str, "error": str | None}``.

        Args:
            tool_name: Name of the Blender tool to call
            arguments: Tool arguments dict

        Returns:
            Normalized dict: ``{"output": ..., "error": ...}``

        Raises:
            RuntimeError: If context not initialized via set_context()
            RuntimeError: If the operator reports an error

        Usage:
            async def my_tool(ctx: ToolContext, code: str) -> str:
                result = await ctx.call_blender_operator(
                    "blender_run_code",
                    {"code": code}
                )
                return result["output"]
        """
        if self.execute_fn is None:
            raise RuntimeError(
                "Context not initialized - set_context() must be called before call_blender_operator()"
            )

        if self.is_http_mode:
            # HTTP mode: execute through thread bridge
            raw = await self.anyio_module.to_thread.run_sync(
                self.execute_fn, tool_name, arguments
            )
        else:
            # stdio mode: forward to bridge
            raw = await self.execute_fn(tool_name, arguments)

        return self._normalize_result(raw)

    @staticmethod
    def _normalize_result(raw: Any) -> dict[str, Any]:
        """
        Normalize a transport result into ``{"output": str, "error": str | None}``.

        Handles:
        - dict with "output"/"error"/"status" keys (HTTP mode)
        - list of MCP content items ``[{"type": "text", "text": ...}]`` (stdio mode)
        - plain str or other types (fallback)

        Raises:
            RuntimeError: If the result carries an error status.
        """
        if isinstance(raw, dict):
            if raw.get("status") == "error":
                raise RuntimeError(raw.get("error", "Tool execution failed"))
            return {
                "output": raw.get("output", ""),
                "error": None,
            }

        if isinstance(raw, list) and raw:
            first = raw[0]
            if isinstance(first, dict) and first.get("type") == "text":
                return {
                    "output": first.get("text", ""),
                    "error": None,
                }

        # Fallback: stringify
        return {"output": str(raw) if raw else "", "error": None}


# Global context instance shared across all threads
# This is intentionally global because:
# 1. set_context() is called once at server startup (from main thread)
# 2. get_context() is called from HTTP server thread when executing tools
# 3. The context values don't change after initialization
# Thread safety is ensured by using a lock for writes
_tool_context = ToolContext()
_context_lock = threading.Lock()


def get_context() -> ToolContext:
    """
    Get the shared tool execution context.

    Returns:
        ToolContext with execute_fn and anyio_module set

    Thread Safety:
        Uses a lock for consistent reads, matching the lock used in set_context().
        The context is shared across threads because it's set once at startup
        and read from the HTTP server thread during tool execution.

    Usage:
        async def my_tool(param: str) -> str:
            ctx = get_context()
            if ctx.is_http_mode:
                # HTTP-specific logic
                result = await ctx.anyio_module.to_thread.run_sync(...)
            else:
                # stdio-specific logic
                result = await ctx.execute_fn(...)
            return result
    """
    with _context_lock:
        return _tool_context


def set_context(execute_fn: Callable[[str, dict], Any], anyio_module: Any) -> None:
    """
    Set the tool execution context (called once at server startup).

    This is called during tool registration to inject dependencies.
    Uses a lock to ensure thread-safe writes.

    Args:
        execute_fn: Function to execute tools on main thread
        anyio_module: anyio module reference (or None for stdio)

    Thread Safety:
        Uses a lock to ensure atomic writes, though in practice this is
        only called once at server startup before any tools are executed.
    """
    with _context_lock:
        _tool_context.execute_fn = execute_fn
        _tool_context.anyio_module = anyio_module
