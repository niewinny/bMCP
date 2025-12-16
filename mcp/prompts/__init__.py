"""
MCP Prompts - Dynamic prompt discovery system
"""

from ..logger import get_logger
from . import explain_geonodes  # noqa: F401
from ._internal.registry import iter_prompts

logger = get_logger("bmcp-prompts")


def register_prompts():
    """
    Initialize prompts system.

    Prompts are already imported and registered via decorators.
    This function just logs the initialization.
    """
    logger.info("Initializing prompts system...")

    # Count and list registered prompts
    prompts = list(iter_prompts())
    prompt_count = len(prompts)
    logger.info("Prompts system ready - %d prompt(s) available", prompt_count)

    # Debug: log each prompt
    for p in prompts:
        logger.debug(
            "  Registered prompt: %s (handler: %s)", p.name, p.handler.__name__
        )


# Public API
__all__ = [
    "register_prompts",
]
