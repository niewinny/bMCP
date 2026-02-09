"""
Shared validation utilities for decorators.

Provides common validation functions used by @tool and @resource decorators.
All validators return True if valid, False if invalid (with logging).
"""

import logging
import weakref
from types import FunctionType
from typing import Any, get_type_hints

# =============================================================================
# TYPE HINTS CACHE - Avoids expensive re-parsing of type hints
# =============================================================================
_type_hints_cache: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def get_cached_type_hints(func: FunctionType) -> dict:
    """
    Get type hints for a function with caching.

    This avoids expensive re-parsing of type hints when the same function
    is inspected multiple times (e.g., during validation AND schema generation).

    Args:
        func: Function to get type hints for

    Returns:
        dict: Type hints for the function (empty dict if resolution fails)
    """
    try:
        return _type_hints_cache[func]
    except (KeyError, TypeError):
        pass
    try:
        hints = get_type_hints(func)
    except Exception:
        # Type hints might not be available in all contexts
        hints = {}
    try:
        _type_hints_cache[func] = hints
    except TypeError:
        # func is not weak-referenceable (e.g. built-in), skip caching
        pass
    return hints


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
    func: FunctionType, decorator_name: str, logger: logging.Logger
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


def check_docstring(func: FunctionType, logger: logging.Logger) -> bool:
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
    func: FunctionType, expected_type: type, strict: bool, logger: logging.Logger
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
    raw_annotations = getattr(func, "__annotations__", {})
    if "return" not in raw_annotations:
        logger.warning(
            f"'{func.__name__}' has no return type annotation "
            f"(should be '-> {expected_type.__name__}')"
        )
        return True

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
        except Exception:
            return_annotation = raw_annotations.get("return", "")
            if expected_type.__name__ not in str(return_annotation):
                logger.warning(
                    f"'{func.__name__}' should return '{expected_type.__name__}', "
                    f"got '{return_annotation}'"
                )
    else:
        return_annotation = raw_annotations.get("return", "")
        if expected_type.__name__ not in str(return_annotation):
            logger.warning(
                f"'{func.__name__}' should return '{expected_type.__name__}', "
                f"got '{return_annotation}'"
            )

    return True
