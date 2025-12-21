"""
Resources Registry - Decorator and storage for MCP resources.

Provides @resource decorator and registry for resource discovery.
"""

from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Set

# Import directly from submodules to avoid circular import through mcp/__init__.py
from ...logger import get_logger
from ...utils import validators as utils

logger = get_logger("bmcp-resources-registry")


@dataclass
class ResourceRegistration:
    """Resource registration entry."""

    uri: str
    handler: Callable[..., Any]
    name: Optional[str] = None
    description: Optional[str] = None


# Internal registry populated by @resource decorator
_resource_registry: List[ResourceRegistration] = []
_registered_uris: Set[str] = set()  # Track URIs to prevent duplicates


def resource(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator to register a resource.

    Resources are synchronous functions that run on Blender's main thread.
    They are executed via the get_resources operator when a client requests
    a resource read.

    The resource URI is automatically generated as "blender://{function_name}".
    The resource name is automatically derived from the function name, and the
    description is extracted from the function's docstring.

    Args:
        func: The function to register as a resource (must be sync, return str)

    Returns:
        The same function (unmodified)

    Example:
        @resource  # Auto-generates URI: blender://blender_version
        def blender_version() -> str:
            '''Get the current Blender version.'''
            import bpy
            return f"Blender {bpy.app.version_string}"

    Example with scene data:
        @resource  # Auto-generates URI: blender://active_scene
        def active_scene() -> str:
            '''Returns information about the active scene.'''
            import bpy
            scene = bpy.context.scene
            return f"# Scene: {scene.name}\\nObjects: {len(scene.objects)}"
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
        uri = f"blender://{func.__name__}"

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


__all__ = ["resource", "iter_resources", "clear_registry"]
