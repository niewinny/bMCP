"""
Compositor Nodes Resource

Provides information about compositor nodes.
"""

import bpy

from bmcp import resource

from . import resource_error_handler
from ._node_helpers import (
    format_active_node_base,
    format_active_node_inputs,
    format_active_node_outputs,
    format_node_groups_used,
    format_node_type_stats,
    format_overview,
    format_socket_guide,
)

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

SOCKET_TYPES = {
    "RGBA": "Image/Color data",
    "VALUE": "Grayscale/numeric value",
    "VECTOR": "XYZ data (motion vectors, normals)",
}

SOCKET_PATTERNS = [
    "Basic Comp: `Render Layers \u2192 Color Correction \u2192 Composite`",
    "Glow Effect: `Image \u2192 Blur \u2192 Glare \u2192 Mix (Add mode) with original`",
    "Depth of Field: `Render Layers \u2192 Blur (size from Depth) \u2192 Composite`",
    "Masking: `ID Mask \u2192 ColorRamp \u2192 Mix RGB Fac (to isolate objects)`",
]


@resource
@resource_error_handler("Compositor", [
    "Check that compositor nodes are enabled for the scene",
    "Verify the scene is not corrupted",
    "Try creating a new scene",
    "Restart Blender if issues persist",
])
def selected_compositor() -> str:
    """
    Returns comprehensive information about compositor nodes.
    """
    scene = bpy.context.scene

    if not scene.use_nodes:
        return f"# Compositor\n\n**Scene**: {scene.name}\n\nCompositor nodes are not enabled for this scene.\n\nEnable in: Scene Properties \u2192 Compositor \u2192 Use Nodes"

    node_tree = scene.node_tree
    output = "# Compositor\n\n"
    output += f"**Scene**: {scene.name}\n"

    # Render settings context
    output += f"**Resolution**: {scene.render.resolution_x}x{scene.render.resolution_y}\n"
    output += f"**Frame Range**: {scene.frame_start} - {scene.frame_end}\n"
    output += f"**Current Frame**: {scene.frame_current}\n\n"

    output += format_socket_guide(
        SOCKET_TYPES,
        "Compositing works with image data and render passes",
        SOCKET_PATTERNS,
    )

    # Get all nodes
    all_nodes = list(node_tree.nodes)
    selected_nodes = [n for n in all_nodes if n.select]
    active_node = node_tree.nodes.active

    output += format_overview(
        all_nodes, selected_nodes, active_node, node_tree.links,
        "Compositor Overview",
    )
    output += format_node_type_stats(all_nodes, NODE_PURPOSES)

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

            image_input = comp_node.inputs.get("Image")
            if image_input and image_input.is_linked and image_input.links:
                link = image_input.links[0]
                output += f"  - Image \u2190 {link.from_node.name}.{link.from_socket.name}\n"

            alpha_input = comp_node.inputs.get("Alpha")
            if alpha_input and alpha_input.is_linked and alpha_input.links:
                link = alpha_input.links[0]
                output += f"  - Alpha \u2190 {link.from_node.name}.{link.from_socket.name}\n"

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

            if fo_node.file_slots:
                output += f"  - File Slots ({len(fo_node.file_slots)}): {', '.join([slot.path for slot in fo_node.file_slots])}\n"

        output += "\n"

    # Active node details
    if active_node:
        output += format_active_node_base(active_node)

        # Compositor-specific active node attributes
        if active_node.type == "BLUR":
            output += f"- **Filter Type**: {active_node.filter_type}\n"
            output += f"- **Use Relative**: {active_node.use_relative}\n"

        if active_node.type == "COLORCORRECTION":
            output += f"- **Highlights**: {active_node.highlights}\n"
            output += f"- **Midtones**: {active_node.midtones}\n"
            output += f"- **Shadows**: {active_node.shadows}\n"

        if active_node.type == "GLARE":
            output += f"- **Glare Type**: {active_node.glare_type}\n"
            output += f"- **Quality**: {active_node.quality}\n"

        if active_node.type == "MIX_RGB" or active_node.type == "MIX":
            if hasattr(active_node, "blend_type"):
                output += f"- **Blend Type**: {active_node.blend_type}\n"
            if hasattr(active_node, "use_clamp"):
                output += f"- **Clamp**: {active_node.use_clamp}\n"

        if active_node.type == "VALTORGB":
            output += (
                f"- **Interpolation**: {active_node.color_ramp.interpolation}\n"
            )
            output += f"- **Stops**: {len(active_node.color_ramp.elements)}\n"

        if active_node.type == "SCALE":
            output += f"- **Space**: {active_node.space}\n"

        if active_node.type == "TRANSFORM":
            output += f"- **Filter**: {active_node.filter_type}\n"

        if active_node.type == "IMAGE":
            if active_node.image:
                output += f"- **Image**: {active_node.image.name}\n"
                output += f"  - Size: {active_node.image.size[0]}x{active_node.image.size[1]}\n"
                output += f"  - Source: {active_node.image.source}\n"

        output += format_active_node_inputs(active_node)
        output += format_active_node_outputs(active_node)
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

    output += format_node_groups_used(all_nodes)

    return output
