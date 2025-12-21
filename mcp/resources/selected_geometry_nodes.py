"""
Geometry Nodes Resource

Provides information about geometry nodes.
"""

import traceback

import bpy

from ._internal.registry import resource
from ._internal.utils import format_socket_value


@resource
def selected_geometry_nodes() -> str:
    """
    Returns comprehensive information about geometry nodes.
    """
    try:
        # Node type purposes for Geometry Nodes
        NODE_PURPOSES = {
            "GROUP_INPUT": "Modifier inputs - parameters visible in modifier panel",
            "GROUP_OUTPUT": "Final geometry output",
            "JOIN_GEOMETRY": "Combines multiple geometries into one",
            "TRANSFORM_GEOMETRY": "Moves/rotates/scales geometry",
            "SET_POSITION": "Moves vertices (use for displacement)",
            "MESH_PRIMITIVE_CUBE": "Creates cube mesh",
            "MESH_PRIMITIVE_UV_SPHERE": "Creates UV sphere",
            "MESH_PRIMITIVE_GRID": "Creates flat grid/plane",
            "INSTANCE_ON_POINTS": "Copies geometry onto points (scattering)",
            "REALIZE_INSTANCES": "Converts instances to real geometry",
            "MESH_TO_POINTS": "Converts mesh vertices to points",
            "SUBDIVIDE_MESH": "Adds more geometry detail",
            "EXTRUDE_MESH": "Extrudes faces outward",
            "STORE_NAMED_ATTRIBUTE": "Saves data to geometry (colors, IDs)",
            "MATH": "Math operations on values/fields",
            "RANDOM_VALUE": "Random values per element",
            "NOISE_TEXTURE": "Procedural noise (for displacement/variation)",
        }

        # Socket types in Geometry Nodes
        SOCKET_TYPES = {
            "GEOMETRY": "Mesh/curve/points data",
            "VALUE": "Float number (can be per-element field)",
            "INT": "Integer number",
            "BOOLEAN": "True/False (can be selection mask)",
            "VECTOR": "XYZ coordinates (can be per-vertex)",
            "RGBA": "Color data",
            "STRING": "Text",
            "OBJECT": "Reference to Blender object",
            "COLLECTION": "Reference to collection",
        }

        active_obj = bpy.context.active_object

        if not active_obj:
            return "# Geometry Nodes\n\nNo active object selected."

        # Find geometry nodes modifier
        geo_mod = None
        for mod in active_obj.modifiers:
            if mod.type == "NODES":
                geo_mod = mod
                break

        if not geo_mod:
            return f"# Geometry Nodes\n\n**Object**: {active_obj.name}\n\nNo Geometry Nodes modifier found on this object."
        elif not geo_mod.node_group:
            return f"# Geometry Nodes\n\n**Object**: {active_obj.name}\n**Modifier**: {geo_mod.name}\n\nGeometry Nodes modifier has no node group assigned."

        else:
            node_tree = geo_mod.node_group
            output = "# Geometry Nodes\n\n"
            output += f"**Object**: {active_obj.name}\n"
            output += f"**Modifier**: {geo_mod.name}\n"
            output += f"**Node Group**: {node_tree.name}\n\n"

            # Socket types guide
            output += "## Socket Type Guide\n\n"
            output += "**GeoNodes uses 'fields'** - values that can vary per element (vertex/face/point):\n"
            for sock_type, desc in SOCKET_TYPES.items():
                output += f"- **{sock_type}**: {desc}\n"
            output += "\n**Common Patterns**:\n"
            output += "- Scattering: `Grid → Mesh to Points → Instance on Points (with objects)`\n"
            output += "- Displacement: `Grid → Set Position (Offset = Noise Texture)`\n"
            output += "- Randomization: `Random Value → Scale/Rotation of instances`\n"
            output += (
                "- Selection: `BOOLEAN field → Selection input (True = affected)`\n\n"
            )

            # Get all nodes
            all_nodes = list(node_tree.nodes)
            selected_nodes = [n for n in all_nodes if n.select]
            active_node = node_tree.nodes.active

            output += "## Node Group Overview\n\n"
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
            )[:15]:
                purpose = NODE_PURPOSES.get(ntype, "See Blender docs")
                output += f"  - {ntype} ({count}x): {purpose}\n"
            output += "\n"

            # Group Input/Output nodes
            input_nodes = [n for n in all_nodes if n.type == "GROUP_INPUT"]
            output_nodes = [n for n in all_nodes if n.type == "GROUP_OUTPUT"]

            if input_nodes:
                output += "## Group Inputs\n\n"
                for inp_node in input_nodes:
                    output += f"**{inp_node.name}**:\n"
                    for out_socket in inp_node.outputs:
                        if out_socket.name != "":  # Skip empty sockets
                            link_count = len(out_socket.links)
                            output += f"  - {out_socket.name} ({out_socket.type}): {link_count} connection(s)\n"
                output += "\n"

            if output_nodes:
                output += "## Group Outputs\n\n"
                for out_node in output_nodes:
                    output += f"**{out_node.name}**"
                    if out_node == active_node:
                        output += " [ACTIVE]"
                    output += ":\n"
                    for inp_socket in out_node.inputs:
                        if inp_socket.name != "":  # Skip empty sockets
                            link_status = (
                                "LINKED" if inp_socket.is_linked else "Not connected"
                            )
                            output += f"  - {inp_socket.name} ({inp_socket.type}): {link_status}\n"
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
                        output += f"- **References Node Group**: {active_node.node_tree.name}\n"

                # Inputs
                if active_node.inputs:
                    output += "\n**Inputs**:\n"
                    for inp in active_node.inputs:
                        if inp.name != "":
                            link_status = (
                                "LINKED"
                                if inp.is_linked
                                else f"Value: {format_socket_value(inp)}"
                            )
                            output += f"  - {inp.name} ({inp.type}): {link_status}\n"
                            if inp.is_linked and inp.links:
                                for link in inp.links:
                                    output += f"    ← {link.from_node.name}.{link.from_socket.name}\n"

                # Outputs
                if active_node.outputs:
                    output += "\n**Outputs**:\n"
                    for out in active_node.outputs:
                        if out.name != "":
                            link_count = len(out.links)
                            output += f"  - {out.name} ({out.type}): {link_count} connection(s)\n"
                            if out.is_linked and out.links:
                                for link in out.links[:3]:  # First 3
                                    output += f"    → {link.to_node.name}.{link.to_socket.name}\n"
                                if link_count > 3:
                                    output += f"    ... and {link_count - 3} more\n"

                output += "\n"

            # Other selected nodes
            other_selected = [n for n in selected_nodes if n != active_node]
            if other_selected:
                output += f"## Other Selected Nodes ({len(other_selected)})\n\n"
                for node in other_selected[:8]:
                    output += f"### {node.name}\n"
                    output += f"- **Type**: {node.type}\n"

                    if node.type == "GROUP" and node.node_tree:
                        output += f"- **Node Group**: {node.node_tree.name}\n"

                    # Show key inputs/outputs
                    linked_inputs = [
                        inp for inp in node.inputs if inp.is_linked and inp.name != ""
                    ]
                    linked_outputs = [
                        out for out in node.outputs if out.is_linked and out.name != ""
                    ]

                    if linked_inputs:
                        output += f"- **Inputs**: {', '.join([inp.name for inp in linked_inputs[:5]])}\n"
                    if linked_outputs:
                        output += f"- **Outputs**: {', '.join([out.name for out in linked_outputs[:5]])}\n"

                    output += "\n"

                if len(other_selected) > 8:
                    output += (
                        f"... and {len(other_selected) - 8} more selected nodes\n\n"
                    )

            # Node groups used in tree
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
                    if len(instances) <= 3:
                        output += f"  - {', '.join(instances)}\n"

            return output

    except Exception as e:
        # Resource failed - return error as markdown string
        error_trace = traceback.format_exc()

        return f"""# Geometry Nodes - Error

**ERROR**: Failed to retrieve geometry nodes information

**Exception Type**: {type(e).__name__}
**Error Message**: {str(e)}

## Traceback
```
{error_trace}
```

## Troubleshooting
- Ensure you have an object with a Geometry Nodes modifier selected
- Check that the modifier has a node group assigned
- Verify the node tree is not corrupted
- Try selecting a different object
- Restart Blender if issues persist
"""
