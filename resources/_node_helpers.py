"""
Shared helpers for node-editor resource modules.

Provides common formatting functions used by compositor, geometry nodes,
and shader node resources to avoid code duplication.
"""

from bmcp.resources._internal.utils import format_socket_value


def format_socket_guide(socket_types: dict, intro_line: str, patterns: list[str]) -> str:
    """
    Format the socket type guide section.

    Args:
        socket_types: Mapping of socket type name to description.
        intro_line: Bold intro text before the list.
        patterns: List of common pattern strings.
    """
    out = "## Socket Type Guide\n\n"
    out += f"**{intro_line}**:\n"
    for sock_type, desc in socket_types.items():
        out += f"- **{sock_type}**: {desc}\n"
    out += "\n**Common Patterns**:\n"
    for p in patterns:
        out += f"- {p}\n"
    out += "\n"
    return out


def format_overview(all_nodes, selected_nodes, active_node, links, heading: str) -> str:
    """
    Format the tree overview section (total, selected, active, links).

    Args:
        all_nodes: List of all nodes.
        selected_nodes: List of selected nodes.
        active_node: The active node (or None).
        links: The node_tree.links collection.
        heading: Section heading (e.g. "Compositor Overview").
    """
    out = f"## {heading}\n\n"
    out += f"- **Total Nodes**: {len(all_nodes)}\n"
    out += f"- **Selected Nodes**: {len(selected_nodes)}\n"
    out += f"- **Active Node**: {active_node.name if active_node else 'None'}\n"
    out += f"- **Links**: {len(links)}\n\n"
    return out


def format_node_type_stats(all_nodes, node_purposes: dict, limit: int | None = None) -> str:
    """
    Format node type statistics with purpose descriptions.

    Args:
        all_nodes: List of all nodes.
        node_purposes: Mapping of node type to purpose description.
        limit: Max types to show (None for all).
    """
    node_types: dict[str, int] = {}
    for node in all_nodes:
        node_types[node.type] = node_types.get(node.type, 0) + 1

    out = "**Node Types** (with purposes):\n"
    sorted_types = sorted(node_types.items(), key=lambda x: x[1], reverse=True)
    if limit is not None:
        sorted_types = sorted_types[:limit]
    for ntype, count in sorted_types:
        purpose = node_purposes.get(ntype, "See Blender docs")
        out += f"  - {ntype} ({count}x): {purpose}\n"
    out += "\n"
    return out


def format_active_node_base(active_node, *, group_label: str = "Node Group") -> str:
    """
    Format common active node properties (type, label, location, mute, group).

    Args:
        active_node: The active node.
        group_label: Label for the node group reference line.
    """
    out = f"## Active Node: {active_node.name}\n\n"
    out += f"- **Type**: {active_node.type}\n"
    out += f"- **Label**: {active_node.label if active_node.label else '(none)'}\n"
    out += f"- **Location**: ({active_node.location.x:.1f}, {active_node.location.y:.1f})\n"

    if hasattr(active_node, "mute") and active_node.mute:
        out += "- **Muted**: Yes\n"

    if active_node.type == "GROUP":
        if active_node.node_tree:
            out += f"- **{group_label}**: {active_node.node_tree.name}\n"

    return out


def format_active_node_inputs(active_node, *, skip_empty_names: bool = False) -> str:
    """
    Format the inputs section of the active node.

    Args:
        active_node: The active node.
        skip_empty_names: If True, skip sockets with empty names.
    """
    if not active_node.inputs:
        return ""

    out = "\n**Inputs**:\n"
    for inp in active_node.inputs:
        if skip_empty_names and inp.name == "":
            continue
        link_status = (
            "LINKED"
            if inp.is_linked
            else f"Value: {format_socket_value(inp)}"
        )
        out += f"  - {inp.name} ({inp.type}): {link_status}\n"
        if inp.is_linked:
            for link in inp.links:
                out += f"    \u2190 {link.from_node.name}.{link.from_socket.name}\n"
    return out


def format_active_node_outputs(active_node, *, skip_empty_names: bool = False) -> str:
    """
    Format the outputs section of the active node.

    Args:
        active_node: The active node.
        skip_empty_names: If True, skip sockets with empty names.
    """
    if not active_node.outputs:
        return ""

    out = "\n**Outputs**:\n"
    for socket_out in active_node.outputs:
        if skip_empty_names and socket_out.name == "":
            continue
        link_count = len(socket_out.links)
        out += f"  - {socket_out.name} ({socket_out.type}): {link_count} connection(s)\n"
        if socket_out.is_linked and socket_out.links:
            for link in socket_out.links[:3]:
                out += f"    \u2192 {link.to_node.name}.{link.to_socket.name}\n"
            if link_count > 3:
                out += f"    ... and {link_count - 3} more\n"
    return out


def format_node_groups_used(all_nodes, *, show_instance_names: bool = False) -> str:
    """
    Format the node groups used section.

    Args:
        all_nodes: List of all nodes.
        show_instance_names: If True, list instance names for groups with <= 3 instances.
    """
    node_groups = [n for n in all_nodes if n.type == "GROUP"]
    if not node_groups:
        return ""

    unique_groups: dict[str, list[str]] = {}
    for ng in node_groups:
        if ng.node_tree:
            group_name = ng.node_tree.name
            if group_name not in unique_groups:
                unique_groups[group_name] = []
            unique_groups[group_name].append(ng.name)

    out = f"## Node Groups Used ({len(node_groups)} instances)\n\n"
    for group_name, instances in unique_groups.items():
        out += f"- **{group_name}**: {len(instances)} instance(s)\n"
        if show_instance_names and len(instances) <= 3:
            out += f"  - {', '.join(instances)}\n"
    return out
