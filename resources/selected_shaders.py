"""
Shader Nodes Resource

Provides information about shader nodes.
"""

import bpy

from bmcp import resource
from bmcp.resources._internal.utils import format_socket_value

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
    "BSDF_PRINCIPLED": "PBR shader (Metallic=0-1, Roughness=0-1) - main shader",
    "BSDF_DIFFUSE": "Matte/diffuse - scatters light evenly",
    "BSDF_GLOSSY": "Reflective/mirror-like surface",
    "BSDF_GLASS": "Transparent glass (refraction+reflection)",
    "EMISSION": "Emits light (glowing)",
    "MIX_SHADER": "Blends two shaders (Fac 0-1)",
    "ADD_SHADER": "Adds two shaders together",
    "TEX_IMAGE": "Loads image texture",
    "TEX_NOISE": "Procedural noise pattern",
    "TEX_VORONOI": "Cellular/Voronoi pattern",
    "VALTORGB": "ColorRamp - maps value to color gradient",
    "MIX": "Mixes colors/values with blend modes",
    "MAPPING": "Transforms UV coords (location/rotation/scale)",
    "TEX_COORD": "Provides UV coordinates (Generated/UV/Object)",
    "NORMAL_MAP": "Converts RGB image to normal vector",
    "BUMP": "Fake surface detail from height map",
    "MATH": "Math operations (Add/Multiply/Power/etc)",
    "MAP_RANGE": "Remaps value range (From \u2192 To)",
    "RGBTOBW": "Color \u2192 Grayscale",
    "SEPRGB": "Splits RGB into R,G,B values",
    "COMBRGB": "Combines R,G,B into color",
}

SOCKET_COMPAT = {
    "VALUE": "Float (accepts INT, BOOLEAN)",
    "INT": "Integer",
    "BOOLEAN": "True/False",
    "VECTOR": "XYZ coordinates",
    "RGBA": "Color (can accept VALUE for grayscale)",
    "SHADER": "Shader data (only connects to SHADER)",
}

SOCKET_PATTERNS = [
    "Texturing: `Texture Coordinate \u2192 Mapping \u2192 Image Texture \u2192 Principled BSDF`",
    "Normal Maps: `Image Texture \u2192 Normal Map \u2192 Shader Normal input`",
    "Mixing Shaders: `Noise/Image \u2192 ColorRamp \u2192 Mix Shader Fac`",
    "Procedural Variation: `Noise \u2192 ColorRamp \u2192 Roughness/Metallic`",
]


