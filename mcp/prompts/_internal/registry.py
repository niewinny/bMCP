"""
Prompts Registry - Decorator and storage for MCP prompts.

Provides @prompt decorator and registry for prompt discovery.
"""

import inspect
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Set

from ...logger import get_logger
from ...utils import validators as utils

logger = get_logger("bmcp-prompts-registry")


@dataclass
class PromptArgument:
    """Prompt argument definition for MCP."""

    name: str
    description: str = ""
    required: bool = True


@dataclass
class PromptRegistration:
    """Prompt registration entry."""

    name: str
    handler: Callable[..., List[dict]]
    title: Optional[str] = None  # Human-readable display name
    description: Optional[str] = None
    arguments: List[PromptArgument] = field(default_factory=list)


# Internal registry populated by @prompt decorator
_prompt_registry: List[PromptRegistration] = []
_registered_names: Set[str] = set()


def prompt(func: Callable[..., List[dict]]) -> Callable[..., List[dict]]:
    """
    Decorator to register an MCP prompt.

    Prompts are synchronous functions that return a list of messages.
    They run in async context (no Blender API access needed - prompts are templates).

    The prompt name is automatically derived from the function name.
    The description is extracted from the docstring.
    Arguments are extracted from function parameters and type hints.

    Args:
        func: Function to register as a prompt (must return List[dict])

    Returns:
        The same function (unmodified)

    Example:
        @prompt
        def explain_geonodes(focus: str = "all") -> list[dict]:
            '''Explain selected geometry nodes in detail.

            Args:
                focus: Area to focus on - "all", "inputs", "outputs", "flow"
            '''
            return [{"role": "user", "content": {"type": "text", "text": "..."}}]
    """
    # Validate function
    is_valid = (
        utils.validate_callable(func, "prompt", logger)
        and utils.validate_has_name(func, "prompt", logger)
        and utils.check_docstring(func, logger)
    )

    if not is_valid:
        return func

    prompt_name = func.__name__

    # Check for duplicate name
    if prompt_name in _registered_names:
        logger.error(
            "Prompt '%s' is already registered. Duplicate ignored.", prompt_name
        )
        return func

    # Generate title from function name (e.g., "explain_geonodes" -> "Explain Geonodes")
    title = prompt_name.replace("_", " ").title()

    # Extract description from docstring (first paragraph, before Args:)
    description = ""
    if func.__doc__:
        doc_lines = func.__doc__.strip().split("\n")
        desc_lines = []
        for line in doc_lines:
            stripped = line.strip()
            if stripped.lower().startswith("args:") or stripped == "":
                break
            desc_lines.append(stripped)
        description = " ".join(desc_lines)

    # Extract arguments from function signature
    arguments = []
    sig = inspect.signature(func)

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue

        # Determine if required (no default value)
        required = param.default == inspect.Parameter.empty

        # Try to get description from docstring Args section
        arg_desc = ""
        if func.__doc__ and "Args:" in func.__doc__:
            args_section = func.__doc__.split("Args:")[1]
            for line in args_section.split("\n"):
                if param_name in line and ":" in line:
                    arg_desc = line.split(":", 1)[1].strip()
                    break

        arguments.append(
            PromptArgument(name=param_name, description=arg_desc, required=required)
        )

    _prompt_registry.append(
        PromptRegistration(
            name=prompt_name,
            handler=func,
            title=title,
            description=description,
            arguments=arguments,
        )
    )
    _registered_names.add(prompt_name)
    logger.debug("Registered prompt: %s", prompt_name)

    return func


def iter_prompts() -> List[PromptRegistration]:
    """Return a snapshot of all registered prompts."""
    return list(_prompt_registry)


def clear_registry() -> None:
    """Clear all registered prompts.

    Used for testing and server restart to prevent stale registrations.
    """
    _prompt_registry.clear()
    _registered_names.clear()
    logger.debug("Prompt registry cleared")


__all__ = [
    "prompt",
    "iter_prompts",
    "clear_registry",
    "PromptRegistration",
    "PromptArgument",
]
