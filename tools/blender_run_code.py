"""
Blender Code Execution Tool

Provides the main tool for executing arbitrary Python code in Blender's context.
"""

from bmcp import tool


@tool
async def blender_run_code(ctx, code: str) -> str:
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
    # Context is injected automatically (like FastAPI's Depends).
    # call_blender_operator normalizes the result from any transport into
    # a uniform {"output": str, "error": str | None} dict.
    result = await ctx.call_blender_operator("blender_run_code", {"code": code})

    output = result.get("output", "")
    return output if output else "Code executed successfully (no output)"