@resource
@resource_error_handler("Selected Shaders", [
    "Ensure you have an object with a material selected",
    "Check that the material uses nodes",
    "Verify shader nodes are not corrupted",
    "Try selecting a different material",
    "Restart Blender if issues persist",
])
def selected_shaders() -> str:
    """
    Returns comprehensive information about shader nodes.
    """
    active_obj = bpy.context.active_object

    if not active_obj:
        return "# Shader Nodes\n\nNo active object selected."

    if active_obj.type not in [
        "MESH",
        "CURVE",
        "SURFACE",
        "FONT",
        "META",
        "VOLUME",
        "GPENCIL",
    ]:
        return f"# Shader Nodes\n\n**Object**: {active_obj.name}\n**Type**: {active_obj.type}\n\nThis object type doesn't support materials."

    active_material = active_obj.active_material

    if not active_material:
        mat_count = len(active_obj.material_slots)
        return f"# Shader Nodes\n\n**Object**: {active_obj.name}\n**Material Slots**: {mat_count}\n\nNo active material assigned."
    elif not active_material.use_nodes:
        return f"# Shader Nodes\n\n**Object**: {active_obj.name}\n**Material**: {active_material.name}\n\nMaterial doesn't use nodes (legacy material system)."

    node_tree = active_material.node_tree
    output = "# Shader Nodes\n\n"
    output += f"**Object**: {active_obj.name}\n"
    output += f"**Material**: {active_material.name}\n"

    # Material settings (blend_method/shadow_method removed in Blender 4.2+ with EEVEE-Next)
    if hasattr(active_material, "blend_method"):
        output += f"**Blend Mode**: {active_material.blend_method}\n"
        output += f"**Shadow Mode**: {active_material.shadow_method}\n"
        if active_material.blend_method in ["BLEND", "HASHED"]:
            output += (
                f"**Show Backface**: {active_material.show_transparent_back}\n"
            )
    output += "\n"

    output += format_socket_guide(
        SOCKET_COMPAT,
        "Connection Rules: Sockets connect based on type compatibility",
        SOCKET_PATTERNS,
    )

    all_nodes = list(node_tree.nodes)
    selected_nodes = [n for n in all_nodes if n.select]
    active_node = node_tree.nodes.active

    output += format_overview(
        all_nodes, selected_nodes, active_node, node_tree.links,
        "Shader Tree Overview",
    )
    output += format_node_type_stats(all_nodes, NODE_PURPOSES)

    output_nodes = [n for n in all_nodes if n.type == "OUTPUT_MATERIAL"]
    if output_nodes:
        output += "## Material Output Nodes\n\n"
        for out_node in output_nodes:
            output += f"**{out_node.name}**"
            if out_node.is_active_output:
                output += " [ACTIVE OUTPUT]"
            output += ":\n"

            surface = out_node.inputs.get("Surface")
            if surface and surface.is_linked and surface.links:
                link = surface.links[0]
                output += f"  - Surface \u2190 {link.from_node.name} ({link.from_node.type})\n"

            volume = out_node.inputs.get("Volume")
            if volume and volume.is_linked and volume.links:
                link = volume.links[0]
                output += f"  - Volume \u2190 {link.from_node.name} ({link.from_node.type})\n"

            displacement = out_node.inputs.get("Displacement")
            if displacement and displacement.is_linked and displacement.links:
                link = displacement.links[0]
                output += f"  - Displacement \u2190 {link.from_node.name} ({link.from_node.type})\n"

        output += "\n"

    bsdf_nodes = [n for n in all_nodes if "BSDF" in n.type]
    if bsdf_nodes:
        output += f"## BSDF Shader Nodes ({len(bsdf_nodes)})\n\n"
        for bsdf in bsdf_nodes:
            output += f"**{bsdf.name}** ({bsdf.type})"
            if bsdf == active_node:
                output += " [ACTIVE]"
            if bsdf.select:
                output += " [SELECTED]"
            output += "\n"

            if bsdf.type == "BSDF_PRINCIPLED":
                key_inputs = [
                    "Base Color",
                    "Metallic",
                    "Roughness",
                    "IOR",
                    "Alpha",
                    "Emission Color",
                    "Emission Strength",
                ]
                for input_name in key_inputs:
                    inp = bsdf.inputs.get(input_name)
                    if inp:
                        if inp.is_linked and inp.links:
                            link = inp.links[0]
                            output += (
                                f"  - {input_name}: \u2190 {link.from_node.name}\n"
                            )
                        else:
                            output += f"  - {input_name}: {format_socket_value(inp)}\n"

        output += "\n"

    texture_nodes = [n for n in all_nodes if n.type.startswith("TEX_")]
    if texture_nodes:
        output += f"## Texture Nodes ({len(texture_nodes)})\n\n"
        for tex in texture_nodes:
            output += f"**{tex.name}** ({tex.type})"
            if tex == active_node:
                output += " [ACTIVE]"
            if tex.select:
                output += " [SELECTED]"
            output += "\n"

            if tex.type == "TEX_IMAGE":
                if tex.image:
                    output += f"  - Image: {tex.image.name}\n"
                    output += (
                        f"  - Size: {tex.image.size[0]}x{tex.image.size[1]}\n"
                    )
                    if (
                        hasattr(tex.image, "colorspace_settings")
                        and tex.image.colorspace_settings
                    ):
                        output += f"  - Color Space: {tex.image.colorspace_settings.name}\n"
                else:
                    output += "  - Image: (none)\n"
                output += f"  - Interpolation: {tex.interpolation}\n"
                output += f"  - Projection: {tex.projection}\n"

        output += "\n"

    if active_node:
        output += format_active_node_base(active_node)

        if active_node.type == "VALTORGB":
            output += (
                f"- **Interpolation**: {active_node.color_ramp.interpolation}\n"
            )
            output += f"- **Color Mode**: {active_node.color_ramp.color_mode}\n"
            output += f"- **Stops**: {len(active_node.color_ramp.elements)}\n"

        if active_node.type == "MATH":
            output += f"- **Operation**: {active_node.operation}\n"
            output += f"- **Clamp**: {active_node.use_clamp}\n"

        if active_node.type == "VECT_MATH":
            output += f"- **Operation**: {active_node.operation}\n"

        if active_node.type == "MIX":
            if hasattr(active_node, "data_type"):
                output += f"- **Data Type**: {active_node.data_type}\n"
            if hasattr(active_node, "blend_type"):
                output += f"- **Blend Type**: {active_node.blend_type}\n"
            if hasattr(active_node, "clamp_result"):
                output += f"- **Clamp**: {active_node.clamp_result}\n"

        if active_node.type == "MAPPING":
            output += f"- **Vector Type**: {active_node.vector_type}\n"

        output += format_active_node_inputs(active_node)
        output += format_active_node_outputs(active_node)
        output += "\n"

    other_selected = [n for n in selected_nodes if n != active_node]
    if other_selected:
        output += f"## Other Selected Nodes ({len(other_selected)})\n\n"
        for node in other_selected[:8]:
            output += f"### {node.name} ({node.type})\n"

            if node.type == "GROUP" and node.node_tree:
                output += f"- Node Group: {node.node_tree.name}\n"

            if node.type == "TEX_IMAGE" and node.image:
                output += f"- Image: {node.image.name}\n"

            output += "\n"

        if len(other_selected) > 8:
            output += (
                f"... and {len(other_selected) - 8} more selected nodes\n\n"
            )

    output += format_node_groups_used(all_nodes)

    return output
