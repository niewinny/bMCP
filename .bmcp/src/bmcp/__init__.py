"""bmcp: Python SDK for building MCP servers."""

from .logger import get_logger, setup_logging
from .tools._internal.registry import tool, iter_tools, clear_registry as clear_tools
from .tools._internal.context import get_context, set_context
from .resources._internal.registry import (
    resource,
    iter_resources,
    clear_registry as clear_resources,
)
from .prompts._internal.registry import (
    prompt,
    iter_prompts,
    clear_registry as clear_prompts,
)

try:
    from importlib.metadata import version as _version
    __version__ = _version("bmcp")
except Exception:
    __version__ = "1.0.0"

__all__ = [
    "tool",
    "resource",
    "prompt",
    "iter_tools",
    "iter_resources",
    "iter_prompts",
    "get_context",
    "set_context",
    "clear_tools",
    "clear_resources",
    "clear_prompts",
    "get_logger",
    "setup_logging",
]
