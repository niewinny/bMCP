"""
Resource Executor

Executes resource functions on Blender's main thread via the get_resources operator.
Provides async/sync bridging for the MCP server.

Execution Model:
- Each request gets a unique job_id (UUID)
- Requests are independent - if one hangs, others continue working
- Blender's timer system queues operations sequentially on main thread
- Configurable timeout (default: 5 minutes)
- Uses event-based completion signaling for low-latency response

Queue Management:
- Maximum of MAX_PENDING_OPERATIONS concurrent pending operations
- When limit reached, oldest pending operation is cancelled and REMOVED immediately
- Prevents unbounded memory growth from stuck operations
- Cancelled operations raise RuntimeError to inform the client

Property Cleanup:
- Window manager properties are cleaned up IMMEDIATELY after use (not scheduled)
- Stale properties from crashed operations are cleaned up periodically
- Properties use unique job_id keys to prevent collisions
"""

import asyncio
import threading
import time
import uuid
from collections import OrderedDict

import bpy

from ...logger import get_logger
from ...utils.config import (
    MAX_PENDING_OPERATIONS,
    RESOURCE_EXECUTION_TIMEOUT,
    STALE_PROPERTY_AGE,
)

# Get logger for this module
logger = get_logger("bmcp-executor")

# Track pending operations: job_id -> {"start_time": float, "cancelled": bool, "event": asyncio.Event, "loop": asyncio.AbstractEventLoop}
_pending_operations: OrderedDict[str, dict] = OrderedDict()
_pending_lock = threading.Lock()  # Use threading.Lock for thread-safe access

# Track property keys for cleanup
_RESOURCE_PROPERTY_PREFIXES = (
    "mcp_resource_data_",
    "mcp_resource_done_",
    "mcp_resource_error_",
)
_CODE_PROPERTY_PREFIX = "mcp_result_"


def _register_pending(
    job_id: str, event: asyncio.Event, loop: asyncio.AbstractEventLoop
) -> None:
    """Register a new pending operation, cancelling and REMOVING oldest if at limit.

    Args:
        job_id: Unique identifier for the operation
        event: asyncio.Event to signal when operation completes
        loop: Event loop to use for thread-safe signaling
    """
    with _pending_lock:
        # Check if we need to cancel oldest
        if len(_pending_operations) >= MAX_PENDING_OPERATIONS:
            # Get oldest (first item in OrderedDict)
            oldest_id, oldest_info = next(iter(_pending_operations.items()))
            oldest_info["cancelled"] = True

            # Signal the event so the waiting coroutine wakes up and sees cancellation
            oldest_event = oldest_info.get("event")
            oldest_loop = oldest_info.get("loop")
            if oldest_event and oldest_loop:
                try:
                    oldest_loop.call_soon_threadsafe(oldest_event.set)
                except RuntimeError:
                    pass  # Loop may be closed

            # IMMEDIATELY remove the cancelled operation from tracking
            del _pending_operations[oldest_id]

            # Log the cancellation with details
            age = time.time() - oldest_info["start_time"]
            logger.warning(
                "Operation %s cancelled (queue full, max=%d, age=%.1fs). "
                "New operation %s taking its place.",
                oldest_id[:8],
                MAX_PENDING_OPERATIONS,
                age,
                job_id[:8],
            )

            # Schedule cleanup of any orphaned properties for the cancelled operation
            _schedule_property_cleanup_for_job(oldest_id)

        # Register new operation with event for signaling
        _pending_operations[job_id] = {
            "start_time": time.time(),
            "cancelled": False,
            "event": event,
            "loop": loop,
        }


def _signal_completion(job_id: str) -> None:
    """Signal that an operation has completed (called from main thread).

    This wakes up the waiting coroutine immediately without polling.
    """
    with _pending_lock:
        info = _pending_operations.get(job_id)
        if info:
            event = info.get("event")
            loop = info.get("loop")
            if event and loop:
                try:
                    loop.call_soon_threadsafe(event.set)
                except RuntimeError:
                    pass  # Loop may be closed


def _unregister_pending(job_id: str) -> None:
    """Unregister a completed/cancelled operation."""
    with _pending_lock:
        if job_id in _pending_operations:
            del _pending_operations[job_id]


def _is_cancelled(job_id: str) -> bool:
    """Check if an operation has been cancelled.

    Returns True if:
    - The operation was explicitly marked as cancelled
    - The operation was removed from the dict (cancelled and cleaned up)
    """
    with _pending_lock:
        info = _pending_operations.get(job_id)
        if info is None:
            # Entry was removed - treat as cancelled
            return True
        return info.get("cancelled", False)


def clear_pending_operations() -> int:
    """
    Clear all pending operations (call on server shutdown).

    Returns:
        Number of operations that were cleared.
    """
    with _pending_lock:
        count = len(_pending_operations)
        _pending_operations.clear()
        return count


def _schedule_property_cleanup_for_job(job_id: str) -> None:
    """
    Schedule cleanup of window_manager properties for a specific job.

    This is called when an operation is cancelled to clean up any orphaned properties.
    Runs on Blender's main thread via timer.
    """

    def cleanup():
        try:
            wm = bpy.context.window_manager
            keys_to_delete = [
                f"mcp_resource_data_{job_id}",
                f"mcp_resource_done_{job_id}",
                f"mcp_resource_error_{job_id}",
                f"mcp_result_{job_id}",
            ]
            for key in keys_to_delete:
                if key in wm:
                    del wm[key]
                    logger.debug("Cleaned up orphaned property: %s", key)
        except Exception as e:
            logger.debug("Property cleanup error (non-fatal): %s", e)

    try:
        bpy.app.timers.register(cleanup, first_interval=0.0)
    except Exception as e:
        logger.debug("Timer registration failed for job %s cleanup: %s", job_id[:8], e)


