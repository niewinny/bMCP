"""
Geometry Nodes Resource

Provides information about geometry nodes.
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

SOCKET_PATTERNS = [
    "Scattering: `Grid \u2192 Mesh to Points \u2192 Instance on Points (with objects)`",
    "Displacement: `Grid \u2192 Set Position (Offset = Noise Texture)`",
    "Randomization: `Random Value \u2192 Scale/Rotation of instances`",
    "Selection: `BOOLEAN field \u2192 Selection input (True = affected)`",
]


@resource
@resource_error_handler("Geometry Nodes", [
    "Ensure you have an object with a Geometry Nodes modifier selected",
    "Check that the modifier has a node group assigned",
    "Verify the node tree is not corrupted",
    "Try selecting a different object",
    "Restart Blender if issues persist",
])
def selected_geometry_nodes() -> str:
    """
    Returns comprehensive information about geometry nodes.
    """
    active_obj = bpy.context.active_object

    if not active_obj:
        return "# Geometry Nodes\n\nNo active object selected."

    geo_mod = None
    for mod in active_obj.modifiers:
        if mod.type == "NODES":
            geo_mod = mod
            break

    if not geo_mod:
        return f"# Geometry Nodes\n\n**Object**: {active_obj.name}\n\nNo Geometry Nodes modifier found on this object."
    elif not geo_mod.node_group:
        return f"# Geometry Nodes\n\n**Object**: {active_obj.name}\n**Modifier**: {geo_mod.name}\n\nGeometry Nodes modifier has no node group assigned."

    node_tree = geo_mod.node_group
    output = "# Geometry Nodes\n\n"
    output += f"**Object**: {active_obj.name}\n"
    output += f"**Modifier**: {geo_mod.name}\n"
    output += f"**Node Group**: {node_tree.name}\n\n"

    output += format_socket_guide(
        SOCKET_TYPES,
        "GeoNodes uses 'fields' - values that can vary per element (vertex/face/point)",
        SOCKET_PATTERNS,
    )

    all_nodes = list(node_tree.nodes)
    selected_nodes = [n for n in all_nodes if n.select]
    active_node = node_tree.nodes.active

    output += format_overview(
        all_nodes, selected_nodes, active_node, node_tree.links,
        "Node Group Overview",
    )
    output += format_node_type_stats(all_nodes, NODE_PURPOSES, limit=15)

    input_nodes = [n for n in all_nodes if n.type == "GROUP_INPUT"]
    output_nodes = [n for n in all_nodes if n.type == "GROUP_OUTPUT"]

    if input_nodes:
        output += "## Group Inputs\n\n"
        for inp_node in input_nodes:
            output += f"**{inp_node.name}**:\n"
            for out_socket in inp_node.outputs:
                if out_socket.name != "":
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
                if inp_socket.name != "":
                    link_status = (
                        "LINKED" if inp_socket.is_linked else "Not connected"
                    )
                    output += f"  - {inp_socket.name} ({inp_socket.type}): {link_status}\n"
            output += "\n"

    if active_node:
        output += format_active_node_base(
            active_node, group_label="References Node Group",
        )
        output += format_active_node_inputs(active_node, skip_empty_names=True)
        output += format_active_node_outputs(active_node, skip_empty_names=True)
        output += "\n"

    other_selected = [n for n in selected_nodes if n != active_node]
    if other_selected:
        output += f"## Other Selected Nodes ({len(other_selected)})\n\n"
        for node in other_selected[:8]:
            output += f"### {node.name}\n"
            output += f"- **Type**: {node.type}\n"

            if node.type == "GROUP" and node.node_tree:
                output += f"- **Node Group**: {node.node_tree.name}\n"

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

    output += format_node_groups_used(all_nodes, show_instance_names=True)

    return output
