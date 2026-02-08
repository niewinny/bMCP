"""
Resources Registry - Decorator and storage for MCP resources.

Provides @resource decorator and registry for resource discovery.
Supports configurable URI scheme (default: "app", set to "blender" for Blender addon).
"""

from dataclasses import dataclass
from types import FunctionType
from typing import List, Optional, Set

# Import directly from submodules to avoid circular import through bmcp/__init__.py
from ...logger import get_logger
from ...utils import validators as utils

logger = get_logger("bmcp-resources-registry")

# Configurable URI scheme - default for standalone use
_uri_scheme: str = "app"


def set_uri_scheme(scheme: str) -> None:
    """
    Set the URI scheme for resource registration.

    Args:
        scheme: URI scheme to use (e.g., "blender", "app")
    """
    global _uri_scheme
    _uri_scheme = scheme
    logger.debug("URI scheme set to: %s", scheme)


def get_uri_scheme() -> str:
    """Get the current URI scheme."""
    return _uri_scheme


@dataclass
class ResourceRegistration:
    """Resource registration entry."""

    uri: str
    handler: FunctionType
    name: Optional[str] = None
    description: Optional[str] = None


# Internal registry populated by @resource decorator
_resource_registry: List[ResourceRegistration] = []
_registered_uris: Set[str] = set()  # Track URIs to prevent duplicates


def resource(func: FunctionType) -> FunctionType:
    """
    Decorator to register a resource.

    Resources are synchronous functions that run on the main thread (in Blender)
    or in a thread pool (standalone). They are executed via the executor when
    a client requests a resource read.

    The resource URI is automatically generated as "{scheme}://{function_name}".
    The resource name is automatically derived from the function name, and the
    description is extracted from the function's docstring.

    Args:
        func: The function to register as a resource (must be sync, return str)

    Returns:
        The same function (unmodified)

    Example:
        @resource  # Auto-generates URI: app://blender_version (or blender://blender_version)
        def blender_version() -> str:
            '''Get the current Blender version.'''
            import bpy
            return f"Blender {bpy.app.version_string}"
    """
    # Validate function (returns True/False)
    is_valid = (
        utils.validate_callable(func, "resource", logger)
        and utils.validate_has_name(func, "resource", logger)
        and utils.check_docstring(func, logger)
        and utils.check_return_type(func, str, strict=True, logger=logger)
    )

    # Only register if all validations passed
    if is_valid:
        uri = f"{_uri_scheme}://{func.__name__}"

        # Check for duplicate URI
        if uri in _registered_uris:
            logger.error(
                "Resource URI '%s' is already registered. "
                "Each resource must have a unique URI. "
                "The duplicate registration will be ignored.",
                uri,
            )
            return func

        _resource_registry.append(ResourceRegistration(uri=uri, handler=func))
        _registered_uris.add(uri)
        logger.debug("Registered resource: %s", uri)

    return func


def iter_resources() -> List[ResourceRegistration]:
    """Return a snapshot of all registered resources."""
    return list(_resource_registry)


def clear_registry() -> None:
    """Clear all registered resources.

    Used for testing and server restart to prevent stale registrations.
    """
    _resource_registry.clear()
    _registered_uris.clear()
    logger.debug("Resource registry cleared")


__all__ = ["resource", "iter_resources", "clear_registry", "set_uri_scheme", "get_uri_scheme"]
