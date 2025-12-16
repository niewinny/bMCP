import bpy

from .. import __package__ as base_package
from ..mcp import is_running as is_server_running
from ..mcp.utils.config import DEFAULT_SERVER_PORT

# Version constant - update this when version changes
ADDON_VERSION = (1, 0, 0)


class BMCPMainMenu(bpy.types.Menu):
    bl_idname = "BMCP_MT_Main"
    bl_label = f"bMCP: {ADDON_VERSION[0]}.{ADDON_VERSION[1]}.{ADDON_VERSION[2]}"

    def draw(self, _context) -> None:
        layout = self.layout
        layout.operator_context = "INVOKE_DEFAULT"

        server_running = is_server_running()

        addon_prefs = bpy.context.preferences.addons.get(base_package)
        if addon_prefs and addon_prefs.preferences:
            # Use getattr for safety in case properties don't exist
            port = getattr(addon_prefs.preferences, 'server_port', DEFAULT_SERVER_PORT)
            network_access = getattr(addon_prefs.preferences, 'network_access', False)
        else:
            port = DEFAULT_SERVER_PORT
            network_access = False

        layout.separator(type="SPACE", factor=0.5)
        col = layout.column(align=True)
        col.scale_y = 0.9
        if server_running:
            col.label(text="Status: Running")
            if network_access:
                col.label(text=f"SSE:  http://127.0.0.1:{port}/sse")
                col.label(text=f"HTTP: http://127.0.0.1:{port}/http")
                # Display security warning when network access is enabled (0.0.0.0 binding allows remote code execution)
                warning_col = layout.column(align=True)
                warning_col.alert = True
                warning_col.scale_y = 0.8
                warning_col.label(text="SECURITY WARNING", icon="ERROR")
                warning_col.label(text="Network accessible - Code execution from network!")
            else:
                col.label(text=f"SSE:  http://127.0.0.1:{port}/sse")
                col.label(text=f"HTTP: http://127.0.0.1:{port}/http")
                col.label(text="(Localhost only)", icon="LOCKED")
        else:
            col.label(text="Status: Disabled")

        layout.separator(type="SPACE", factor=1.0)

        col = layout.column(align=True)
        col.scale_y = 1.4

        # Start button - disabled when server is running
        row = col.row()
        row.enabled = not server_running
        row.operator("bmcp.start_mcp_server", text="Start Server", icon="PLAY")

        # Stop button - disabled when server is not running
        row = col.row()
        row.enabled = server_running
        row.operator("bmcp.stop_mcp_server", text="Stop Server", icon="PAUSE")

        layout.separator(type="SPACE", factor=1.0)


def draw_bmcp_menu(self, _context) -> None:
    """Draw the bMCP menu in the top bar."""
    layout = self.layout
    layout.menu("BMCP_MT_Main", text="bMCP")


classes = (BMCPMainMenu,)


def register() -> None:
    """Register UI elements with Blender."""
    bpy.types.TOPBAR_MT_editor_menus.append(draw_bmcp_menu)


def unregister() -> None:
    """Unregister UI elements from Blender."""
    bpy.types.TOPBAR_MT_editor_menus.remove(draw_bmcp_menu)
