"""
bmcp.server — Server lifecycle, configuration, and transport.

Eager imports: config constants and validation (safe, no bpy).
Lazy imports: server lifecycle functions and ServerManager (trigger bpy).
"""

from .config import (
    # Constants (short aliases)
    DEFAULT_SERVER_PORT as DEFAULT_PORT,
    DEFAULT_AUTH_TOKEN_LENGTH,
    TOOL_EXECUTION_TIMEOUT as TOOL_TIMEOUT,
    RESOURCE_EXECUTION_TIMEOUT as RESOURCE_TIMEOUT,
    OUTPUT_SIZE_LIMIT as OUTPUT_LIMIT,
    SERVER_STARTUP_TIMEOUT as STARTUP_TIMEOUT,
    GRACEFUL_SHUTDOWN_TIMEOUT as SHUTDOWN_TIMEOUT,
    MAX_PENDING_OPERATIONS as MAX_PENDING_OPS,
    SSE_QUEUE_SIZE,
    # Validation
    validate_port,
    validate_config,
    ConfigValidationResult,
    clear_port_validation_cache,
)

# Lifecycle functions and classes are lazily imported to avoid triggering bpy.
_LAZY_TRANSPORT = frozenset({
    "start", "stop", "is_running", "is_shutting_down", "wait", "ServerManager",
})


def __getattr__(name):
    if name in _LAZY_TRANSPORT:
        import importlib
        mod = importlib.import_module(".transport.http_server", "bmcp")
        return getattr(mod, name)
    if name == "MCPServer":
        from .core import MCPServer
        return MCPServer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Lifecycle
    "start",
    "stop",
    "is_running",
    "is_shutting_down",
    "wait",
    # Constants
    "DEFAULT_PORT",
    "DEFAULT_AUTH_TOKEN_LENGTH",
    "TOOL_TIMEOUT",
    "RESOURCE_TIMEOUT",
    "OUTPUT_LIMIT",
    "STARTUP_TIMEOUT",
    "SHUTDOWN_TIMEOUT",
    "MAX_PENDING_OPS",
    "SSE_QUEUE_SIZE",
    # Validation
    "validate_port",
    "validate_config",
    "ConfigValidationResult",
    "clear_port_validation_cache",
    # Classes
    "ServerManager",
    "MCPServer",
]
