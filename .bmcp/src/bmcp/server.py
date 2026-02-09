"""
bmcp.server — Server lifecycle, configuration, and transport.

Eager imports: config constants and validation (safe, no bpy).
Lazy imports: server lifecycle functions and ServerManager (trigger bpy).
"""

from .config import (
    # Constants
    DEFAULT_PORT,
    DEFAULT_AUTH_TOKEN_LENGTH,
    TOOL_TIMEOUT,
    RESOURCE_TIMEOUT,
    OUTPUT_LIMIT,
    STARTUP_TIMEOUT,
    SHUTDOWN_TIMEOUT,
    MAX_PENDING_OPS,
    SSE_QUEUE_SIZE,
    # Validation
    validate_port,
    validate_config,
    ConfigValidationResult,
)

# Lifecycle functions and classes are lazily imported to avoid triggering bpy.
_LAZY_TRANSPORT = frozenset({
    "start", "stop", "is_running", "is_shutting_down", "wait", "ServerManager",
})


def __getattr__(name):
    import importlib

    if name in _LAZY_TRANSPORT:
        mod = importlib.import_module(".transport.http_server", "bmcp")
        attr = getattr(mod, name)
        globals()[name] = attr
        return attr
    if name == "MCPServer":
        mod = importlib.import_module(".core", "bmcp")
        attr = mod.MCPServer
        globals()[name] = attr
        return attr
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
    # Classes
    "ServerManager",
    "MCPServer",
]
