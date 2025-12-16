"""
Shared utilities for resource modules.

Provides common helper functions used across multiple resource files.
"""


def format_socket_value(socket) -> str:
    """
    Format a node socket's default value for display.

    Handles various socket types (VALUE, INT, BOOLEAN, VECTOR, RGBA, STRING)
    and returns a human-readable string representation.

    Args:
        socket: A Blender node socket with potential default_value attribute

    Returns:
        str: Formatted string representation of the socket's default value,
             or "N/A" if no value is available
    """
    if not hasattr(socket, "default_value"):
        return "N/A"

    val = socket.default_value
    socket_type = socket.type

    if socket_type == "VALUE":
        return f"{val:.4f}"
    elif socket_type == "INT":
        return str(val)
    elif socket_type == "BOOLEAN":
        return str(val)
    elif socket_type == "VECTOR":
        return f"({val[0]:.3f}, {val[1]:.3f}, {val[2]:.3f})"
    elif socket_type == "RGBA":
        return f"RGBA({val[0]:.3f}, {val[1]:.3f}, {val[2]:.3f}, {val[3]:.3f})"
    elif socket_type == "STRING":
        return f'"{val}"'
    else:
        return str(val) if val is not None else "N/A"
