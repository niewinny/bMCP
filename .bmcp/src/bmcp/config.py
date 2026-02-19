"""
Configuration validation utilities.

Validates server configuration before startup to prevent runtime issues.
Provides centralized configuration constants for the MCP server.
"""

import socket
from dataclasses import dataclass
from typing import List, Optional, Tuple

# =============================================================================
# CENTRALIZED CONFIGURATION CONSTANTS
# =============================================================================

# Server defaults
DEFAULT_PORT = 12097
DEFAULT_AUTH_TOKEN_LENGTH = 32

# Timeout settings (in seconds)
# Set to None for no timeout (infinite wait) - use with caution
TOOL_TIMEOUT: Optional[float] = 300.0  # 5 minutes for tool execution
RESOURCE_TIMEOUT: Optional[float] = 300.0  # 5 minutes for resource execution
STARTUP_TIMEOUT: float = 5.0  # Server startup timeout
SHUTDOWN_TIMEOUT: float = 1.5  # Graceful shutdown wait

# Queue limits
MAX_PENDING_OPS = 50  # Maximum concurrent pending resource operations

# Cleanup settings
STALE_PROPERTY_AGE: float = 300.0  # 5 minutes before properties are considered stale
OUTPUT_LIMIT: int = 2 * 1024 * 1024  # 2MB output limit

# Polling intervals (in seconds)
# Note: These are fallback values - event-based completion is preferred
RESOURCE_POLL_INTERVAL: float = 0.05  # 50ms polling for resource completion

# Session management
SESSION_TIMEOUT: float = 1800.0  # 30 minutes before session expires
SESSION_CLEANUP_INTERVAL: float = 300.0  # 5 minutes between cleanup sweeps

# Protocol
PROTOCOL_VERSION = "2025-11-25"
PROTOCOL_VERSION_LEGACY = "2024-11-05"

# =============================================================================
# PORT VALIDATION CACHE
# =============================================================================
_port_validation_cache: dict[tuple[str, int], bool] = {}


@dataclass
class ConfigValidationResult:
    """Result of configuration validation."""

    valid: bool
    errors: List[str]
    warnings: List[str]

    def __bool__(self):
        return self.valid


def validate_port(
    port: int, host: str, use_cache: bool = True
) -> Tuple[bool, Optional[str]]:
    """
    Validate port number and check availability.

    Uses caching to avoid expensive socket operations on repeated calls.

    Args:
        port: Port number to validate
        host: Host to check port on
        use_cache: If True, use cached validation result (default True)

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not isinstance(port, int):
        return False, f"Port must be integer, got {type(port).__name__}"

    if port < 1024:
        return False, f"Port {port} is in privileged range (< 1024)"

    if port > 65535:
        return False, f"Port {port} exceeds maximum (65535)"

    # Check cache first to avoid expensive socket operations
    cache_key = (host, port)
    if use_cache and cache_key in _port_validation_cache:
        return _port_validation_cache[cache_key], None

    # Check if port is available
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
        _port_validation_cache[cache_key] = True
    except socket.error as e:
        errno_val = getattr(e, "errno", None)
        if errno_val in (98, 10048):  # Address already in use (Linux/Windows)
            return False, f"Port {port} is already in use"
        return False, f"Port {port} unavailable: {str(e)}"

    return True, None


def validate_config(
    port: int, network_access: bool, auth_required: bool, auth_token: str
) -> ConfigValidationResult:
    """
    Validate complete server configuration.

    Args:
        port: Server port
        network_access: Whether network access is enabled (0.0.0.0 binding)
        auth_required: Whether authentication is required
        auth_token: Authentication token

    Returns:
        ConfigValidationResult with validation status, errors, and warnings
    """
    errors = []
    warnings = []

    # Determine actual host
    host = "0.0.0.0" if network_access else "127.0.0.1"

    # Port validation
    _port_ok, port_err = validate_port(port, host)
    if port_err:
        errors.append(port_err)

    # Auth validation
    if auth_required and not auth_token:
        errors.append("Authentication required but no token set")
    elif not auth_required:
        warnings.append(
            "Authentication disabled - server accessible without credentials"
        )
    elif auth_token and len(auth_token) < 16:
        warnings.append(
            f"Token length ({len(auth_token)} chars) is short - recommend 32+ characters"
        )

    # Network access validation
    if network_access:
        if not auth_required or not auth_token:
            errors.append("Network access requires authentication with a token")
        else:
            warnings.append("Network access enabled - server accessible from 0.0.0.0")

    return ConfigValidationResult(
        valid=len(errors) == 0, errors=errors, warnings=warnings
    )