def _cleanup_properties_immediately(wm, keys: tuple) -> None:
    """
    Clean up window_manager properties IMMEDIATELY (not scheduled).

    Args:
        wm: Window manager reference
        keys: Tuple of property keys to delete
    """
    for key in keys:
        try:
            if key in wm:
                del wm[key]
        except Exception as e:
            logger.debug("Failed to delete property %s: %s", key, e)


def cleanup_stale_properties(max_age: float | None = None) -> int:
    """
    Clean up stale window_manager properties from crashed/abandoned operations.

    This should be called periodically (e.g., on server start) to clean up
    any orphaned properties from previous sessions or crashed operations.

    Args:
        max_age: Maximum age in seconds for stale properties (uses STALE_PROPERTY_AGE from config if None)

    Returns:
        Number of properties cleaned up.
    """
    if max_age is None:
        max_age = STALE_PROPERTY_AGE

    try:
        wm = bpy.context.window_manager
        if wm is None:
            return 0

        cleaned = 0
        keys_to_delete = []

        # Find all MCP-related properties
        for key in list(wm.keys()):
            is_resource_prop = any(
                key.startswith(prefix) for prefix in _RESOURCE_PROPERTY_PREFIXES
            )
            is_code_prop = key.startswith(_CODE_PROPERTY_PREFIX)

            if is_resource_prop or is_code_prop:
                keys_to_delete.append(key)

        # Delete them
        for key in keys_to_delete:
            try:
                del wm[key]
                cleaned += 1
            except Exception as e:
                logger.debug("Failed to delete stale property %s: %s", key, e)

        if cleaned > 0:
            logger.info("Cleaned up %d stale MCP properties", cleaned)

        return cleaned

    except Exception as e:
        logger.debug("Stale property cleanup error: %s", e)
        return 0


async def execute_resource(uri: str, timeout: float | None = None) -> str:
    """
    Execute a resource by URI on Blender's main thread and wait for result.

    This function:
    1. Generates a unique job ID and registers as pending with an asyncio.Event
    2. Schedules the get_resources operator on main thread via bpy.app.timers
    3. Waits for completion signal (event-based, not polling) with configurable timeout
    4. Retrieves result from window_manager properties
    5. Cleans up temporary properties IMMEDIATELY after reading (not scheduled)

    Args:
        uri: Resource URI to read (e.g., "blender://active_scene")
        timeout: Timeout in seconds (uses RESOURCE_EXECUTION_TIMEOUT from config if None)

    Returns:
        str: Result string from resource execution

    Raises:
        TimeoutError: If execution times out
        RuntimeError: If execution fails, context unavailable, or cancelled

    Note:
        Max MAX_PENDING_OPERATIONS concurrent operations. Oldest cancelled when full.
        Each request has unique job_id so other requests continue working.
        Properties are cleaned up immediately to prevent accumulation in .blend files.
        Uses event-based signaling for low-latency response (no polling overhead).
    """
    if timeout is None:
        timeout = RESOURCE_EXECUTION_TIMEOUT

    job_id = str(uuid.uuid4())
    start_time = time.time()

    # Key names for window_manager properties
    result_key = f"mcp_resource_data_{job_id}"
    done_key = f"mcp_resource_done_{job_id}"
    error_key = f"mcp_resource_error_{job_id}"
    property_keys = (result_key, done_key, error_key)

    # Get window_manager reference - validate context is available
    wm = bpy.context.window_manager
    if wm is None:
        raise RuntimeError("Blender context not available (window_manager is None)")

    # Create event for completion signaling
    completion_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    # Register as pending with event (may cancel oldest if at limit)
    _register_pending(job_id, completion_event, loop)

    try:
        # Schedule operator call on main thread with completion signaling
        def run_on_main_thread():
            bpy.ops.bmcp.get_resources(uri=uri, job_id=job_id)
            # Signal completion immediately after operator finishes
            _signal_completion(job_id)

        bpy.app.timers.register(run_on_main_thread, first_interval=0.0)

        # Wait for completion event with timeout (event-based, not polling)
        try:
            await asyncio.wait_for(completion_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            # Schedule cleanup since we can't do it from async context
            _schedule_property_cleanup_for_job(job_id)
            timeout_msg = (
                f"Resource execution timed out after {timeout:.1f} seconds. "
                f"URI: {uri}. "
                f"The resource may still be running in Blender. "
                f"To increase the timeout, modify RESOURCE_EXECUTION_TIMEOUT in config.py "
                f"or set it to None for infinite wait."
            )
            raise TimeoutError(timeout_msg)

        # Check if we were cancelled (event was signaled due to cancellation)
        if _is_cancelled(job_id):
            _schedule_property_cleanup_for_job(job_id)
            raise RuntimeError(
                f"Operation cancelled: too many pending operations "
                f"(max {MAX_PENDING_OPERATIONS}). URI: {uri}"
            )

        # Read values BEFORE cleanup
        error_msg = wm.get(error_key)
        result = wm.get(result_key, "")

        # Clean up properties IMMEDIATELY via scheduled timer
        # We must use timer because we're in async context, not main thread
        def immediate_cleanup():
            _cleanup_properties_immediately(bpy.context.window_manager, property_keys)

        bpy.app.timers.register(immediate_cleanup, first_interval=0.0)

        # Raise error if execution failed
        if error_msg:
            raise RuntimeError(error_msg)

        return result

    finally:
        # Always unregister from pending operations
        _unregister_pending(job_id)
