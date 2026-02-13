"""Basic quota tracking for sandbox executions."""

from __future__ import annotations

import logging
import time
import threading
from dataclasses import dataclass, field
from typing import Dict

logger = logging.getLogger(__name__)

QUOTA_WARNING_THRESHOLD = 0.8


@dataclass
class ResourceQuota:
    max_executions_per_hour: int = 120
    max_concurrent_sandboxes: int = 10
    max_memory_mb: int = 2048
    max_cpu_seconds_per_hour: int = 3600
    max_storage_bytes: int = 5 * 1024 * 1024 * 1024  # 5GB
    max_network_egress_bytes_per_hour: int = 1 * 1024 * 1024 * 1024  # 1GB


class QuotaManager:
    def __init__(
        self,
        limit_per_hour: int | None = None,
        quota: ResourceQuota | None = None,
    ) -> None:
        """
        Initialize the quota manager.

        Parameters:
            limit_per_hour (int | None): Maximum allowed executions per sandbox within any rolling
                one-hour window. If provided, overrides quota.max_executions_per_hour.
            quota (ResourceQuota | None): Full resource quota configuration. Defaults to ResourceQuota().
        """
        self.quota = quota or ResourceQuota()
        if limit_per_hour is not None:
            self.quota.max_executions_per_hour = limit_per_hour
        self.limit_per_hour = self.quota.max_executions_per_hour
        self._counters: Dict[str, list[float]] = {}
        self._active_sandboxes: set[str] = set()
        self._resource_usage: Dict[str, dict] = {}
        self._lock = threading.Lock()

    def allow_execution(self, sandbox_id: str) -> bool:
        """
        DEPRECATED: Check and record an execution atomically to prevent race conditions.
        
        This method has a race condition when used alongside record_execution.
        Use check_and_record_execution instead for atomic operation.

        Parameters:
            sandbox_id (str): Identifier of the sandbox to check.

        Returns:
            `true` if the sandbox has recorded fewer than `limit_per_hour` executions in the past hour, `false` otherwise.
        """
        # Call the atomic method to prevent race conditions
        return self.check_and_record_execution(sandbox_id)

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

    def check_sandbox_limit(self) -> bool:
        """Check if we're under the max concurrent sandboxes limit."""
        with self._lock:
            count = len(self._active_sandboxes)
            limit = self.quota.max_concurrent_sandboxes
            if count >= limit * QUOTA_WARNING_THRESHOLD and count < limit:
                logger.warning(
                    "Approaching concurrent sandbox limit: %d/%d", count, limit
                )
            return count < limit

    def record_sandbox_created(self, sandbox_id: str) -> None:
        """Record that a sandbox has been created."""
        with self._lock:
            self._active_sandboxes.add(sandbox_id)
            self._resource_usage.setdefault(sandbox_id, {
                "memory_mb": 0,
                "storage_bytes": 0,
                "cpu_seconds": 0,
                "network_egress_bytes": 0,
            })

    def record_sandbox_destroyed(self, sandbox_id: str) -> None:
        """Record that a sandbox has been destroyed."""
        with self._lock:
            self._active_sandboxes.discard(sandbox_id)
            self._resource_usage.pop(sandbox_id, None)

    def record_memory_usage(self, sandbox_id: str, memory_mb: int) -> None:
        """Record current memory usage for a sandbox."""
        with self._lock:
            usage = self._resource_usage.setdefault(sandbox_id, {
                "memory_mb": 0,
                "storage_bytes": 0,
                "cpu_seconds": 0,
                "network_egress_bytes": 0,
            })
            usage["memory_mb"] = memory_mb
            ratio = memory_mb / self.quota.max_memory_mb
            if ratio >= QUOTA_WARNING_THRESHOLD and ratio < 1.0:
                logger.warning(
                    "Sandbox %s approaching memory limit: %dMB/%dMB",
                    sandbox_id, memory_mb, self.quota.max_memory_mb,
                )

    def record_storage_usage(self, sandbox_id: str, storage_bytes: int) -> None:
        """Record current storage usage for a sandbox."""
        with self._lock:
            usage = self._resource_usage.setdefault(sandbox_id, {
                "memory_mb": 0,
                "storage_bytes": 0,
                "cpu_seconds": 0,
                "network_egress_bytes": 0,
            })
            usage["storage_bytes"] = storage_bytes
            ratio = storage_bytes / self.quota.max_storage_bytes
            if ratio >= QUOTA_WARNING_THRESHOLD and ratio < 1.0:
                logger.warning(
                    "Sandbox %s approaching storage limit: %d/%d bytes",
                    sandbox_id, storage_bytes, self.quota.max_storage_bytes,
                )

    def get_usage(self, sandbox_id: str) -> dict:
        """Return current usage stats for a specific sandbox."""
        with self._lock:
            usage = self._resource_usage.get(sandbox_id, {})
            now = time.time()
            window = now - 3600
            timestamps = self._counters.get(sandbox_id, [])
            executions = sum(1 for t in timestamps if t >= window)
            return {
                "sandbox_id": sandbox_id,
                "executions_this_hour": executions,
                "memory_mb": usage.get("memory_mb", 0),
                "storage_bytes": usage.get("storage_bytes", 0),
                "cpu_seconds": usage.get("cpu_seconds", 0),
                "network_egress_bytes": usage.get("network_egress_bytes", 0),
            }

    def get_all_usage(self) -> dict:
        """Return aggregate usage stats across all sandboxes."""
        with self._lock:
            now = time.time()
            window = now - 3600
            total_executions = 0
            for timestamps in self._counters.values():
                total_executions += sum(1 for t in timestamps if t >= window)

            total_memory = 0
            total_storage = 0
            total_cpu = 0
            total_network = 0
            for usage in self._resource_usage.values():
                total_memory += usage.get("memory_mb", 0)
                total_storage += usage.get("storage_bytes", 0)
                total_cpu += usage.get("cpu_seconds", 0)
                total_network += usage.get("network_egress_bytes", 0)

            return {
                "active_sandboxes": len(self._active_sandboxes),
                "total_executions_this_hour": total_executions,
                "total_memory_mb": total_memory,
                "total_storage_bytes": total_storage,
                "total_cpu_seconds": total_cpu,
                "total_network_egress_bytes": total_network,
            }

    def check_resource_limits(self, sandbox_id: str) -> list[str]:
        """Return a list of violated quota names for a sandbox. Empty means all good."""
        violations = []
        with self._lock:
            usage = self._resource_usage.get(sandbox_id, {})

            if usage.get("memory_mb", 0) > self.quota.max_memory_mb:
                violations.append("max_memory_mb")

            if usage.get("storage_bytes", 0) > self.quota.max_storage_bytes:
                violations.append("max_storage_bytes")

            if usage.get("cpu_seconds", 0) > self.quota.max_cpu_seconds_per_hour:
                violations.append("max_cpu_seconds_per_hour")

            if usage.get("network_egress_bytes", 0) > self.quota.max_network_egress_bytes_per_hour:
                violations.append("max_network_egress_bytes_per_hour")

            now = time.time()
            window = now - 3600
            timestamps = self._counters.get(sandbox_id, [])
            executions = sum(1 for t in timestamps if t >= window)
            if executions > self.quota.max_executions_per_hour:
                violations.append("max_executions_per_hour")

            if len(self._active_sandboxes) > self.quota.max_concurrent_sandboxes:
                violations.append("max_concurrent_sandboxes")

        return violations