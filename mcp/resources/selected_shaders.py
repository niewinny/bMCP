"""
Shader Nodes Resource

Provides information about shader nodes.
"""

import traceback

import bpy

from ._internal.registry import resource
from ._internal.utils import format_socket_value


@resource
def selected_shaders() -> str:
    """
    Returns comprehensive information about shader nodes.
    """
    try:
        # Node type descriptions for context
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
            "MAP_RANGE": "Remaps value range (From → To)",
            "RGBTOBW": "Color → Grayscale",
            "SEPRGB": "Splits RGB into R,G,B values",
            "COMBRGB": "Combines R,G,B into color",
        }

        # Socket type compatibility
        SOCKET_COMPAT = {
            "VALUE": "Float (accepts INT, BOOLEAN)",
            "INT": "Integer",
            "BOOLEAN": "True/False",
            "VECTOR": "XYZ coordinates",
            "RGBA": "Color (can accept VALUE for grayscale)",
            "SHADER": "Shader data (only connects to SHADER)",
        }

        active_obj = bpy.context.active_object

        if not active_obj:
            return "# Shader Nodes\n\nNo active object selected."

        # Check if object type can have materials
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

        else:
            node_tree = active_material.node_tree
            output = "# Shader Nodes\n\n"
            output += f"**Object**: {active_obj.name}\n"
            output += f"**Material**: {active_material.name}\n"

            # Material settings
            output += f"**Blend Mode**: {active_material.blend_method}\n"
            output += f"**Shadow Mode**: {active_material.shadow_method}\n"
            if active_material.blend_method in ["BLEND", "HASHED"]:
                output += f"**Show Backface**: {active_material.show_transparent_back}\n"
            output += "\n"

            # Socket compatibility guide
            output += "## Socket Type Guide\n\n"
            output += "**Connection Rules**: Sockets connect based on type compatibility:\n"
            for sock_type, desc in SOCKET_COMPAT.items():
                output += f"- **{sock_type}**: {desc}\n"
            output += "\n**Common Patterns**:\n"
            output += "- Texturing: `Texture Coordinate → Mapping → Image Texture → Principled BSDF`\n"
            output += "- Normal Maps: `Image Texture → Normal Map → Shader Normal input`\n"
            output += "- Mixing Shaders: `Noise/Image → ColorRamp → Mix Shader Fac`\n"
            output += "- Procedural Variation: `Noise → ColorRamp → Roughness/Metallic`\n\n"

            # Get all nodes
            all_nodes = list(node_tree.nodes)
            selected_nodes = [n for n in all_nodes if n.select]
            active_node = node_tree.nodes.active

            output += "## Shader Tree Overview\n\n"
            output += f"- **Total Nodes**: {len(all_nodes)}\n"
            output += f"- **Selected Nodes**: {len(selected_nodes)}\n"
            output += f"- **Active Node**: {active_node.name if active_node else 'None'}\n"
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

            # Output nodes
            output_nodes = [n for n in all_nodes if n.type == "OUTPUT_MATERIAL"]
            if output_nodes:
                output += "## Material Output Nodes\n\n"
                for out_node in output_nodes:
                    output += f"**{out_node.name}**"
                    if out_node.is_active_output:
                        output += " [ACTIVE OUTPUT]"
                    output += ":\n"

                    # Surface input
                    surface = out_node.inputs.get("Surface")
                    if surface and surface.is_linked and surface.links:
                        link = surface.links[0]
                        output += (
                            f"  - Surface ← {link.from_node.name} ({link.from_node.type})\n"
                        )

                    # Volume input
                    volume = out_node.inputs.get("Volume")
                    if volume and volume.is_linked and volume.links:
                        link = volume.links[0]
                        output += (
                            f"  - Volume ← {link.from_node.name} ({link.from_node.type})\n"
                        )

                    # Displacement input
                    displacement = out_node.inputs.get("Displacement")
                    if displacement and displacement.is_linked and displacement.links:
                        link = displacement.links[0]
                        output += f"  - Displacement ← {link.from_node.name} ({link.from_node.type})\n"

                output += "\n"

            # BSDF shaders
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

                    # Principled BSDF specific
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
                                    output += f"  - {input_name}: ← {link.from_node.name}\n"
                                else:
                                    output += (
                                        f"  - {input_name}: {format_socket_value(inp)}\n"
                                    )

                output += "\n"

            # Texture nodes
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

                    # Image texture specific
                    if tex.type == "TEX_IMAGE":
                        if tex.image:
                            output += f"  - Image: {tex.image.name}\n"
                            output += f"  - Size: {tex.image.size[0]}x{tex.image.size[1]}\n"
                            # colorspace_settings may not exist on all image types
                            if hasattr(tex.image, 'colorspace_settings') and tex.image.colorspace_settings:
                                output += f"  - Color Space: {tex.image.colorspace_settings.name}\n"
                        else:
                            output += "  - Image: (none)\n"
                        output += f"  - Interpolation: {tex.interpolation}\n"
                        output += f"  - Projection: {tex.projection}\n"

                output += "\n"

            # Active node details
            if active_node:
                output += f"## Active Node: {active_node.name}\n\n"
                output += f"- **Type**: {active_node.type}\n"
                output += (
                    f"- **Label**: {active_node.label if active_node.label else '(none)'}\n"
                )
                output += f"- **Location**: ({active_node.location.x:.1f}, {active_node.location.y:.1f})\n"

                if hasattr(active_node, "mute") and active_node.mute:
                    output += "- **Muted**: Yes\n"

                # Node group reference
                if active_node.type == "GROUP" and hasattr(active_node, 'node_tree'):
                    if active_node.node_tree:
                        output += f"- **Node Group**: {active_node.node_tree.name}\n"

                # Color Ramp
                if active_node.type == "VALTORGB":
                    output += (
                        f"- **Interpolation**: {active_node.color_ramp.interpolation}\n"
                    )
                    output += f"- **Color Mode**: {active_node.color_ramp.color_mode}\n"
                    output += f"- **Stops**: {len(active_node.color_ramp.elements)}\n"

                # Math node
                if active_node.type == "MATH":
                    output += f"- **Operation**: {active_node.operation}\n"
                    output += f"- **Clamp**: {active_node.use_clamp}\n"

                # Vector Math node
                if active_node.type == "VECT_MATH":
                    output += f"- **Operation**: {active_node.operation}\n"

                # Mix node
                if active_node.type == "MIX":
                    if hasattr(active_node, "data_type"):
                        output += f"- **Data Type**: {active_node.data_type}\n"
                    if hasattr(active_node, "blend_type"):
                        output += f"- **Blend Type**: {active_node.blend_type}\n"
                    if hasattr(active_node, "clamp_result"):
                        output += f"- **Clamp**: {active_node.clamp_result}\n"

                # Mapping node
                if active_node.type == "MAPPING":
                    output += f"- **Vector Type**: {active_node.vector_type}\n"

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
                                output += (
                                    f"    ← {link.from_node.name}.{link.from_socket.name}\n"
                                )

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

                    if node.type == "TEX_IMAGE" and node.image:
                        output += f"- Image: {node.image.name}\n"

                    output += "\n"

                if len(other_selected) > 8:
                    output += f"... and {len(other_selected) - 8} more selected nodes\n\n"

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

        return f"""# Selected Shaders - Error

**ERROR**: Failed to retrieve shader information

**Exception Type**: {type(e).__name__}
**Error Message**: {str(e)}

## Traceback
```
{error_trace}
```

## Troubleshooting
- Ensure you have an object with a material selected
- Check that the material uses nodes
- Verify shader nodes are not corrupted
- Try selecting a different material
- Restart Blender if issues persist
"""
