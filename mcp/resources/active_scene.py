"""
Active Scene Resource

Provides information about the current Blender scene.
"""

import traceback

import bpy

from ._internal.registry import resource

# Safety limits to prevent Blender hangs
MAX_OBJECTS = 500  # Maximum objects to show detailed info for


@resource
def active_scene() -> str:
    """
    Returns comprehensive information about the active scene.

    Includes timeline, render settings, camera, and all objects grouped by type.
    """
    try:
        scene = bpy.context.scene

        # Start building markdown output
        output = f"# Current Scene: {scene.name}\n\n"

        # Timeline
        output += f"""## Timeline
- Current Frame: {scene.frame_current}
- Frame Range: {scene.frame_start} - {scene.frame_end}
- FPS: {scene.render.fps}

"""

        # Render Settings
        output += f"""## Render Settings
- Engine: {scene.render.engine}
- Resolution: {scene.render.resolution_x}x{scene.render.resolution_y} ({scene.render.resolution_percentage}%)

"""

        # Active Camera
        output += "## Active Camera\n"
        if scene.camera:
            cam = scene.camera
            output += f"- Name: {cam.name}\n"
            output += f"- Location: {[round(x, 3) for x in cam.location]}\n"
            output += f"- Rotation: {[round(x, 3) for x in cam.rotation_euler]}\n"
            if cam.data:
                output += f"- Focal Length: {cam.data.lens}mm\n"
        else:
            output += "- No active camera\n"

        # Objects
        objects = list(scene.objects)
        total_count = len(objects)

        # Limit objects to prevent hanging on huge scenes
        if total_count > MAX_OBJECTS:
            output += f"\n## Objects ({total_count:,} total - showing first {MAX_OBJECTS})\n\n"
            output += "**WARNING: Scene has too many objects** - showing limited data for performance.\n"
            output += "Use `blender_run_code` tool for custom queries on large scenes.\n\n"
            objects = objects[:MAX_OBJECTS]
        else:
            output += f"\n## Objects ({total_count} total)\n\n"

        # Group by type
        by_type = {}
        for obj in objects:
            if obj.type not in by_type:
                by_type[obj.type] = []
            by_type[obj.type].append(obj)

        for obj_type in sorted(by_type.keys()):
            objs = by_type[obj_type]
            output += f"### {obj_type} ({len(objs)})\n\n"
            for obj in objs:
                output += f"**{obj.name}**\n"
                output += f"- Location: {[round(x, 3) for x in obj.location]}\n"
                output += f"- Rotation: {[round(x, 3) for x in obj.rotation_euler]}\n"
                output += f"- Scale: {[round(x, 3) for x in obj.scale]}\n"

                if obj.parent:
                    output += f"- Parent: {obj.parent.name}\n"

                if obj.type == "MESH" and obj.data and obj.data.materials:
                    mats = [mat.name for mat in obj.data.materials if mat]
                    if mats:
                        output += f"- Materials: {', '.join(mats)}\n"

                if obj.modifiers:
                    mods = [mod.name for mod in obj.modifiers]
                    output += f"- Modifiers: {', '.join(mods)}\n"

                output += "\n"

        return output

    except Exception as e:
        # Resource failed - return error as markdown string
        error_trace = traceback.format_exc()

        return f"""# Active Scene - Error

**ERROR**: Failed to retrieve scene information

**Exception Type**: {type(e).__name__}
**Error Message**: {str(e)}

## Traceback
```
{error_trace}
```

## Troubleshooting
- Check that a scene is active
- Verify scene data is not corrupted
- Try creating a new scene
- Restart Blender if issues persist
"""
