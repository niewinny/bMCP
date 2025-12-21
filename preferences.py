import json
import os
import secrets
import string
import sys

import bpy

from . import __package__ as base_package
from .mcp.utils.config import DEFAULT_AUTH_TOKEN_LENGTH, DEFAULT_SERVER_PORT


def generate_token(length=DEFAULT_AUTH_TOKEN_LENGTH):
    """Generate a secure random authentication token."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class BMCP_Preference(bpy.types.AddonPreferences):
    bl_idname = base_package

    def update_network_access(self, context):
        """Update callback for network access"""
        if self.network_access:
            self.auth_required = True

    def update_auth_required(self, context):
        """Update callback for auth required"""
        # If auth is disabled but network access is still on, disable network access
        if not self.auth_required and self.network_access:
            self.network_access = False

    network_access: bpy.props.BoolProperty(
        name="Allow Network Access",
        description="SECURITY WARNING: Allows arbitrary Python code execution from network! Only enable on trusted networks. Required for WSL2, Docker, or remote access. When disabled, only localhost connections are allowed (127.0.0.1)",
        default=False,
        update=update_network_access,
    )

    auth_token: bpy.props.StringProperty(
        name="Authentication Token",
        description="Secure token required for all HTTP/SSE connections. Clients must provide this via 'Authorization: Bearer <token>' header or '?token=<token>' query parameter",
        default="",
    )

    auth_required: bpy.props.BoolProperty(
        name="Authentication Required",
        description="Require a token for all connections. Automatically enabled when Network Access is on",
        default=False,
        update=update_auth_required,
    )

    server_port: bpy.props.IntProperty(
        name="Server Port",
        description="Port number for the MCP server",
        default=DEFAULT_SERVER_PORT,
        min=1024,
        max=65535,
    )

    enable_logs: bpy.props.BoolProperty(
        name="Enable Detailed Logs",
        description="Enable detailed logging to console (useful for debugging). Shows all log levels including DEBUG. When disabled, only ERROR and WARNING messages are shown",
        default=False,
    )

    setup_tab: bpy.props.EnumProperty(
        name="Setup Tab",
        description="Select which transport configuration to view",
        items=[
            ("STDIO", "Stdio", "For Claude Desktop (stdio bridge)", "CONSOLE", 0),
            ("HTTP", "HTTP", "For sync clients (LM Studio)", "NETWORK_DRIVE", 1),
            ("SSE", "SSE", "For streaming clients (Claude Code, Cursor)", "LIGHT", 2),
        ],
        default="STDIO",
    )

    def draw(self, context):
        """Draw the preferences panel"""
        layout = self.layout

        layout.use_property_split = True
        layout.use_property_decorate = False

        # Server Settings Section
        row = layout.row()
        row.prop(self, "network_access")
        if self.network_access:
            warning_box = layout.box()
            warning_box.alert = True
            col = warning_box.column(align=True)
            col.label(text="SECURITY WARNING", icon="ERROR")
            col.label(text="Network access allows ANYONE on your network to execute")
            col.label(text="arbitrary Python code in Blender with full system access!")
            col.label(text="Only enable on trusted networks or use firewall rules.")

        row = layout.row()
        row.prop(self, "auth_required")
        if self.auth_required:
            row = layout.row()
            row.prop(self, "auth_token")

            # Regenerate button
            row.operator("bmcp.regenerate_token", text="", icon="FILE_REFRESH")

            if not self.auth_token:
                layout.alert = True
                layout.label(
                    text="WARNING: No token set! Server is insecure.", icon="ERROR"
                )
                layout.alert = False

        row = layout.row()
        row.prop(self, "server_port")

        row = layout.row()
        row.prop(self, "enable_logs")

        # Tab Selection
        layout.separator()
        layout.label(text="Client Configuration", icon="PLUGIN")
        row = layout.row(align=True)
        row.prop(self, "setup_tab", expand=True)

        # Show content based on selected tab
        if self.setup_tab == "STDIO":
            self._draw_stdio_tab(layout)
        elif self.setup_tab == "HTTP":
            self._draw_http_tab(layout)
        elif self.setup_tab == "SSE":
            self._draw_sse_tab(layout)

    def _draw_stdio_tab(self, layout):
        """Draw the Stdio configuration tab"""

        # Get paths
        python_exe = sys.executable
        addon_dir = os.path.dirname(os.path.abspath(__file__))
        stdio_script = os.path.join(addon_dir, "mcp", "transport", "stdio.py")

        # Generate JSON configuration
        config = {
            "mcpServers": {"blender": {"command": python_exe, "args": [stdio_script]}}
        }
        config_json = json.dumps(config, indent=2)

        # Display the configuration in a readable format
        col = layout.column(align=True)
        col.scale_y = 0.75
        for line in config_json.split("\n"):
            col.label(text=f"   {line}")

        # Copy button
        row = layout.row()
        row.scale_y = 1.3
        props = row.operator(
            "bmcp.copy_config", text="Copy Configuration", icon="COPYDOWN"
        )
        props.config_text = config_json
        props.config_type = "STDIO"

    def _draw_http_tab(self, layout):
        """Draw the HTTP configuration tab"""

        server_url = f"http://localhost:{self.server_port}/http"

        # Add token to config if present
        headers = {}
        if self.auth_required and self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        config = {"mcpServers": {"blender": {"url": server_url, "headers": headers}}}
        config_json = json.dumps(config, indent=2)

        # Display the configuration
        col = layout.column(align=True)
        col.scale_y = 0.75
        for line in config_json.split("\n"):
            col.label(text=f"   {line}")

        # Copy button
        row = layout.row()
        row.scale_y = 1.3
        props = row.operator(
            "bmcp.copy_config", text="Copy Configuration", icon="COPYDOWN"
        )
        props.config_text = config_json
        props.config_type = "HTTP"

    def _draw_sse_tab(self, layout):
        """Draw the SSE configuration tab (for streaming clients)"""

        server_url = f"http://localhost:{self.server_port}/sse"

        # Add token to config if present
        headers = {}
        if self.auth_required and self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        config = {"mcpServers": {"blender": {"url": server_url, "headers": headers}}}
        config_json = json.dumps(config, indent=2)

        # Display the configuration
        col = layout.column(align=True)
        col.scale_y = 0.75
        for line in config_json.split("\n"):
            col.label(text=f"   {line}")

        # Copy button
        row = layout.row()
        row.scale_y = 1.3
        props = row.operator(
            "bmcp.copy_config", text="Copy Configuration", icon="COPYDOWN"
        )
        props.config_text = config_json
        props.config_type = "SSE"


class BMCP_OT_CopyConfig(bpy.types.Operator):
    """Copy configuration to clipboard"""

    bl_idname = "bmcp.copy_config"
    bl_label = "Copy Configuration"
    bl_description = "Copy the client configuration to clipboard"

    config_text: bpy.props.StringProperty(
        name="Config Text",
        description="Configuration text to copy",
        options={"SKIP_SAVE"},
    )
    config_type: bpy.props.StringProperty(
        name="Config Type",
        description="Type of configuration being copied",
        options={"SKIP_SAVE"},
    )

    def execute(self, context):
        bpy.context.window_manager.clipboard = self.config_text
        self.report({"INFO"}, "Configuration copied!")
        return {"FINISHED"}


class BMCP_OT_RegenerateToken(bpy.types.Operator):
    """Regenerate authentication token"""

    bl_idname = "bmcp.regenerate_token"
    bl_label = "Regenerate Token"
    bl_description = "Generate a new secure authentication token"

    def execute(self, context):
        addon = context.preferences.addons.get(base_package)
        if not addon or not addon.preferences:
            self.report({"ERROR"}, "Addon preferences not found")
            return {"CANCELLED"}
        addon.preferences.auth_token = generate_token()
        self.report({"INFO"}, "New authentication token generated")
        return {"FINISHED"}


classes = (BMCP_Preference, BMCP_OT_CopyConfig, BMCP_OT_RegenerateToken)
