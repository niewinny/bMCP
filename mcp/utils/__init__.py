"""
MCP Utilities

Shared utility functions and helpers.
"""

from .config import (
    DEFAULT_AUTH_TOKEN_LENGTH,
    # Configuration constants
    DEFAULT_SERVER_PORT,
    GRACEFUL_SHUTDOWN_TIMEOUT,
    MAX_PENDING_OPERATIONS,
    OUTPUT_SIZE_LIMIT,
    RESOURCE_EXECUTION_TIMEOUT,
    RESOURCE_POLL_INTERVAL,
    SERVER_STARTUP_TIMEOUT,
    SSE_POLL_INTERVAL,
    SSE_QUEUE_SIZE,
    STALE_PROPERTY_AGE,
    TOOL_EXECUTION_TIMEOUT,
    ConfigValidationResult,
    validate_config,
    validate_port,
)
from .validators import (
    check_docstring,
    check_return_type,
    validate_callable,
    validate_has_name,
)

__all__ = [
    # Decorator validators
    "validate_callable",
    "validate_has_name",
    "check_docstring",
    "check_return_type",
    # Config validation
    "validate_config",
    "validate_port",
    "ConfigValidationResult",
    # Configuration constants
    "DEFAULT_SERVER_PORT",
    "DEFAULT_AUTH_TOKEN_LENGTH",
    "TOOL_EXECUTION_TIMEOUT",
    "RESOURCE_EXECUTION_TIMEOUT",
    "SERVER_STARTUP_TIMEOUT",
    "GRACEFUL_SHUTDOWN_TIMEOUT",
    "MAX_PENDING_OPERATIONS",
    "SSE_QUEUE_SIZE",
    "STALE_PROPERTY_AGE",
    "OUTPUT_SIZE_LIMIT",
    "RESOURCE_POLL_INTERVAL",
    "SSE_POLL_INTERVAL",
]
