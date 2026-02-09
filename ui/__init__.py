import time

import bpy

from .. import __package__ as base_package
from bmcp.server import is_running, DEFAULT_PORT

# Cache for server state to avoid calling is_running() on every redraw
_server_state_cache = {"running": False, "timestamp": 0.0}
CACHE_TTL = 0.5  # Cache valid for 0.5 seconds


def get_cached_server_state() -> bool:
    """Get cached server running state, refreshing if stale."""
    now = time.time()
    if now - _server_state_cache["timestamp"] > CACHE_TTL:
        _server_state_cache["running"] = is_running()
        _server_state_cache["timestamp"] = now
    return _server_state_cache["running"]


def _get_addon_version() -> tuple:
    """Get addon version from blender_manifest.toml or use fallback."""
    try:
        import os
        import tomllib

        manifest_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "blender_manifest.toml",
        )
        with open(manifest_path, "rb") as f:
            data = tomllib.load(f)
        version_str = data["version"]
        parts = version_str.split(".")
        return tuple(int(p) for p in parts[:3])
    except Exception:
        pass
    return (0, 1, 0)  # Fallback


# Version from manifest
ADDON_VERSION = _get_addon_version()


class BMCPMainMenu(bpy.types.Menu):
    bl_idname = "BMCP_MT_Main"
    bl_label = f"bMCP: {ADDON_VERSION[0]}.{ADDON_VERSION[1]}.{ADDON_VERSION[2]}"

    def draw(self, _context) -> None:
        layout = self.layout
        layout.operator_context = "INVOKE_DEFAULT"

        server_running = get_cached_server_state()

        addon_prefs = bpy.context.preferences.addons.get(base_package)
        if addon_prefs and addon_prefs.preferences:
            port = getattr(addon_prefs.preferences, "server_port", DEFAULT_PORT)
            network_access = getattr(addon_prefs.preferences, "network_access", False)
        else:
            port = DEFAULT_PORT
            network_access = False

        display_host = "0.0.0.0" if network_access else "127.0.0.1"

        layout.separator(type="SPACE", factor=0.5)
        col = layout.column(align=True)
        col.scale_y = 0.9
        if server_running:
            col.label(text="Status: Running")
            if network_access:
                col.label(text=f"SSE:  http://{display_host}:{port}/sse")
                col.label(text=f"HTTP: http://{display_host}:{port}/http")
                warning_col = layout.column(align=True)
                warning_col.alert = True
                warning_col.scale_y = 0.8
                warning_col.label(text="SECURITY WARNING", icon="ERROR")
                warning_col.label(
                    text="Network accessible - Code execution from network!"
                )
            else:
                col.label(text=f"SSE:  http://{display_host}:{port}/sse")
                col.label(text=f"HTTP: http://{display_host}:{port}/http")
                col.label(text="(Localhost only)", icon="LOCKED")
        else:
            col.label(text="Status: Disabled")

        layout.separator(type="SPACE", factor=1.0)

        col = layout.column(align=True)
        col.scale_y = 1.4

        row = col.row()
        row.enabled = not server_running
        row.operator("bmcp.start_mcp_server", text="Start Server", icon="PLAY")

        row = col.row()
        row.enabled = server_running
        row.operator("bmcp.stop_mcp_server", text="Stop Server", icon="PAUSE")

        layout.separator(type="SPACE", factor=1.0)


def draw_bmcp_menu(self, _context) -> None:
    """Draw the bMCP menu in the top bar."""
    layout = self.layout
    layout.menu("BMCP_MT_Main", text="MCP")


classes = (BMCPMainMenu,)


def register():
    """Register UI elements with Blender."""
    bpy.types.TOPBAR_MT_editor_menus.append(draw_bmcp_menu)


def unregister():
    """Unregister UI elements from Blender."""
    bpy.types.TOPBAR_MT_editor_menus.remove(draw_bmcp_menu)
