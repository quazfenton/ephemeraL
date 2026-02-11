"""Basic quota tracking for sandbox executions."""

from __future__ import annotations

import time
import threading
from typing import Dict


class QuotaManager:
    def __init__(self, limit_per_hour: int = 120) -> None:
        """
        Initialize the quota manager with a per-sandbox hourly execution limit and an empty timestamp store.

        Parameters:
            limit_per_hour (int): Maximum allowed executions per sandbox within any rolling one-hour window (default 120).
        """
        self.limit_per_hour = limit_per_hour
        self._counters: Dict[str, list[float]] = {}
        self._lock = threading.Lock()  # Thread lock for atomic operations

    def allow_execution(self, sandbox_id: str) -> bool:
        """
        Check whether the specified sandbox has remaining executions available within the current one-hour window.

        Parameters:
            sandbox_id (str): Identifier of the sandbox to check.

        Returns:
            `true` if the sandbox has recorded fewer than `limit_per_hour` executions in the past hour, `false` otherwise.
        """
        now = time.time()
        window = now - 3600
        
        with self._lock:
            timestamps = self._counters.setdefault(sandbox_id, [])
            # Remove expired timestamps
            while timestamps and timestamps[0] < window:
                timestamps.pop(0)
            return len(timestamps) < self.limit_per_hour

    def record_execution(self, sandbox_id: str) -> None:
        """
        Record an execution timestamp for a sandbox.

        Appends the current time to the internal per-sandbox list of execution timestamps used for hourly quota tracking.

        Parameters:
            sandbox_id (str): Identifier of the sandbox whose execution should be recorded.
        """
        now = time.time()
        
        with self._lock:
            timestamps = self._counters.setdefault(sandbox_id, [])
            timestamps.append(now)

    def check_and_record_execution(self, sandbox_id: str) -> bool:
        """
        Atomically check if execution is allowed and record it if it is.

        This combines the check and record operations to prevent race conditions
        where multiple concurrent requests could exceed the quota.

        Parameters:
            sandbox_id (str): Identifier of the sandbox to check and record.

        Returns:
            `true` if execution was allowed and recorded, `false` otherwise.
        """
        now = time.time()
        window = now - 3600
        
        with self._lock:
            timestamps = self._counters.setdefault(sandbox_id, [])
            # Remove expired timestamps
            while timestamps and timestamps[0] < window:
                timestamps.pop(0)
            
            if len(timestamps) < self.limit_per_hour:
                timestamps.append(now)
                return True
            return False