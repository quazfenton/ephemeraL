from __future__ import annotations

import asyncio
import subprocess
import sys
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, TextIO

from container_fallback import ContainerFallback


@dataclass
class FallbackProcess:
    sandbox_id: str
    port: int
    process: subprocess.Popen
    workspace: Path
    stdout: Optional[TextIO]
    stderr: Optional[TextIO]
    started_at: float = time.time()


class PortAllocator:
    def __init__(self, start: int = 33000, end: int = 33999) -> None:
        self._start = start
        self._end = end
        self._current = start
        self._lock = asyncio.Lock()

    async def allocate(self) -> int:
        async with self._lock:
            if self._current > self._end:
                self._current = self._start
            port = self._current
            self._current += 1
            return port


class FallbackOrchestrator:
    def __init__(
        self,
        workspace_dir: str = "/tmp/workspaces",
        snapshot_dir: str = "/tmp/snapshots",
        port_allocator: Optional[PortAllocator] = None,
    ) -> None:
        self.container = ContainerFallback(
            base_workspace_dir=workspace_dir,
            base_snapshot_dir=snapshot_dir,
        )
        self.port_allocator = port_allocator or PortAllocator()
        self._processes: Dict[str, FallbackProcess] = {}
        self._lock = asyncio.Lock()

    async def promote_to_container(self, sandbox_id: str) -> str:
        async with self._lock:
            existing = self._processes.get(sandbox_id)
            if existing and existing.process.poll() is None:
                return f"http://127.0.0.1:{existing.port}"

            # Ensure workspace exists and is marked as running
            self.container.create_container(sandbox_id)
            self.container.start_container(sandbox_id)

            serve_port = await self.port_allocator.allocate()
            workspace = self.container._get_workspace_path(sandbox_id)
            log_dir = workspace / "logs"
            log_dir.mkdir(exist_ok=True)
            stdout_path = log_dir / "fallback_http.log"
            stderr_path = log_dir / "fallback_http.err"

            cmd = [
                sys.executable,
                "-m",
                "http.server",
                str(serve_port),
                "--bind",
                "127.0.0.1",
            ]

            stdout_handle = open(stdout_path, "a", encoding="utf-8")
            stderr_handle = open(stderr_path, "a", encoding="utf-8")
            process = subprocess.Popen(
                cmd,
                cwd=str(workspace),
                stdout=stdout_handle,
                stderr=stderr_handle,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
                start_new_session=True,
            )

            self._processes[sandbox_id] = FallbackProcess(
                sandbox_id=sandbox_id,
                port=serve_port,
                process=process,
                workspace=workspace,
                stdout=stdout_handle,
                stderr=stderr_handle,
            )

            # Give http.server time to start
            await asyncio.sleep(0.5)
            return f"http://127.0.0.1:{serve_port}"

    async def stop_container(self, sandbox_id: str) -> None:
        async with self._lock:
            info = self._processes.pop(sandbox_id, None)
            if not info:
                return
            if info.process.poll() is None:
                info.process.terminate()
                try:
                    info.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    info.process.kill()
            if info.stdout:  # close handles so they flush
                info.stdout.close()
            if info.stderr:
                info.stderr.close()
            self.container.stop_container(sandbox_id)

    async def cleanup_stale(self) -> None:
        async with self._lock:
            for sandbox_id, info in list(self._processes.items()):
                if info.process.poll() is not None:
                    self._processes.pop(sandbox_id)
                    self.container.stop_container(sandbox_id)
