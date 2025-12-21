"""
Shared validation utilities for decorators.

Provides common validation functions used by @tool and @resource decorators.
All validators return True if valid, False if invalid (with logging).
"""

import logging
from typing import Any, Callable, get_type_hints

# =============================================================================
# TYPE HINTS CACHE - Avoids expensive re-parsing of type hints
# =============================================================================
_type_hints_cache: dict[int, dict] = {}  # keyed by id(func)


def get_cached_type_hints(func: Callable) -> dict:
    """
    Get type hints for a function with caching.

    This avoids expensive re-parsing of type hints when the same function
    is inspected multiple times (e.g., during validation AND schema generation).

    Args:
        func: Function to get type hints for

    Returns:
        dict: Type hints for the function (empty dict if resolution fails)
    """
    func_id = id(func)
    if func_id not in _type_hints_cache:
        try:
            _type_hints_cache[func_id] = get_type_hints(func)
        except Exception:
            # Type hints might not be available in all contexts
            # Common causes: ForwardRef resolution, circular imports, missing modules
            _type_hints_cache[func_id] = {}
    return _type_hints_cache[func_id]


def clear_type_hints_cache() -> None:
    """Clear the type hints cache (useful for testing or reloading)."""
    _type_hints_cache.clear()


def validate_callable(func: Any, decorator_name: str, logger: logging.Logger) -> bool:
    """
    Validate that the decorated object is callable.

    Args:
        func: Object to validate
        decorator_name: Name of decorator for error message
        logger: Logger instance for errors

    Returns:
        True if valid, False otherwise
    """
    if not callable(func):
        logger.error(
            f"@{decorator_name} decorator can only be applied to functions, "
            f"got {type(func).__name__}"
        )
        return False
    return True


def validate_has_name(
    func: Callable, decorator_name: str, logger: logging.Logger
) -> bool:
    """
    Validate that function has __name__ attribute.

    Args:
        func: Function to validate
        decorator_name: Name of decorator for error message
        logger: Logger instance for errors

    Returns:
        True if valid, False otherwise
    """
    if not hasattr(func, "__name__"):
        logger.error(
            "@%s decorator requires function to have __name__ attribute", decorator_name
        )
        return False
    return True


def check_docstring(func: Callable, logger: logging.Logger) -> bool:
    """
    Check if function has docstring, warn if missing.

    Args:
        func: Function to check
        logger: Logger instance for warnings

    Returns:
        True (always - this is just a warning, not a validation failure)
    """
    if not func.__doc__:
        logger.warning(
            "'%s' has no docstring - description will be empty", func.__name__
        )
    return True


def check_return_type(
    func: Callable, expected_type: type, strict: bool, logger: logging.Logger
) -> bool:
    """
    Check if function has correct return type annotation.

    Args:
        func: Function to check
        expected_type: Expected return type (e.g., str)
        strict: If True, type must match exactly; if False, allow type to contain expected_type
        logger: Logger instance for warnings

    Returns:
        True (always - this is just a warning, not a validation failure)
    """
    # First check raw annotations (doesn't require resolving forward references)
    raw_annotations = getattr(func, "__annotations__", {})
    if "return" not in raw_annotations:
        logger.warning(
            f"'{func.__name__}' has no return type annotation "
            f"(should be '-> {expected_type.__name__}')"
        )
        return True

    # For strict type checking, try to resolve and compare types
    if strict:
        try:
            hints = get_cached_type_hints(func)
            if "return" in hints:
                return_type = hints["return"]
                if return_type != expected_type:
                    logger.warning(
                        f"'{func.__name__}' must return '{expected_type.__name__}', "
                        f"got '{return_type}'"
                    )
        except (NameError, AttributeError, TypeError):
            # Forward reference resolution failed - just check string representation
            return_annotation = raw_annotations.get("return", "")
            if expected_type.__name__ not in str(return_annotation):
                logger.warning(
                    f"'{func.__name__}' should return '{expected_type.__name__}', "
                    f"got '{return_annotation}'"
                )
    else:
        # Non-strict: just check if expected type name is in the annotation string
        return_annotation = raw_annotations.get("return", "")
        if expected_type.__name__ not in str(return_annotation):
            logger.warning(
                f"'{func.__name__}' should return '{expected_type.__name__}', "
                f"got '{return_annotation}'"
            )

    return True
