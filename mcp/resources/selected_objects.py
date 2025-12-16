"""
Selected Objects Resource

Provides information about selected objects.
"""

import traceback

import bpy

from ._internal.registry import resource

# Safety limits to prevent Blender hangs
MAX_SELECTED_OBJECTS = 100  # Maximum selected objects to show detailed info for


@resource
def selected_objects() -> str:
    """
    Returns comprehensive information about selected objects.
    """
    try:
        def _format_object_info(obj):
            info = ""
            info += f"- **Type**: {obj.type}\n"
            info += f"- **Location**: {[round(x, 3) for x in obj.location]}\n"
            info += f"- **Rotation** (Euler): {[round(x, 3) for x in obj.rotation_euler]}\n"
            info += f"- **Scale**: {[round(x, 3) for x in obj.scale]}\n"
            info += f"- **Dimensions**: {[round(x, 3) for x in obj.dimensions]}\n"

            # Hierarchy
            if obj.parent:
                info += f"- **Parent**: {obj.parent.name} ({obj.parent.type})\n"
                info += f"- **Parent Type**: {obj.parent_type}\n"

            if obj.children:
                info += f"- **Children** ({len(obj.children)}): {', '.join([c.name for c in obj.children])}\n"

            # Visibility
            info += f"- **Viewport Visible**: {not obj.hide_viewport}\n"
            info += f"- **Render Visible**: {not obj.hide_render}\n"
            info += f"- **Selectable**: {not obj.hide_select}\n"

            # Collections
            if obj.users_collection:
                info += f"- **Collections**: {', '.join([col.name for col in obj.users_collection])}\n"

            # Type-specific info (with null checks for obj.data)
            if obj.type == "MESH" and obj.data:
                mesh = obj.data
                info += f"\n**Mesh Data**: {mesh.name}\n"
                info += f"- Vertices: {len(mesh.vertices)}\n"
                info += f"- Edges: {len(mesh.edges)}\n"
                info += f"- Faces: {len(mesh.polygons)}\n"
                info += f"- UV Layers: {len(mesh.uv_layers)}\n"
                info += f"- Color Attributes: {len(mesh.color_attributes) if hasattr(mesh, 'color_attributes') else 0}\n"

                if mesh.materials:
                    info += f"\n**Materials** ({len(mesh.materials)}): {', '.join([mat.name if mat else '(empty)' for mat in mesh.materials])}\n"

            elif obj.type == "CAMERA" and obj.data:
                cam = obj.data
                info += f"\n**Camera Data**: {cam.name}\n"
                info += f"- Type: {cam.type}\n"
                info += f"- Focal Length: {cam.lens}mm\n"
                info += f"- Sensor Width: {cam.sensor_width}mm\n"
                info += f"- Sensor Height: {cam.sensor_height}mm\n"
                info += f"- Clip Start: {cam.clip_start}\n"
                info += f"- Clip End: {cam.clip_end}\n"
                # DOF may not exist on all camera types/versions
                if hasattr(cam, 'dof') and cam.dof and hasattr(cam.dof, 'focus_object'):
                    focus_obj = cam.dof.focus_object
                    info += f"- DOF Object: {focus_obj.name if focus_obj else 'None'}\n"

            elif obj.type == "LIGHT" and obj.data:
                light = obj.data
                info += f"\n**Light Data**: {light.name}\n"
                info += f"- Type: {light.type}\n"
                info += f"- Energy: {light.energy}\n"
                info += f"- Color: RGB{tuple(round(x, 3) for x in light.color)}\n"
                if light.type == "AREA":
                    info += f"- Shape: {light.shape}\n"
                    info += f"- Size: {light.size}\n"
                elif light.type in ["SPOT", "POINT"]:
                    info += f"- Shadow Soft Size: {light.shadow_soft_size}\n"

            elif obj.type == "CURVE" and obj.data:
                curve = obj.data
                info += f"\n**Curve Data**: {curve.name}\n"
                info += f"- Dimensions: {curve.dimensions}\n"
                info += f"- Resolution: {curve.resolution_u}\n"
                info += f"- Splines: {len(curve.splines)}\n"

            elif obj.type == "EMPTY":
                info += f"\n**Empty Type**: {obj.empty_display_type}\n"
                info += f"- Display Size: {obj.empty_display_size}\n"

            # Modifiers
            if obj.modifiers:
                info += f"\n**Modifiers** ({len(obj.modifiers)}):\n"
                for mod in obj.modifiers:
                    info += f"  - {mod.name} ({mod.type})"
                    if not mod.show_viewport:
                        info += " [Hidden in Viewport]"
                    if not mod.show_render:
                        info += " [Hidden in Render]"
                    info += "\n"

                    # Add relevant modifier settings
                    if mod.type == "SUBSURF":
                        info += f"    - Levels Viewport: {mod.levels}, Render: {mod.render_levels}\n"
                    elif mod.type == "ARRAY":
                        info += f"    - Count: {mod.count}\n"
                    elif mod.type == "MIRROR":
                        info += f"    - Axis: X={mod.use_axis[0]}, Y={mod.use_axis[1]}, Z={mod.use_axis[2]}\n"
                    elif mod.type == "SOLIDIFY":
                        info += f"    - Thickness: {mod.thickness}\n"
                    elif mod.type == "BEVEL":
                        info += f"    - Width: {mod.width}\n"
                        info += f"    - Segments: {mod.segments}\n"

            # Constraints
            if obj.constraints:
                info += f"\n**Constraints** ({len(obj.constraints)}):\n"
                for con in obj.constraints:
                    info += f"  - {con.name} ({con.type})"
                    if con.mute:
                        info += " [Muted]"
                    info += "\n"

                    # Add target info if available
                    if hasattr(con, "target") and con.target:
                        info += f"    - Target: {con.target.name}\n"

            # Animation
            if obj.animation_data:
                if obj.animation_data.action:
                    action = obj.animation_data.action
                    info += "\n**Animation**:\n"
                    info += f"  - Action: {action.name}\n"
                    info += f"  - Frame Range: {int(action.frame_range[0])} - {int(action.frame_range[1])}\n"
                    info += f"  - FCurves: {len(action.fcurves)}\n"

                if obj.animation_data.nla_tracks:
                    info += f"  - NLA Tracks: {len(obj.animation_data.nla_tracks)}\n"

            # Custom properties
            custom_props = [key for key in obj.keys() if key != "_RNA_UI"]
            if custom_props:
                info += f"\n**Custom Properties**: {', '.join(custom_props)}\n"

            return info

        selected = bpy.context.selected_objects
        active = bpy.context.active_object
        mode = bpy.context.mode

        if not selected:
            return "# Selected Objects\n\nNo objects currently selected.\n\n**Current Mode**: " + mode

        # Check for too many selected objects
        total_selected = len(selected)
        if total_selected > MAX_SELECTED_OBJECTS:
            output = f"# Selected Objects ({total_selected:,} total)\n\n"
            output += f"**WARNING: Too many objects selected** - limit is {MAX_SELECTED_OBJECTS}\n\n"
            output += f"**Current Mode**: {mode}\n"
            output += f"**Active Object**: {active.name if active else 'None'}\n\n"
            output += "Detailed info disabled for performance.\n"
            output += "Use `blender_run_code` tool for custom queries on large selections.\n\n"
            output += "**Example:**\n```python\nimport bpy\n"
            output += "for obj in bpy.context.selected_objects[:10]:\n"
            output += "    print(f'{obj.name}: {obj.type}')\n```"
            return output

        else:
            output = f"# Selected Objects ({len(selected)} total)\n\n"
            output += f"**Current Mode**: {mode}\n\n"

            # Active object first
            if active and active in selected:
                output += f"## ACTIVE: {active.name}\n\n"
                output += _format_object_info(active)
                output += "\n---\n\n"

            # Other selected objects
            other_objects = [obj for obj in selected if obj != active]
            if other_objects:
                output += "## Other Selected Objects\n\n"
                for obj in other_objects:
                    output += f"### {obj.name}\n\n"
                    output += _format_object_info(obj)
                    output += "\n"

            return output

    except Exception as e:
        # Resource failed - return error as markdown string
        error_trace = traceback.format_exc()

        return f"""# Selected Objects - Error

**ERROR**: Failed to retrieve object information

**Exception Type**: {type(e).__name__}
**Error Message**: {str(e)}

## Traceback
```
{error_trace}
```

## Troubleshooting
- Check that objects exist in the scene
- Verify object data is not corrupted
- Try deselecting and reselecting objects
- Restart Blender if issues persist
"""
