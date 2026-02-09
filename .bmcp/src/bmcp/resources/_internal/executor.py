"""
Resource Executor

Executes resource functions on the main thread (Blender) or in a thread pool (standalone).
Provides async/sync bridging for the MCP server.

When bpy is available (Blender context):
- Uses bpy.app.timers to schedule execution on main thread
- Uses bpy.ops operators for resource execution
- Uses window_manager properties for result passing

When bpy is NOT available (standalone):
- Executes handler directly in a thread pool executor
"""

import asyncio

from ...logger import get_logger

# Get logger for this module
logger = get_logger("bmcp-executor")

# Try to import bpy for Blender integration
try:
    import bpy

    _HAS_BPY = True
except ImportError:
    _HAS_BPY = False


if _HAS_BPY:
    # Blender-specific imports and implementation
    import threading
    import time
    import uuid
    from collections import OrderedDict

    from ...config import (
        MAX_PENDING_OPS,
        RESOURCE_TIMEOUT,
    )

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
        """Register a new pending operation, cancelling and REMOVING oldest if at limit."""
        with _pending_lock:
            if len(_pending_operations) >= MAX_PENDING_OPS:
                oldest_id, oldest_info = next(iter(_pending_operations.items()))
                oldest_info["cancelled"] = True

                oldest_event = oldest_info.get("event")
                oldest_loop = oldest_info.get("loop")
                if oldest_event and oldest_loop:
                    try:
                        oldest_loop.call_soon_threadsafe(oldest_event.set)
                    except RuntimeError:
                        pass

                del _pending_operations[oldest_id]

                age = time.time() - oldest_info["start_time"]
                logger.warning(
                    "Operation %s cancelled (queue full, max=%d, age=%.1fs). "
                    "New operation %s taking its place.",
                    oldest_id[:8],
                    MAX_PENDING_OPS,
                    age,
                    job_id[:8],
                )

                _schedule_property_cleanup_for_job(oldest_id)

            _pending_operations[job_id] = {
                "start_time": time.time(),
                "cancelled": False,
                "event": event,
                "loop": loop,
            }

    def _signal_completion(job_id: str) -> None:
        """Signal that an operation has completed (called from main thread)."""
        with _pending_lock:
            info = _pending_operations.get(job_id)
            if info:
                event = info.get("event")
                loop = info.get("loop")
                if event and loop:
                    try:
                        loop.call_soon_threadsafe(event.set)
                    except RuntimeError:
                        pass

    def _unregister_pending(job_id: str) -> None:
        """Unregister a completed/cancelled operation."""
        with _pending_lock:
            if job_id in _pending_operations:
                del _pending_operations[job_id]

    def _is_cancelled(job_id: str) -> bool:
        """Check if an operation has been cancelled."""
        with _pending_lock:
            info = _pending_operations.get(job_id)
            if info is None:
                return True
            return info.get("cancelled", False)

    def clear_pending_operations() -> int:
        """Clear all pending operations (call on server shutdown)."""
        with _pending_lock:
            count = len(_pending_operations)
            _pending_operations.clear()
            return count

    def _schedule_property_cleanup_for_job(job_id: str) -> None:
        """Schedule cleanup of window_manager properties for a specific job."""

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
                    try:
                        del wm[key]
                        logger.debug("Cleaned up orphaned property: %s", key)
                    except KeyError:
                        pass
            except Exception as e:
                logger.debug("Property cleanup error (non-fatal): %s", e)

        try:
            bpy.app.timers.register(cleanup, first_interval=0.0)
        except Exception as e:
            logger.debug("Timer registration failed for job %s cleanup: %s", job_id[:8], e)

    def _cleanup_properties_immediately(wm, keys: tuple) -> None:
        """Clean up window_manager properties IMMEDIATELY (not scheduled)."""
        for key in keys:
            try:
                del wm[key]
            except KeyError:
                pass
            except Exception as e:
                logger.debug("Failed to delete property %s: %s", key, e)

    def cleanup_stale_properties(max_age: float | None = None) -> int:
        """Clean up MCP window_manager properties from previous/crashed operations.

        Note: Blender custom properties don't store timestamps, so max_age
        cannot be checked. All matching MCP properties are removed.

        Args:
            max_age: Unused (kept for API compatibility). All matching
                properties are removed regardless of age.
        """
        # max_age is accepted but unused — Blender wm properties have no timestamps
        _ = max_age

        try:
            wm = bpy.context.window_manager
            if wm is None:
                return 0

            cleaned = 0
            keys_to_delete = []

            for key in list(wm.keys()):
                is_resource_prop = any(
                    key.startswith(prefix) for prefix in _RESOURCE_PROPERTY_PREFIXES
                )
                is_code_prop = key.startswith(_CODE_PROPERTY_PREFIX)

                if is_resource_prop or is_code_prop:
                    keys_to_delete.append(key)

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
        """Execute a resource by URI on Blender's main thread and wait for result."""
        if timeout is None:
            timeout = RESOURCE_TIMEOUT

        job_id = str(uuid.uuid4())

        result_key = f"mcp_resource_data_{job_id}"
        done_key = f"mcp_resource_done_{job_id}"
        error_key = f"mcp_resource_error_{job_id}"
        property_keys = (result_key, done_key, error_key)

        wm = bpy.context.window_manager
        if wm is None:
            raise RuntimeError("Blender context not available (window_manager is None)")

        completion_event = asyncio.Event()
        loop = asyncio.get_running_loop()

        _register_pending(job_id, completion_event, loop)

        try:
            def run_on_main_thread():
                bpy.ops.bmcp.get_resources(uri=uri, job_id=job_id)
                _signal_completion(job_id)

            bpy.app.timers.register(run_on_main_thread, first_interval=0.0)

            try:
                await asyncio.wait_for(completion_event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                _schedule_property_cleanup_for_job(job_id)
                timeout_msg = (
                    f"Resource execution timed out after {timeout:.1f} seconds. "
                    f"URI: {uri}. "
                    f"The resource may still be running in Blender. "
                    f"To increase the timeout, modify RESOURCE_TIMEOUT in config.py "
                    f"or set it to None for infinite wait."
                )
                raise TimeoutError(timeout_msg)

            if _is_cancelled(job_id):
                _schedule_property_cleanup_for_job(job_id)
                raise RuntimeError(
                    f"Operation cancelled: too many pending operations "
                    f"(max {MAX_PENDING_OPS}). URI: {uri}"
                )

            error_msg = wm.get(error_key)
            result = wm.get(result_key, "")

            def immediate_cleanup():
                _cleanup_properties_immediately(bpy.context.window_manager, property_keys)

            bpy.app.timers.register(immediate_cleanup, first_interval=0.0)

            if error_msg:
                raise RuntimeError(error_msg)

            return result

        finally:
            _unregister_pending(job_id)

else:
    # Standalone implementation (no bpy)

    async def execute_resource(uri: str, timeout: float | None = None) -> str:
        """Execute a resource by URI directly in a thread pool (standalone mode)."""
        from .registry import iter_resources

        for res in iter_resources():
            if res.uri == uri:
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(None, res.handler)
        raise ValueError(f"Resource '{uri}' not found")

    def clear_pending_operations() -> int:
        """No-op for standalone mode."""
        return 0

    def cleanup_stale_properties(max_age: float | None = None) -> int:
        """No-op for standalone mode."""
        return 0
