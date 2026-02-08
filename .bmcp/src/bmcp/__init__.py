"""bmcp: Python SDK for building MCP servers."""

from .core import MCPServer
from .logger import get_logger, setup_logging
from .tools._internal.registry import tool, iter_tools, clear_registry as clear_tools
from .tools._internal.context import get_context, set_context
from .resources._internal.registry import (
    resource,
    iter_resources,
    set_uri_scheme,
    clear_registry as clear_resources,
)
from .prompts._internal.registry import (
    prompt,
    iter_prompts,
    clear_registry as clear_prompts,
)
from .transport.http_server import (
    is_server_running,
    is_server_shutting_down,
    start_mcp_server,
    stop_mcp_server,
    wait_for_shutdown,
)

__version__ = "0.1.0"

__all__ = [
    "tool",
    "resource",
    "prompt",
    "MCPServer",
    "iter_tools",
    "iter_resources",
    "iter_prompts",
    "get_context",
    "set_context",
    "set_uri_scheme",
    "clear_tools",
    "clear_resources",
    "clear_prompts",
    "get_logger",
    "setup_logging",
    "is_server_running",
    "is_server_shutting_down",
    "start_mcp_server",
    "stop_mcp_server",
    "wait_for_shutdown",
]
