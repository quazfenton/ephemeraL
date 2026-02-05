"""Basic quota tracking for sandbox executions."""

from __future__ import annotations

import time
from typing import Dict


class QuotaManager:
    def __init__(self, limit_per_hour: int = 120) -> None:
        self.limit_per_hour = limit_per_hour
        self._counters: Dict[str, list[float]] = {}

    def allow_execution(self, sandbox_id: str) -> bool:
        now = time.time()
        window = now - 3600
        timestamps = self._counters.setdefault(sandbox_id, [])
        # Remove expired timestamps
        while timestamps and timestamps[0] < window:
            timestamps.pop(0)
        return len(timestamps) < self.limit_per_hour

    def record_execution(self, sandbox_id: str) -> None:
        now = time.time()
        timestamps = self._counters.setdefault(sandbox_id, [])
        timestamps.append(now)
