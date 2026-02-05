from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

import httpx


@dataclass
class PreviewTarget:
    sandbox_id: str
    port: int
    backend_url: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    fallback_url: Optional[str] = None
    use_fallback: bool = False
    last_health_check: float = field(default_factory=time.time)

    @property
    def effective_url(self) -> str:
        return self.fallback_url if self.use_fallback else self.backend_url


class HealthChecker:
    def __init__(self, client: httpx.AsyncClient, timeout: float = 2.0) -> None:
        self.client = client
        self.timeout = timeout

    async def is_healthy(self, url: str) -> bool:
        try:
            response = await self.client.options(url, timeout=self.timeout)
            return 200 <= response.status_code < 400
        except Exception:
            return False


class PreviewRegistry:
    def __init__(self, health_checker: HealthChecker) -> None:
        self._targets: Dict[Tuple[str, int], PreviewTarget] = {}
        self._lock = asyncio.Lock()
        self._health_checker = health_checker

    async def register(
        self,
        sandbox_id: str,
        port: int,
        backend_url: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PreviewTarget:
        key = (sandbox_id, port)
        target = PreviewTarget(
            sandbox_id=sandbox_id,
            port=port,
            backend_url=backend_url.rstrip('/'),
            metadata=metadata or {},
        )
        async with self._lock:
            self._targets[key] = target
        return target

    async def resolve(self, sandbox_id: str, port: int) -> Optional[PreviewTarget]:
        key = (sandbox_id, port)
        async with self._lock:
            return self._targets.get(key)

    async def mark_fallback(self, sandbox_id: str, port: int, fallback_url: str) -> None:
        key = (sandbox_id, port)
        async with self._lock:
            target = self._targets.get(key)
            if not target:
                return
            target.fallback_url = fallback_url.rstrip('/')
            target.use_fallback = True
            target.last_health_check = time.time()

    async def reset_fallback(self, sandbox_id: str, port: int) -> None:
        key = (sandbox_id, port)
        async with self._lock:
            target = self._targets.get(key)
            if not target:
                return
            target.use_fallback = False
            target.fallback_url = None
            target.last_health_check = time.time()

    async def health_check_needed(self, target: PreviewTarget) -> bool:
        now = time.time()
        return now - target.last_health_check > 5

    async def ensure_primary_healthy(self, target: PreviewTarget) -> bool:
        if target.use_fallback:
            return False
        if await self.health_check_needed(target):
            healthy = await self._health_checker.is_healthy(target.effective_url)
            target.last_health_check = time.time()
            return healthy
        return True

    async def list_targets(self) -> Dict[Tuple[str, int], PreviewTarget]:
        async with self._lock:
            return dict(self._targets)
