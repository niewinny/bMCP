"""
bmcp.server — Server lifecycle, configuration, and transport.

Eager imports: config constants and validation (safe, no bpy).
Lifecycle functions use internal lazy imports to avoid triggering bpy at
module load time, enabling standalone library usage.
"""

import threading

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
    PROTOCOL_VERSION,
    # Validation
    validate_port,
    validate_config,
    ConfigValidationResult,
)

# ---------------------------------------------------------------------------
# Lazy singleton — created on first call to a lifecycle function.
# Lives here (the public namespace) rather than in transport/http_server so
# that server.py owns the lifecycle and transport/ stays a pure implementation
# detail.
# ---------------------------------------------------------------------------
_server_manager = None
_server_manager_lock = threading.Lock()


def _get_server_manager():
    """Get or create the module-level ServerManager singleton."""
    global _server_manager
    if _server_manager is None:
        with _server_manager_lock:
            if _server_manager is None:
                import importlib
                mod = importlib.import_module(".transport.http_server", "bmcp")
                _server_manager = mod.ServerManager()
    return _server_manager


# ---------------------------------------------------------------------------
# Lazy class accessors — avoids importing bpy at module load time.
# Uses importlib.import_module() (not ``from . import``) to prevent
# Python 3.13 infinite recursion in module __getattr__.
# ---------------------------------------------------------------------------
def __getattr__(name):
    import importlib

    if name == "ServerManager":
        mod = importlib.import_module(".transport.http_server", "bmcp")
        attr = mod.ServerManager
        globals()[name] = attr
        return attr
    if name == "MCPServer":
        mod = importlib.import_module(".core", "bmcp")
        attr = mod.MCPServer
        globals()[name] = attr
        return attr
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ---------------------------------------------------------------------------
# Public lifecycle functions
# ---------------------------------------------------------------------------
def start():
    """Start the MCP server."""
    return _get_server_manager().start()


def stop():
    """Stop the MCP server."""
    return _get_server_manager().stop()


def is_running():
    """Whether the server is currently running."""
    if _server_manager is None:
        return False
    return _server_manager.is_running()


def is_shutting_down():
    """Whether the server is in the process of shutting down."""
    if _server_manager is None:
        return False
    return _server_manager.is_shutting_down()


def wait(timeout=3.0):
    """Wait for server shutdown to complete.

    Args:
        timeout: Maximum time to wait in seconds (default: 3.0)

    Returns:
        bool: True if shutdown completed, False if timeout
    """
    if _server_manager is None:
        return True
    return _server_manager.wait_for_shutdown(timeout=timeout)


def unregister():
    """Unregister hook — stop server on addon unload."""
    if _server_manager is not None:
        _server_manager.stop()


__all__ = [
    # Lifecycle
    "start",
    "stop",
    "is_running",
    "is_shutting_down",
    "wait",
    "unregister",
    # Constants
    "DEFAULT_PORT",
    "DEFAULT_AUTH_TOKEN_LENGTH",
    "TOOL_TIMEOUT",
    "RESOURCE_TIMEOUT",
    "OUTPUT_LIMIT",
    "STARTUP_TIMEOUT",
    "SHUTDOWN_TIMEOUT",
    "MAX_PENDING_OPS",
    "PROTOCOL_VERSION",
    # Validation
    "validate_port",
    "validate_config",
    "ConfigValidationResult",
    # Classes
    "ServerManager",
    "MCPServer",
]
