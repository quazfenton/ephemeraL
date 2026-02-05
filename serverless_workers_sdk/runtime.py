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
        """
        Update the sandbox's activity timestamps.
        
        Sets both `last_active` and `keep_alive_at` to the current event-loop time.
        """
        self.last_active = asyncio.get_event_loop().time()
        self.keep_alive_at = self.last_active

    def register_preview(self, port: int, url: str) -> None:
        """
        Register or update a preview URL for a given local port on the sandbox.
        
        Also updates the sandbox's activity timestamps.
        
        Parameters:
            port (int): Local port number to associate with the preview.
            url (str): Preview URL to register for the given port.
        """
        self.preview_ports[port] = url
        self.touch()

    def unregister_preview(self, port: int) -> None:
        """
        Remove a registered preview for a local port and refresh the sandbox's activity timestamps.
        
        If no preview is registered for the given port, the method does nothing.
        
        Parameters:
            port (int): Local port whose preview URL mapping should be removed.
        """
        self.preview_ports.pop(port, None)
        self.touch()


class SandboxManager:
    def __init__(self, fallback: Optional[FallbackOrchestrator] = None) -> None:
        """
        Initialize a SandboxManager with optional fallback orchestration.
        
        Parameters:
            fallback (Optional[FallbackOrchestrator]): Optional orchestrator used to promote sandbox executions to containerized fallback; if omitted, a default FallbackOrchestrator is created.
        """
        self._sandboxes: Dict[str, SandboxInstance] = {}
        self._lock = asyncio.Lock()
        self._fallback = fallback or FallbackOrchestrator()
        self._recorder = EventRecorder()
        self._quota = QuotaManager()

    async def create_sandbox(self, sandbox_id: Optional[str] = None) -> SandboxInstance:
        """
        Create a new sandbox instance with a dedicated workspace and virtual filesystem.
        
        Parameters:
            sandbox_id (Optional[str]): Optional identifier to use for the sandbox. If omitted, a unique id is generated.
        
        Returns:
            SandboxInstance: The created sandbox, registered with the manager and ready for use. The workspace directory is created on disk and an event is recorded.
        """
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
        """
        Retrieve a SandboxInstance by its identifier.
        
        Returns:
            SandboxInstance: The sandbox associated with the given `sandbox_id`.
        
        Raises:
            KeyError: If no sandbox exists with the provided `sandbox_id`.
        """
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
        """
        Execute a command inside the specified sandbox and return its execution result.
        
        Parameters:
            sandbox_id (str): Identifier of the target sandbox.
            command (str): Command to run (e.g., "python", "node").
            args (Optional[List[str]]): Additional command-line arguments.
            code (Optional[str]): Source code to write into a temporary script inside the sandbox; when provided the command will run that script.
            timeout (Optional[int]): Maximum runtime in seconds before the process is terminated. Defaults to the module DEFAULT_TIMEOUT when not provided.
            requires_native (bool): If true, force promotion to a container fallback instead of running in the sandbox runtime.
        
        Returns:
            result (Dict[str, Any]): A dictionary describing the outcome. Possible shapes include:
              - On successful local execution: {"stdout": str, "stderr": str, "exit_code": int}
              - When execution is denied by quota: {"error": "quota_exceeded"}
              - When promoted to a container fallback: {"fallback_url": str, "message": str}
              - When a timeout occurs: {"stdout": str, "stderr": "Execution timed out", "exit_code": int}
        """
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
        """
        Update the sandbox's keep-alive timestamp and emit a keepalive event.
        
        Parameters:
            sandbox_id (str): Identifier of the sandbox whose keep-alive timestamp should be refreshed.
        """
        sandbox = await self.get_sandbox(sandbox_id)
        sandbox.keep_alive_at = asyncio.get_event_loop().time()
        await self._recorder.record("sandbox.keepalive", sandbox_id)

    async def mount(self, sandbox_id: str, alias: str, target: Path) -> None:
        """
        Mount a host path into the sandbox's virtual filesystem under the given alias.
        
        Parameters:
            sandbox_id (str): Identifier of the sandbox to modify.
            alias (str): Virtual mount alias or mount point name within the sandbox.
            target (Path): Host filesystem path to mount into the sandbox.
        
        Raises:
            KeyError: If no sandbox exists with the provided `sandbox_id`.
        """
        sandbox = await self.get_sandbox(sandbox_id)
        sandbox.fs.mount(alias, target)
        await self._recorder.record("sandbox.mount", sandbox_id, {"alias": alias, "target": str(target)})

    async def register_preview(self, sandbox_id: str, port: int, url: str) -> None:
        """
        Register a preview URL for a sandbox port and record the registration event.
        
        Parameters:
            sandbox_id (str): Identifier of the target sandbox.
            port (int): Local port number exposed by the sandbox to associate with the preview.
            url (str): Public URL that serves the preview for the given port.
        """
        sandbox = await self.get_sandbox(sandbox_id)
        sandbox.register_preview(port, url)
        await self._recorder.record("sandbox.preview.register", sandbox_id, {"port": port, "url": url})

    async def ensure_background(self, sandbox_id: str, job: BackgroundJob) -> None:
        """
        Register a background job with the specified sandbox and emit a creation event.
        
        Parameters:
            sandbox_id (str): Identifier of the sandbox to attach the background job to.
            job (BackgroundJob): Background job to store; its `job_id` will be used as the key.
        """
        sandbox = await self.get_sandbox(sandbox_id)
        sandbox.background_jobs[job.job_id] = job
        await self._recorder.record("sandbox.background.created", sandbox_id, {"job_id": job.job_id})

    async def remove_background(self, sandbox_id: str, job_id: str) -> None:
        """
        Stop and remove a background job from the specified sandbox.
        
        If a background job with the given job_id exists in the sandbox, its task is cancelled and a "sandbox.background.stopped" event is recorded.
        
        Raises:
            KeyError: If the sandbox with `sandbox_id` does not exist.
        """
        sandbox = await self.get_sandbox(sandbox_id)
        job = sandbox.background_jobs.pop(job_id, None)
        if job:
            job.task.cancel()
            await self._recorder.record("sandbox.background.stopped", sandbox_id, {"job_id": job_id})