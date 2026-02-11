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


from dataclasses import dataclass, field

@dataclass
class FallbackProcess:
    sandbox_id: str
    port: int
    process: subprocess.Popen
    workspace: Path
    stdout: Optional[TextIO]
    stderr: Optional[TextIO]
    started_at: float = field(default_factory=time.time)


class PortAllocator:
    def __init__(self, start: int = 33000, end: int = 33999) -> None:
        """
        Initialize the port allocator with a configurable inclusive port range and prepare it for concurrent async allocation.

        Parameters:
            start (int): First port in the inclusive allocation range (default 33000).
            end (int): Last port in the inclusive allocation range (default 33999). Must be greater than or equal to `start`.
        """
        self._start = start
        self._end = end
        self._current = start
        self._allocated_ports = set()
        self._lock = asyncio.Lock()

    async def allocate(self) -> int:
        """
        Allocate the next available port from the configured range, advancing the allocator and wrapping to the start when the end is exceeded.

        Returns:
            port (int): Allocated port number.
        """
        async with self._lock:
            # Find an unallocated port in the range
            original_start = self._current
            while self._current <= self._end:
                if self._current not in self._allocated_ports:
                    self._allocated_ports.add(self._current)
                    port = self._current
                    self._current += 1
                    return port
                self._current += 1
            
            # Wrap around if needed
            if self._current > self._end:
                self._current = self._start
                while self._current < original_start:
                    if self._current not in self._allocated_ports:
                        self._allocated_ports.add(self._current)
                        port = self._current
                        self._current += 1
                        return port
                    self._current += 1
            
            # If all ports are allocated, raise an exception
            raise RuntimeError("All ports in the range are allocated")

    def release(self, port: int) -> None:
        """
        Release an allocated port so it can be reused.

        Parameters:
            port (int): The port number to release.
        """
        if self._start <= port <= self._end:
            self._allocated_ports.discard(port)


class FallbackOrchestrator:
    def __init__(
        self,
        workspace_dir: str = "/tmp/workspaces",
        snapshot_dir: str = "/tmp/snapshots",
        port_allocator: Optional[PortAllocator] = None,
    ) -> None:
        """
        Initialize a FallbackOrchestrator with workspace/snapshot directories and a port allocator.
        
        Parameters:
            workspace_dir (str): Base directory where per-sandbox workspaces will be created.
            snapshot_dir (str): Base directory where sandbox snapshots are stored.
            port_allocator (Optional[PortAllocator]): Optional custom PortAllocator to use for serving ports; a default allocator is created if omitted.
        """
        self.container = ContainerFallback(
            base_workspace_dir=workspace_dir,
            base_snapshot_dir=snapshot_dir,
        )
        self.port_allocator = port_allocator or PortAllocator()
        self._processes: Dict[str, FallbackProcess] = {}
        self._lock = asyncio.Lock()

    async def promote_to_container(self, sandbox_id: str) -> str:
        """
        Ensure a container-backed HTTP server is running for the given sandbox and return its public URL.
        
        If an active fallback process already exists for the sandbox, its URL is returned. Otherwise this method creates and starts the container workspace (if needed), allocates a port, launches a local Python HTTP server subprocess bound to 127.0.0.1, and records stdout/stderr logs for the fallback process.
        
        Parameters:
            sandbox_id (str): Identifier of the sandbox to promote.
        
        Returns:
            url (str): HTTP URL (e.g., "http://127.0.0.1:<port>") where the promoted sandbox is served.
        """
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
            try:
                process = subprocess.Popen(
                    cmd,
                    cwd=str(workspace),
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    env={**os.environ, "PYTHONUNBUFFERED": "1"},
                    start_new_session=True,
                )
            except Exception:
                stdout_handle.close()
                stderr_handle.close()
                raise

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
        """
        Stop and clean up the container-backed HTTP server for a sandbox.

        If a tracked fallback process for the given sandbox exists and is running, terminate it (wait up to 5 seconds, then kill if it doesn't exit), close its stdout/stderr handles to flush logs, and instruct the container manager to stop the container. If no process is tracked for the sandbox, the call is a no-op.

        Parameters:
            sandbox_id (str): Identifier of the sandbox whose container and associated process should be stopped.
        """
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
            # Release the port back to the allocator
            self.port_allocator.release(info.port) if info else None
            self.container.stop_container(sandbox_id)

    async def cleanup_stale(self) -> None:
        """
        Remove tracked fallback processes that have exited and stop their containers.

        Acquires the orchestrator's internal lock, scans the current process map, removes entries whose subprocess has finished, and invokes the container manager to stop the corresponding sandbox containers.
        """
        async with self._lock:
            for sandbox_id, info in list(self._processes.items()):
                if info.process.poll() is not None:
                    # Close file handles to prevent file descriptor leaks
                    if info.stdout:
                        info.stdout.close()
                    if info.stderr:
                        info.stderr.close()

                    # Release the port back to the allocator
                    self.port_allocator.release(info.port)
                    
                    self._processes.pop(sandbox_id)
                    self.container.stop_container(sandbox_id)