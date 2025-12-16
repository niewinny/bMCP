"""
Blender Code Execution Tool

Provides the main tool for executing arbitrary Python code in Blender's context.
"""

from typing import TYPE_CHECKING

from ._internal.registry import tool

if TYPE_CHECKING:
    from ._internal.context import ToolContext


@tool
async def blender_run_code(ctx: "ToolContext", code: str) -> str:
    """
    Execute Python code in Blender's context with full bpy API access.

    This tool allows running arbitrary Python code within Blender's environment.
    The code has access to bpy and the current Blender context. Use this to
    manipulate scenes, objects, materials, animations, or any other Blender
    functionality.

    Args:
        code: Python code to execute in Blender. The code should start with
             'import bpy' to access Blender's API.

    Returns:
        Execution output (stdout) or error message

    Examples:
        - Create a cube:
          import bpy
          bpy.ops.mesh.primitive_cube_add(location=(0, 0, 0))

        - List all objects:
          import bpy
          print([obj.name for obj in bpy.data.objects])

        - Modify active object:
          import bpy
          bpy.context.active_object.location.z += 1

        - Add a material:
          import bpy
          mat = bpy.data.materials.new(name="MyMaterial")
          bpy.context.active_object.data.materials.append(mat)

        - Get current context:
          import bpy
          print(f"Mode: {bpy.context.mode}")
          print(f"Active: {bpy.context.active_object.name if bpy.context.active_object else None}")
          print(f"Selected: {[o.name for o in bpy.context.selected_objects]}")
    """
    # Dual execution path: HTTP (direct) vs stdio (forwarded)
    # Context is injected automatically (like FastAPI's Depends)

    # Use the convenience method that handles both modes uniformly
    result = await ctx.call_blender_operator("blender_run_code", {"code": code})

    if ctx.is_http_mode:
        # HTTP mode: result is dict from operator
        if not isinstance(result, dict):
            raise RuntimeError(f"Expected dict result in HTTP mode, got {type(result).__name__}")

        if result.get("status") == "error":
            error_msg = result.get("error", "Tool execution failed")
            raise RuntimeError(error_msg)

        output = result.get("output", "")
        if not output:
            output = "Code executed successfully (no output)"
        return output
    else:
        # stdio mode: result is MCP response format
        if isinstance(result, list) and len(result) > 0:
            content_item = result[0]
            if isinstance(content_item, dict) and content_item.get("type") == "text":
                return content_item.get("text", "No output")

        return str(result)

    # NOTE: Exceptions propagate to handlers.py which wraps them with isError: True
