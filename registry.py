"""Registry module for managing Blender addon class registration."""

import logging

from bpy.utils import register_class, unregister_class

from . import ops, preferences, ui

classes = (
    *preferences.classes,
    *ops.classes,
    *ui.classes,
)


def register():
    """Register all addon classes and UI elements."""
    for cls in classes:
        register_class(cls)

    ui.register()


def unregister():
    """Unregister all addon classes and UI elements."""
    # 1. Unregister UI first - removes menu that references server state
    ui.unregister()

    # 2. Stop the MCP server if running (no more UI callbacks can occur)
    from bmcp.server import is_running, is_shutting_down, stop, wait

    try:
        if is_running() and not is_shutting_down():
            stop()
            wait(timeout=2.0)
    except Exception as e:
        logging.getLogger(__name__).warning("Error stopping server on unregister: %s", e)

    # 3. Unregister classes in reverse order
    for cls in reversed(classes):
        unregister_class(cls)
