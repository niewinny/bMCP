"""
Get Resources Operator

Executes a registered resource handler on Blender's main thread.
Uses the resource registry to look up handlers by URI.
"""

import bpy

from ..mcp.resources._internal.registry import iter_resources

# Safety limit for output size
MAX_OUTPUT_SIZE = 2_000_000  # 2MB maximum output size


class BMCP_OT_get_resources(bpy.types.Operator):
    """Execute a registered resource handler on main thread (Internal operator)"""

    bl_idname = "bmcp.get_resources"
    bl_label = "Get Resources"
    bl_options = {"INTERNAL"}

    uri: bpy.props.StringProperty(
        name="URI",
        description="Resource URI to read (e.g., blender://active_scene)",
        default="",
        options={"SKIP_SAVE"},
    )

    job_id: bpy.props.StringProperty(
        name="Job ID",
        description="Unique identifier for this execution",
        default="",
        options={"SKIP_SAVE"},
    )

    def execute(self, context) -> set[str]:
        # Validate context is available
        if context is None or context.window_manager is None:
            self.report({"ERROR"}, "Invalid context: window_manager not available")
            return {"CANCELLED"}

        result_key = f"mcp_resource_data_{self.job_id}"
        done_key = f"mcp_resource_done_{self.job_id}"
        error_key = f"mcp_resource_error_{self.job_id}"

        # Clean up any stale data from previous execution
        context.window_manager.pop(result_key, None)
        context.window_manager.pop(done_key, None)
        context.window_manager.pop(error_key, None)

        try:
            # Find handler for this URI
            handler = None
            for reg in iter_resources():
                if reg.uri == self.uri:
                    handler = reg.handler
                    break

            if handler is None:
                error_msg = f"Resource not found: {self.uri}"
                context.window_manager[error_key] = error_msg
                context.window_manager[done_key] = True
                self.report({"ERROR"}, error_msg)
                return {"CANCELLED"}

            # Execute handler (sync function)
            result = handler()

            # Validate result is a string
            if not isinstance(result, str):
                result = str(result)

            # Truncate if too large - provide clear warning with details
            if len(result) > MAX_OUTPUT_SIZE:
                original_size = len(result)
                result = (
                    result[:MAX_OUTPUT_SIZE] + f"\n\n[OUTPUT TRUNCATED]\n"
                    f"Original size: {original_size:,} bytes\n"
                    f"Limit: {MAX_OUTPUT_SIZE:,} bytes (2MB)\n"
                    f"Truncated: {original_size - MAX_OUTPUT_SIZE:,} bytes"
                )

            # Store result directly (no JSON encoding - result is already a string)
            context.window_manager[result_key] = result
            context.window_manager[done_key] = True

            return {"FINISHED"}

        except Exception as e:
            error_msg = f"Resource execution failed: {type(e).__name__}: {str(e)}"
            # Store in window_manager FIRST, then report (ensures data is available to waiting threads)
            context.window_manager[error_key] = error_msg
            context.window_manager[done_key] = True
            self.report({"ERROR"}, error_msg)
            return {"CANCELLED"}
