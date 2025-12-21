"""
Centralized logging configuration for bMCP servers.

Provides structured logging with request context, correlation IDs, and timing utilities.
"""

import logging
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Optional

# Context variable for request ID (async/thread-safe)
_request_id: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


class RequestContextFilter(logging.Filter):
    """Add request context to log records."""

    def filter(self, record):
        req_id = _request_id.get()
        record.request_id = req_id[:8] if req_id else "-"
        return True


def setup_logging(level=logging.WARNING):
    """
    Configure logging for bMCP servers with request context.

    Args:
        level: Logging level (default: logging.WARNING)
    """
    # Get root logger
    root = logging.getLogger()
    root.setLevel(level)

    # Remove existing handlers to avoid duplicates
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    # Create stderr handler with request context
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(request_id)s] %(name)s %(levelname)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    handler.addFilter(RequestContextFilter())
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger for a specific module.

    Args:
        name: Logger name (e.g., "bmcp-mcp-http", "bmcp-handlers")

    Returns:
        Logger instance with the specified name
    """
    return logging.getLogger(name)


def set_request_id(request_id: Optional[str] = None) -> str:
    """
    Set the current request ID for logging context.

    Args:
        request_id: Request ID to set, or None to generate new one

    Returns:
        The request ID that was set
    """
    if request_id is None:
        request_id = str(uuid.uuid4())
    _request_id.set(request_id)
    return request_id


def get_request_id() -> Optional[str]:
    """Get the current request ID."""
    return _request_id.get()


def clear_request_id():
    """Clear the current request ID."""
    _request_id.set(None)


class RequestTimer:
    """
    Context manager for timing operations with automatic logging.

    Usage:
        with RequestTimer(logger, "tool/blender_run_code"):
            # ... operation ...
    """

    def __init__(self, logger: logging.Logger, operation: str, log_start: bool = False):
        """
        Args:
            logger: Logger instance
            operation: Description of operation being timed
            log_start: Whether to log when operation starts (default: False)
        """
        self.logger = logger
        self.operation = operation
        self.log_start = log_start
        self.start_time: float | None = None
        self.duration_ms: float | None = None

    def __enter__(self):
        self.start_time = time.perf_counter()
        if self.log_start:
            self.logger.debug("Starting: %s", self.operation)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time is None:
            return False
        self.duration_ms = (time.perf_counter() - self.start_time) * 1000

        if exc_type:
            self.logger.error(
                "%s failed after %.2fms: %s: %s",
                self.operation,
                self.duration_ms,
                exc_type.__name__,
                exc_val,
            )
        else:
            self.logger.debug(
                "%s completed in %.2fms", self.operation, self.duration_ms
            )

        return False  # Don't suppress exceptions
