"""Core sandbox runtime abstractions."""

from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from serverless_workers_router.orchestrator import FallbackOrchestrator
from serverless_workers_sdk.background import BackgroundJob
from serverless_workers_sdk.quota import QuotaManager
from serverless_workers_sdk.recorder import EventRecorder
from serverless_workers_sdk.virtual_fs import VirtualFS

SANDBOX_ROOT = Path(os.getenv("SANDBOX_ROOT", "/tmp/serverless_sandboxes"))
ALLOWED_COMMANDS = {"python", "node"}
DEFAULT_TIMEOUT = 15


@dataclass
class SandboxInstance:
    sandbox_id: str
    workspace: Path
    fs: VirtualFS
    created_at: float
    last_active: float
    keep_alive_at: float
    preview_ports: Dict[int, str] = field(default_factory=dict)
    background_jobs: Dict[str, BackgroundJob] = field(default_factory=dict)

    def touch(self) -> None:
        self.last_active = asyncio.get_event_loop().time()
        self.keep_alive_at = self.last_active

    def register_preview(self, port: int, url: str) -> None:
        self.preview_ports[port] = url
        self.touch()

    def unregister_preview(self, port: int) -> None:
        self.preview_ports.pop(port, None)
        self.touch()


class SandboxManager:
    def __init__(self, fallback: Optional[FallbackOrchestrator] = None) -> None:
        self._sandboxes: Dict[str, SandboxInstance] = {}
        self._lock = asyncio.Lock()
        self._fallback = fallback or FallbackOrchestrator()
        self._recorder = EventRecorder()
        self._quota = QuotaManager()

    async def create_sandbox(self, sandbox_id: Optional[str] = None) -> SandboxInstance:
        async with self._lock:
            sandbox_id = sandbox_id or uuid.uuid4().hex
            workspace = SANDBOX_ROOT / sandbox_id
            workspace.mkdir(parents=True, exist_ok=True)
            fs = VirtualFS(workspace)
            sandbox = SandboxInstance(
                sandbox_id=sandbox_id,
                workspace=workspace,
                fs=fs,
                created_at=asyncio.get_event_loop().time(),
                last_active=asyncio.get_event_loop().time(),
                keep_alive_at=asyncio.get_event_loop().time(),
            )
            self._sandboxes[sandbox_id] = sandbox
            await self._recorder.record("sandbox.created", sandbox_id)
            return sandbox

    async def get_sandbox(self, sandbox_id: str) -> SandboxInstance:
        sandbox = self._sandboxes.get(sandbox_id)
        if not sandbox:
            raise KeyError(f"sandbox '{sandbox_id}' not found")
        return sandbox

    async def exec_command(
        self,
        sandbox_id: str,
        command: str,
        args: Optional[List[str]] = None,
        code: Optional[str] = None,
        timeout: Optional[int] = None,
        requires_native: bool = False,
    ) -> Dict[str, Any]:
        sandbox = await self.get_sandbox(sandbox_id)
        sandbox.touch()

        if not self._quota.allow_execution(sandbox_id):
            await self._recorder.record("sandbox.exec.denied", sandbox_id, {"reason": "quota"})
            return {"error": "quota_exceeded"}

        if requires_native or command not in ALLOWED_COMMANDS:
            fallback_url = await self._fallback.promote_to_container(sandbox_id)
            await self._recorder.record("sandbox.exec.fallback", sandbox_id, {"command": command})
            return {
                "fallback_url": fallback_url,
                "message": "promoted to container fallback",
            }

        args = args or []
        cmd = [command, *args]
        if command == "python" and code:
            script_path = sandbox.workspace / "sandbox_exec.py"
            script_path.write_text(code)
            cmd = ["python", str(script_path)]
        elif code:
            script_path = sandbox.workspace / f"sandbox_exec.{command}"
            script_path.write_text(code)
            cmd = [command, str(script_path)]

        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(sandbox.workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            timeout = timeout or DEFAULT_TIMEOUT
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            stdout, stderr = b"", b""
            return {
                "stdout": stdout.decode(errors="ignore"),
                "stderr": "Execution timed out",
                "exit_code": proc.returncode,
            }

        result = {
            "stdout": stdout.decode(errors="ignore"),
            "stderr": stderr.decode(errors="ignore"),
            "exit_code": proc.returncode,
        }
        await self._recorder.record("sandbox.exec.success", sandbox_id, {"cmd": cmd})
        self._quota.record_execution(sandbox_id)
        return result

    async def keep_alive(self, sandbox_id: str) -> None:
        sandbox = await self.get_sandbox(sandbox_id)
        sandbox.keep_alive_at = asyncio.get_event_loop().time()
        await self._recorder.record("sandbox.keepalive", sandbox_id)

    async def mount(self, sandbox_id: str, alias: str, target: Path) -> None:
        sandbox = await self.get_sandbox(sandbox_id)
        sandbox.fs.mount(alias, target)
        await self._recorder.record("sandbox.mount", sandbox_id, {"alias": alias, "target": str(target)})

    async def register_preview(self, sandbox_id: str, port: int, url: str) -> None:
        sandbox = await self.get_sandbox(sandbox_id)
        sandbox.register_preview(port, url)
        await self._recorder.record("sandbox.preview.register", sandbox_id, {"port": port, "url": url})

    async def ensure_background(self, sandbox_id: str, job: BackgroundJob) -> None:
        sandbox = await self.get_sandbox(sandbox_id)
        sandbox.background_jobs[job.job_id] = job
        await self._recorder.record("sandbox.background.created", sandbox_id, {"job_id": job.job_id})

    async def remove_background(self, sandbox_id: str, job_id: str) -> None:
        sandbox = await self.get_sandbox(sandbox_id)
        job = sandbox.background_jobs.pop(job_id, None)
        if job:
            job.task.cancel()
            await self._recorder.record("sandbox.background.stopped", sandbox_id, {"job_id": job_id})
