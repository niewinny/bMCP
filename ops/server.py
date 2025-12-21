"""
Server Control Operators

Provides Blender operators for starting and stopping the MCP server.
"""

import bpy

from ..mcp import is_running, is_shutting_down, start_server, stop_server, wait_shutdown


class BMCP_OT_start_mcp_server(bpy.types.Operator):
    """Start the bMCP server"""

    bl_idname = "bmcp.start_mcp_server"
    bl_label = "Start MCP Server"
    bl_description = "Start the MCP server for AI assistant communication"
    bl_options = {"REGISTER"}

    def execute(self, _context) -> set[str]:
        # Check if server is shutting down - wait for it to complete
        if is_shutting_down():
            self.report({"INFO"}, "Waiting for previous server to shut down...")
            # Wait up to 3 seconds for shutdown to complete
            if not wait_shutdown(timeout=3.0):
                self.report(
                    {"WARNING"}, "Server is still shutting down, please wait a moment"
                )
                return {"CANCELLED"}

        # Check if already running
        if is_running():
            self.report({"WARNING"}, "MCP Server is already running")
            return {"CANCELLED"}

        if start_server():
            self.report({"INFO"}, "MCP Server started")
            return {"FINISHED"}
        else:
            self.report(
                {"ERROR"},
                "Failed to start MCP Server - Check console for details (port may be in use)",
            )
            return {"CANCELLED"}


class BMCP_OT_stop_mcp_server(bpy.types.Operator):
    """Stop the bMCP server"""

    bl_idname = "bmcp.stop_mcp_server"
    bl_label = "Stop MCP Server"
    bl_description = "Stop the MCP server"
    bl_options = {"REGISTER"}

    def execute(self, _context) -> set[str]:
        if not is_running():
            self.report({"WARNING"}, "MCP Server is not running")
            return {"CANCELLED"}

        if stop_server():
            self.report({"INFO"}, "MCP Server stopped")
            return {"FINISHED"}
        else:
            self.report(
                {"ERROR"}, "Failed to stop MCP Server - Check console for details"
            )
            return {"CANCELLED"}
