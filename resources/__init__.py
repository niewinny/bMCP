"""
Blender-specific MCP resources.

Importing this module triggers registration of Blender resources via decorators.
"""

from . import (  # noqa: F401
    active_scene,
    selected_compositor,
    selected_geometry_nodes,
    selected_mesh,
    selected_objects,
    selected_shaders,
)
