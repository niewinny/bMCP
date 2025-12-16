"""Registry module for managing Blender addon class registration."""

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
    from .mcp import is_running, is_shutting_down, stop_server, wait_shutdown

    if is_running() and not is_shutting_down():
        stop_server()
        # Wait for shutdown to complete before unregistering classes
        # This prevents race conditions where classes are unregistered while server is using them
        wait_shutdown(timeout=2.0)

    # 3. Unregister classes in reverse order
    for cls in reversed(classes):
        unregister_class(cls)
