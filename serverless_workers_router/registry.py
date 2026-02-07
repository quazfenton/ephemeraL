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
        """
        Selects the active URL for this preview target.

        Returns:
            The fallback URL when fallback is active (`use_fallback` is True), otherwise the primary backend URL.
        """
        if self.use_fallback and self.fallback_url:
            return self.fallback_url
        return self.backend_url


class HealthChecker:
    def __init__(self, client: httpx.AsyncClient, timeout: float = 2.0) -> None:
        """
        Initializes the HealthChecker with an httpx.AsyncClient and a request timeout.
        
        Parameters:
            timeout (float): Maximum time in seconds to wait for each health-check request (default 2.0).
        """
        self.client = client
        self.timeout = timeout

    async def is_healthy(self, url: str) -> bool:
        """
        Check whether the given URL responds successfully to an HTTP OPTIONS request.
        
        Parameters:
            url (str): The URL to probe.
        
        Returns:
            bool: True if the response status code is between 200 and 399, False otherwise.
        """
        try:
            response = await self.client.options(url, timeout=self.timeout)
            return 200 <= response.status_code < 400
        except Exception:
            return False


class PreviewRegistry:
    def __init__(self, health_checker: HealthChecker) -> None:
        """
        Initialize the registry for managing preview targets and health checks.
        
        Initializes an empty target mapping, an asyncio lock for synchronized access, and stores the provided HealthChecker for performing health checks.
        
        Parameters:
            health_checker (HealthChecker): The HealthChecker instance used to verify target health.
        """
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
        """
        Create and store a PreviewTarget for the given sandbox and port.
        
        The backend_url is normalized by removing any trailing slash before being stored.
        
        Parameters:
            sandbox_id (str): Identifier of the sandbox.
            port (int): Port number for the preview target.
            backend_url (str): Primary backend URL for the target; trailing slash will be removed.
            metadata (Optional[Dict[str, Any]]): Arbitrary metadata to associate with the target.
        
        Returns:
            PreviewTarget: The created or updated PreviewTarget instance stored in the registry.
        """
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
        """
        Retrieve a registered PreviewTarget by sandbox ID and port.
        
        Returns:
            The matching PreviewTarget if present, `None` otherwise.
        """
        key = (sandbox_id, port)
        async with self._lock:
            return self._targets.get(key)

    async def mark_fallback(self, sandbox_id: str, port: int, fallback_url: str) -> None:
        """
        Activate a fallback URL for a registered preview target.
        
        If a target identified by sandbox_id and port exists, set its fallback_url (trimming any trailing slash),
        mark it to use the fallback, and update last_health_check to the current time. No action is taken if the target is not found.
        This update is performed under the registry's lock.
        Parameters:
            sandbox_id (str): Identifier of the sandbox owning the target.
            port (int): Port number of the target.
            fallback_url (str): Fallback backend URL to use; trailing slash will be removed.
        """
        key = (sandbox_id, port)
        async with self._lock:
            target = self._targets.get(key)
            if not target:
                return
            target.fallback_url = fallback_url.rstrip('/')
            target.use_fallback = True
            target.last_health_check = time.time()

    async def reset_fallback(self, sandbox_id: str, port: int) -> None:
        """
        Deactivate any active fallback for the preview target identified by sandbox_id and port.
        
        If the target exists, this clears its fallback URL, disables fallback usage, and updates the target's last_health_check to the current time. If the target does not exist, no action is taken.
        
        Parameters:
            sandbox_id (str): Identifier of the sandbox containing the target.
            port (int): Port number of the target within the sandbox.
        """
        key = (sandbox_id, port)
        async with self._lock:
            target = self._targets.get(key)
            if not target:
                return
            target.use_fallback = False
            target.fallback_url = None
            target.last_health_check = time.time()

    async def health_check_needed(self, target: PreviewTarget) -> bool:
        """
        Determine whether a health check should be performed for the given preview target.
        
        Parameters:
            target (PreviewTarget): The preview target whose `last_health_check` (POSIX timestamp) is compared to the current time.
        
        Returns:
            `true` if more than 5 seconds have passed since `target.last_health_check`, `false` otherwise.
        """
        now = time.time()
        return now - target.last_health_check > 5

    async def ensure_primary_healthy(self, target: PreviewTarget) -> bool:
        """
        Determine whether the target's primary backend should be considered healthy, performing a health check if required.
        
        If the target is currently using a fallback, this returns `False`. If a health check is needed (based on the target's last health check timestamp), a health probe is performed and `target.last_health_check` is updated with the current time; the probe result is returned. If no health check is needed, the function returns `True` (the primary is assumed healthy).
        
        Parameters:
            target (PreviewTarget): The preview target to evaluate; `last_health_check` will be updated when a health probe is performed.
        
        Returns:
            bool: `True` if the primary backend is considered healthy, `False` otherwise.
        """
        if target.use_fallback:
            return False
        if await self.health_check_needed(target):
            healthy = await self._health_checker.is_healthy(target.effective_url)
            target.last_health_check = time.time()
            return healthy
        return True

    async def list_targets(self) -> Dict[Tuple[str, int], PreviewTarget]:
        """
        Return a shallow, thread-safe snapshot of all registered preview targets keyed by (sandbox_id, port).
        
        The snapshot is created under the registry's lock to provide a consistent view without exposing the internal mapping for mutation.
        
        Returns:
            targets (Dict[Tuple[str, int], PreviewTarget]): A shallow copy of the internal targets mapping.
        """
        async with self._lock:
            return dict(self._targets)