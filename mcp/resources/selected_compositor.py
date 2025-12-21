"""
Compositor Nodes Resource

Provides information about compositor nodes.
"""

import traceback

import bpy

from ._internal.registry import resource
from ._internal.utils import format_socket_value


@resource
def selected_compositor() -> str:
    """
    Returns comprehensive information about compositor nodes.
    """
    try:
        # Node type purposes for Compositor
        NODE_PURPOSES = {
            "R_LAYERS": "Render input - provides rendered image and passes",
            "IMAGE": "Loads image file",
            "COMPOSITE": "Final output - what you see in render",
            "VIEWER": "Preview node - debug intermediate results",
            "OUTPUT_FILE": "Saves image to file",
            "MIX_RGB": "Mixes images with blend modes (Add/Multiply/etc)",
            "ALPHAOVER": "Composites images using alpha (layer stacking)",
            "VALTORGB": "ColorRamp - maps values to colors",
            "COLORCORRECTION": "Color grading (highlights/midtones/shadows)",
            "HUE_SAT": "Adjusts hue, saturation, value",
            "BRIGHTCONTRAST": "Brightness and contrast adjustment",
            "BLUR": "Blurs image (for DoF, glow, softening)",
            "GLARE": "Adds glare/bloom to bright areas",
            "DENOISE": "AI denoising for renders",
            "RGBTOBW": "Color to grayscale",
            "SEPARATE_RGBA": "Splits RGBA into separate channels",
            "COMBINE_RGBA": "Combines R,G,B,A into image",
            "SCALE": "Scales/resizes image",
            "TRANSFORM": "Moves/rotates/scales image",
            "KEYING": "Chroma key (green screen removal)",
            "ID_MASK": "Mask from Object/Material ID pass",
            "MATH": "Math operations on values",
        }

        # Socket types
        SOCKET_TYPES = {
            "RGBA": "Image/Color data",
            "VALUE": "Grayscale/numeric value",
            "VECTOR": "XYZ data (motion vectors, normals)",
        }

        scene = bpy.context.scene

        if not scene.use_nodes:
            return f"# Compositor\n\n**Scene**: {scene.name}\n\nCompositor nodes are not enabled for this scene.\n\nEnable in: Scene Properties → Compositor → Use Nodes"

        else:
            node_tree = scene.node_tree
            output = "# Compositor\n\n"
            output += f"**Scene**: {scene.name}\n"

            # Render settings context
            output += f"**Resolution**: {scene.render.resolution_x}x{scene.render.resolution_y}\n"
            output += f"**Frame Range**: {scene.frame_start} - {scene.frame_end}\n"
            output += f"**Current Frame**: {scene.frame_current}\n\n"

            # Socket types guide
            output += "## Socket Type Guide\n\n"
            output += "**Compositing works with image data and render passes**:\n"
            for sock_type, desc in SOCKET_TYPES.items():
                output += f"- **{sock_type}**: {desc}\n"
            output += "\n**Common Patterns**:\n"
            output += "- Basic Comp: `Render Layers → Color Correction → Composite`\n"
            output += (
                "- Glow Effect: `Image → Blur → Glare → Mix (Add mode) with original`\n"
            )
            output += "- Depth of Field: `Render Layers → Blur (size from Depth) → Composite`\n"
            output += "- Masking: `ID Mask → ColorRamp → Mix RGB Fac (to isolate objects)`\n\n"

            # Get all nodes
            all_nodes = list(node_tree.nodes)
            selected_nodes = [n for n in all_nodes if n.select]
            active_node = node_tree.nodes.active

            output += "## Compositor Overview\n\n"
            output += f"- **Total Nodes**: {len(all_nodes)}\n"
            output += f"- **Selected Nodes**: {len(selected_nodes)}\n"
            output += (
                f"- **Active Node**: {active_node.name if active_node else 'None'}\n"
            )
            output += f"- **Links**: {len(node_tree.links)}\n\n"

            # Node type statistics with purposes
            node_types = {}
            for node in all_nodes:
                node_types[node.type] = node_types.get(node.type, 0) + 1

            output += "**Node Types** (with purposes):\n"
            for ntype, count in sorted(
                node_types.items(), key=lambda x: x[1], reverse=True
            ):
                purpose = NODE_PURPOSES.get(ntype, "See Blender docs")
                output += f"  - {ntype} ({count}x): {purpose}\n"
            output += "\n"

            # Render Layers nodes (input)
            render_layer_nodes = [n for n in all_nodes if n.type == "R_LAYERS"]
            if render_layer_nodes:
                output += "## Render Layers Input Nodes\n\n"
                for rl_node in render_layer_nodes:
                    output += f"**{rl_node.name}**"
                    if rl_node == active_node:
                        output += " [ACTIVE]"
                    if rl_node.select:
                        output += " [SELECTED]"
                    output += ":\n"
                    output += f"  - Scene: {rl_node.scene.name if rl_node.scene else '(current)'}\n"
                    output += f"  - Layer: {rl_node.layer}\n"

                    # Show which outputs are being used
                    connected_outputs = [
                        out for out in rl_node.outputs if len(out.links) > 0
                    ]
                    if connected_outputs:
                        output += f"  - Connected Outputs ({len(connected_outputs)}): {', '.join([o.name for o in connected_outputs[:8]])}\n"

                output += "\n"

            # Composite output nodes
            composite_nodes = [n for n in all_nodes if n.type == "COMPOSITE"]
            if composite_nodes:
                output += "## Composite Output Nodes\n\n"
                for comp_node in composite_nodes:
                    output += f"**{comp_node.name}**"
                    if comp_node == active_node:
                        output += " [ACTIVE]"
                    output += ":\n"

                    # Image input
                    image_input = comp_node.inputs.get("Image")
                    if image_input and image_input.is_linked and image_input.links:
                        link = image_input.links[0]
                        output += f"  - Image ← {link.from_node.name}.{link.from_socket.name}\n"

                    # Alpha input
                    alpha_input = comp_node.inputs.get("Alpha")
                    if alpha_input and alpha_input.is_linked and alpha_input.links:
                        link = alpha_input.links[0]
                        output += f"  - Alpha ← {link.from_node.name}.{link.from_socket.name}\n"

                output += "\n"

            # Viewer nodes
            viewer_nodes = [n for n in all_nodes if n.type == "VIEWER"]
            if viewer_nodes:
                output += "## Viewer Nodes\n\n"
                for viewer in viewer_nodes:
                    output += f"**{viewer.name}**"
                    if viewer == active_node:
                        output += " [ACTIVE]"
                    if viewer.select:
                        output += " [SELECTED]"
                    output += "\n"

                    image_input = viewer.inputs.get("Image")
                    if image_input and image_input.is_linked and image_input.links:
                        link = image_input.links[0]
                        output += f"  - Viewing: {link.from_node.name}.{link.from_socket.name}\n"

                output += "\n"

            # File Output nodes
            file_output_nodes = [n for n in all_nodes if n.type == "OUTPUT_FILE"]
            if file_output_nodes:
                output += "## File Output Nodes\n\n"
                for fo_node in file_output_nodes:
                    output += f"**{fo_node.name}**"
                    if fo_node == active_node:
                        output += " [ACTIVE]"
                    if fo_node.select:
                        output += " [SELECTED]"
                    output += ":\n"
                    output += f"  - Base Path: {fo_node.base_path}\n"
                    output += f"  - Format: {fo_node.format.file_format}\n"

                    # File slots
                    if fo_node.file_slots:
                        output += f"  - File Slots ({len(fo_node.file_slots)}): {', '.join([slot.path for slot in fo_node.file_slots])}\n"

                output += "\n"

            # Active node details
            if active_node:
                output += f"## Active Node: {active_node.name}\n\n"
                output += f"- **Type**: {active_node.type}\n"
                output += f"- **Label**: {active_node.label if active_node.label else '(none)'}\n"
                output += f"- **Location**: ({active_node.location.x:.1f}, {active_node.location.y:.1f})\n"

                if hasattr(active_node, "mute") and active_node.mute:
                    output += "- **Muted**: Yes\n"

                # Node group reference
                if active_node.type == "GROUP":
                    if active_node.node_tree:
                        output += f"- **Node Group**: {active_node.node_tree.name}\n"

                # Blur node
                if active_node.type == "BLUR":
                    output += f"- **Filter Type**: {active_node.filter_type}\n"
                    output += f"- **Use Relative**: {active_node.use_relative}\n"

                # Color Correction
                if active_node.type == "COLORCORRECTION":
                    output += f"- **Highlights**: {active_node.highlights}\n"
                    output += f"- **Midtones**: {active_node.midtones}\n"
                    output += f"- **Shadows**: {active_node.shadows}\n"

                # Glare
                if active_node.type == "GLARE":
                    output += f"- **Glare Type**: {active_node.glare_type}\n"
                    output += f"- **Quality**: {active_node.quality}\n"

                # Mix (Color Mix)
                if active_node.type == "MIX_RGB" or active_node.type == "MIX":
                    if hasattr(active_node, "blend_type"):
                        output += f"- **Blend Type**: {active_node.blend_type}\n"
                    if hasattr(active_node, "use_clamp"):
                        output += f"- **Clamp**: {active_node.use_clamp}\n"

                # Color Ramp
                if active_node.type == "VALTORGB":
                    output += (
                        f"- **Interpolation**: {active_node.color_ramp.interpolation}\n"
                    )
                    output += f"- **Stops**: {len(active_node.color_ramp.elements)}\n"

                # Scale
                if active_node.type == "SCALE":
                    output += f"- **Space**: {active_node.space}\n"

                # Transform
                if active_node.type == "TRANSFORM":
                    output += f"- **Filter**: {active_node.filter_type}\n"

                # Image node
                if active_node.type == "IMAGE":
                    if active_node.image:
                        output += f"- **Image**: {active_node.image.name}\n"
                        output += f"  - Size: {active_node.image.size[0]}x{active_node.image.size[1]}\n"
                        output += f"  - Source: {active_node.image.source}\n"

                # Inputs
                if active_node.inputs:
                    output += "\n**Inputs**:\n"
                    for inp in active_node.inputs:
                        link_status = (
                            "LINKED"
                            if inp.is_linked
                            else f"Value: {format_socket_value(inp)}"
                        )
                        output += f"  - {inp.name} ({inp.type}): {link_status}\n"
                        if inp.is_linked:
                            for link in inp.links:
                                output += f"    ← {link.from_node.name}.{link.from_socket.name}\n"

                # Outputs
                if active_node.outputs:
                    output += "\n**Outputs**:\n"
                    for out in active_node.outputs:
                        link_count = len(out.links)
                        output += (
                            f"  - {out.name} ({out.type}): {link_count} connection(s)\n"
                        )
                        if out.is_linked and out.links:
                            for link in out.links[:3]:
                                output += (
                                    f"    → {link.to_node.name}.{link.to_socket.name}\n"
                                )
                            if link_count > 3:
                                output += f"    ... and {link_count - 3} more\n"

                output += "\n"

            # Other selected nodes
            other_selected = [n for n in selected_nodes if n != active_node]
            if other_selected:
                output += f"## Other Selected Nodes ({len(other_selected)})\n\n"
                for node in other_selected[:8]:
                    output += f"### {node.name} ({node.type})\n"

                    if node.type == "GROUP" and node.node_tree:
                        output += f"- Node Group: {node.node_tree.name}\n"

                    if node.type == "IMAGE" and node.image:
                        output += f"- Image: {node.image.name}\n"

                    output += "\n"

                if len(other_selected) > 8:
                    output += (
                        f"... and {len(other_selected) - 8} more selected nodes\n\n"
                    )

            # Node groups used
            node_groups_used = [n for n in all_nodes if n.type == "GROUP"]
            if node_groups_used:
                unique_groups = {}
                for ng in node_groups_used:
                    if ng.node_tree:
                        group_name = ng.node_tree.name
                        if group_name not in unique_groups:
                            unique_groups[group_name] = []
                        unique_groups[group_name].append(ng.name)

                output += f"## Node Groups Used ({len(node_groups_used)} instances)\n\n"
                for group_name, instances in unique_groups.items():
                    output += f"- **{group_name}**: {len(instances)} instance(s)\n"

            return output

    except Exception as e:
        # Resource failed - return error as markdown string
        error_trace = traceback.format_exc()

        return f"""# Compositor - Error

**ERROR**: Failed to retrieve compositor information

**Exception Type**: {type(e).__name__}
**Error Message**: {str(e)}

## Traceback
```
{error_trace}
```

## Troubleshooting
- Check that compositor nodes are enabled for the scene
- Verify the scene is not corrupted
- Try creating a new scene
- Restart Blender if issues persist
"""
