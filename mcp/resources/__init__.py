"""
MCP Resources - Dynamic resource discovery system
"""

from ..logger import get_logger
from . import (  # noqa: F401
    active_scene,
    selected_compositor,
    selected_geometry_nodes,
    selected_mesh,
    selected_objects,
    selected_shaders,
)
from ._internal.registry import iter_resources

logger = get_logger("bmcp-resources")


def register_resources():
    """
    Initialize resources system.

    Resources are already imported and registered via decorators.
    This function just logs the initialization.
    """
    logger.info("Initializing resources system...")

    # Count and list registered resources
    resources = list(iter_resources())
    resource_count = len(resources)
    logger.info("Resources system ready - %d resource(s) available", resource_count)

    # Debug: log each resource URI
    for res in resources:
        logger.debug(
            "  Registered resource: %s (handler: %s)", res.uri, res.handler.__name__
        )


# Public API
__all__ = [
    "register_resources",
]
