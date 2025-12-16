"""
This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import sys

# Import public API (lazy-loading wrappers)
from .api import (
    is_running,
    is_shutting_down,
    iter_prompts,
    iter_resources,
    iter_tools,
    prompt,
    resource,
    start_server,
    stop_server,
    tool,
    wait_shutdown,
)

# Alias module name to allow `from bmcp import tool, resource`
sys.modules.setdefault("bmcp", sys.modules[__name__])


def register():
    """Register Blender addon classes."""
    # Import lazily to avoid circular imports during Blender add-on discovery.
    from . import registry

    registry.register()


def unregister():
    """Unregister Blender addon classes."""
    from . import registry

    registry.unregister()


# Public API for external add-ons/scripts
__all__ = [
    "tool",
    "resource",
    "prompt",
    "iter_tools",
    "iter_resources",
    "iter_prompts",
    "start_server",
    "stop_server",
    "is_running",
    "is_shutting_down",
    "wait_shutdown",
    "register",
    "unregister",
]
