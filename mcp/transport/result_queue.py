"""
Result Queue for thread-safe job management.

This module provides a thread-safe queue for managing tool execution results
between Blender's main thread and the HTTP server thread.

Architecture:
- Jobs are registered before scheduling on main thread
- Results/errors are stored after execution completes
- Threading.Event provides synchronization for waiting callers
- Automatic cleanup ensures no memory leaks
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from ..logger import get_logger

logger = get_logger("bmcp-result-queue")


@dataclass
class JobEntry:
    """Represents a single job in the result queue."""

    status: str = "pending"  # pending, success, error, cancelled
    result: Any = None
    error: Optional[str] = None
    event: threading.Event = field(default_factory=threading.Event)
    created_at: float = field(default_factory=time.time)


class ResultQueue:
    """
    Thread-safe queue for managing tool execution results.

    This class handles the synchronization between the HTTP server thread
    (which receives requests) and Blender's main thread (which executes tools).

    Usage:
        queue = ResultQueue()

        # Register a job and get its event
        event = queue.register(job_id)

        # Schedule work on main thread...

        # Wait for completion
        if event.wait(timeout=30):
            result = queue.get_result(job_id)
            queue.cleanup(job_id)
    """

    def __init__(self):
        self._queue: dict[str, JobEntry] = {}
        self._lock = threading.Lock()

    def register(self, job_id: str) -> threading.Event:
        """
        Register a new job and return its synchronization event.

        Args:
            job_id: Unique identifier for the job

        Returns:
            threading.Event that will be set when the job completes
        """
        with self._lock:
            entry = JobEntry()
            self._queue[job_id] = entry
            return entry.event

    def exists(self, job_id: str) -> bool:
        """Check if a job exists in the queue."""
        with self._lock:
            return job_id in self._queue

    def get_status(self, job_id: str) -> Optional[str]:
        """Get the current status of a job."""
        with self._lock:
            entry = self._queue.get(job_id)
            return entry.status if entry else None

    def is_cancelled(self, job_id: str) -> bool:
        """Check if a job has been cancelled."""
        with self._lock:
            entry = self._queue.get(job_id)
            if not entry:
                return True  # Job doesn't exist, treat as cancelled
            return entry.status == "cancelled"

    def set_success(self, job_id: str, result: Any) -> bool:
        """
        Mark a job as successful with its result.

        Args:
            job_id: Job identifier
            result: The execution result

        Returns:
            True if job was updated, False if job not found
        """
        with self._lock:
            entry = self._queue.get(job_id)
            if not entry:
                return False
            entry.status = "success"
            entry.result = result
            entry.event.set()
            return True

    def set_error(self, job_id: str, error: str) -> bool:
        """
        Mark a job as failed with an error message.

        Args:
            job_id: Job identifier
            error: Error message

        Returns:
            True if job was updated, False if job not found
        """
        with self._lock:
            entry = self._queue.get(job_id)
            if not entry:
                return False
            entry.status = "error"
            entry.error = error
            entry.event.set()
            return True

    def mark_cancelled(self, job_id: str) -> bool:
        """
        Mark a job as cancelled (typically due to timeout).

        Args:
            job_id: Job identifier

        Returns:
            True if job was marked, False if job not found
        """
        with self._lock:
            entry = self._queue.get(job_id)
            if not entry:
                return False
            entry.status = "cancelled"
            logger.debug("Job %s marked as cancelled", job_id[:8])
            return True

    def get_result(self, job_id: str) -> tuple[str, Any, Optional[str]]:
        """
        Get the result of a completed job.

        Args:
            job_id: Job identifier

        Returns:
            Tuple of (status, result, error)

        Raises:
            KeyError: If job not found
        """
        with self._lock:
            entry = self._queue.get(job_id)
            if not entry:
                raise KeyError(f"Job {job_id} not found in queue")
            return entry.status, entry.result, entry.error

    def cleanup(self, job_id: str) -> bool:
        """
        Remove a job from the queue.

        Args:
            job_id: Job identifier

        Returns:
            True if job was removed, False if not found
        """
        with self._lock:
            if job_id in self._queue:
                del self._queue[job_id]
                return True
            return False

    def clear_all(self) -> int:
        """
        Clear all jobs from the queue.

        Returns:
            Number of jobs cleared
        """
        with self._lock:
            count = len(self._queue)
            self._queue.clear()
            return count

    def __len__(self) -> int:
        """Return the number of jobs in the queue."""
        with self._lock:
            return len(self._queue)
