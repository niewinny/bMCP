"""
Blender-specific MCP resources.

Importing this module triggers registration of Blender resources via decorators.
"""

import functools
import traceback


def resource_error_handler(title, troubleshooting_tips):
    """Decorator that wraps a resource function with standard error handling.

    On exception, returns a formatted markdown error block instead of raising.

    Args:
        title: Display name for the resource (e.g. "Compositor").
        troubleshooting_tips: List of troubleshooting bullet points.
    """

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                error_trace = traceback.format_exc()
                tips = "\n".join(f"- {tip}" for tip in troubleshooting_tips)
                return (
                    f"# {title} - Error\n\n"
                    f"**ERROR**: Failed to retrieve {title.lower()} information\n\n"
                    f"**Exception Type**: {type(e).__name__}\n"
                    f"**Error Message**: {e}\n\n"
                    f"## Traceback\n```\n{error_trace}```\n\n"
                    f"## Troubleshooting\n{tips}\n"
                )

        return wrapper

    return decorator


from . import (  # noqa: F401, E402
    active_scene,
    selected_compositor,
    selected_geometry_nodes,
    selected_mesh,
    selected_objects,
    selected_shaders,
)
