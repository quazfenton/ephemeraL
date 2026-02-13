"""Pluggable container runtime abstraction with Firecracker and process backends."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import subprocess
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from container_fallback import ContainerFallback


@dataclass
class ResourceLimits:
    vcpu_count: int = 1
    mem_size_mib: int = 512
    disk_size_mib: int = 1024


@dataclass
class ContainerInfo:
    sandbox_id: str
    workspace_path: Path
    ip_address: Optional[str]
    created_at: float


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int


class ContainerRuntime(ABC):
    """Abstract base for pluggable container runtimes."""

    @abstractmethod
    async def create(
        self,
        sandbox_id: str,
        image: str,
        resource_limits: Optional[ResourceLimits] = None,
    ) -> ContainerInfo:
        ...

    @abstractmethod
    async def start(self, sandbox_id: str) -> bool:
        ...

    @abstractmethod
    async def stop(self, sandbox_id: str) -> bool:
        ...

    @abstractmethod
    async def destroy(self, sandbox_id: str) -> bool:
        ...

    @abstractmethod
    async def status(self, sandbox_id: str) -> str:
        ...

    @abstractmethod
    async def exec_command(
        self,
        sandbox_id: str,
        command: str,
        args: Optional[List[str]] = None,
        timeout: Optional[int] = None,
    ) -> ExecResult:
        ...


class FirecrackerRuntime(ContainerRuntime):
    """Firecracker microVM-based runtime.

    Requires the ``firecracker`` binary on ``$PATH`` or at
    ``firecracker_bin``.  Each sandbox gets its own API socket under
    ``socket_dir`` and a workspace directory under ``workspace_root``.
    """

    def __init__(
        self,
        firecracker_bin: str = "firecracker",
        kernel_image: str = "/opt/firecracker/vmlinux",
        socket_dir: str = "/tmp/firecracker/sockets",
        workspace_root: str = "/tmp/firecracker/workspaces",
    ) -> None:
        self._bin = firecracker_bin
        self._kernel_image = kernel_image
        self._socket_dir = Path(socket_dir)
        self._workspace_root = Path(workspace_root)
        self._vms: Dict[str, _VMState] = {}

        self._socket_dir.mkdir(parents=True, exist_ok=True)
        self._workspace_root.mkdir(parents=True, exist_ok=True)

    # -- internal helpers -----------------------------------------------------

    def _socket_path(self, sandbox_id: str) -> Path:
        return self._socket_dir / f"{sandbox_id}.sock"

    async def _api_call(
        self, sandbox_id: str, method: str, path: str, body: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Send a request to a Firecracker VM's API socket over HTTP-over-Unix."""
        sock_path = self._socket_path(sandbox_id)
        payload = json.dumps(body) if body else ""
        content_length = len(payload.encode())

        request_lines = [
            f"{method} {path} HTTP/1.1",
            "Host: localhost",
            "Accept: application/json",
            f"Content-Type: application/json",
            f"Content-Length: {content_length}",
            "",
            payload,
        ]
        raw_request = "\r\n".join(request_lines).encode()

        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        try:
            writer.write(raw_request)
            await writer.drain()
            response = await asyncio.wait_for(reader.read(65536), timeout=10)
        finally:
            writer.close()
            await writer.wait_closed()

        # Parse a minimal HTTP response: status line + body after blank line.
        text = response.decode(errors="ignore")
        parts = text.split("\r\n\r\n", 1)
        status_line = parts[0].split("\r\n")[0] if parts else ""
        resp_body = parts[1] if len(parts) > 1 else ""

        status_code = int(status_line.split(" ", 2)[1]) if " " in status_line else 0
        try:
            data = json.loads(resp_body) if resp_body.strip() else {}
        except json.JSONDecodeError:
            data = {"raw": resp_body}

        return {"status_code": status_code, "body": data}

    async def _start_firecracker_process(self, sandbox_id: str) -> asyncio.subprocess.Process:
        sock = self._socket_path(sandbox_id)
        if sock.exists():
            sock.unlink()
        proc = await asyncio.create_subprocess_exec(
            self._bin,
            "--api-sock",
            str(sock),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        # Give the process a moment to open the socket.
        await asyncio.sleep(0.3)
        return proc

    # -- ContainerRuntime interface -------------------------------------------

    async def create(
        self,
        sandbox_id: str,
        image: str,
        resource_limits: Optional[ResourceLimits] = None,
    ) -> ContainerInfo:
        limits = resource_limits or ResourceLimits()
        workspace = self._workspace_root / sandbox_id
        workspace.mkdir(parents=True, exist_ok=True)

        proc = await self._start_firecracker_process(sandbox_id)

        # Configure the VM via Firecracker's REST API.
        await self._api_call(sandbox_id, "PUT", "/machine-config", {
            "vcpu_count": limits.vcpu_count,
            "mem_size_mib": limits.mem_size_mib,
        })
        await self._api_call(sandbox_id, "PUT", "/boot-source", {
            "kernel_image_path": self._kernel_image,
            "boot_args": "console=ttyS0 reboot=k panic=1 pci=off",
        })
        await self._api_call(sandbox_id, "PUT", "/drives/rootfs", {
            "drive_id": "rootfs",
            "path_on_host": image,
            "is_root_device": True,
            "is_read_only": False,
        })

        created_at = time.time()
        info = ContainerInfo(
            sandbox_id=sandbox_id,
            workspace_path=workspace,
            ip_address=None,
            created_at=created_at,
        )
        self._vms[sandbox_id] = _VMState(
            info=info,
            process=proc,
            limits=limits,
            started=False,
        )
        return info

    async def start(self, sandbox_id: str) -> bool:
        vm = self._vms.get(sandbox_id)
        if vm is None:
            return False
        resp = await self._api_call(sandbox_id, "PUT", "/actions", {
            "action_type": "InstanceStart",
        })
        vm.started = resp.get("status_code", 0) < 300
        return vm.started

    async def stop(self, sandbox_id: str) -> bool:
        vm = self._vms.get(sandbox_id)
        if vm is None:
            return False
        resp = await self._api_call(sandbox_id, "PUT", "/actions", {
            "action_type": "SendCtrlAltDel",
        })
        vm.started = False
        return resp.get("status_code", 0) < 300

    async def destroy(self, sandbox_id: str) -> bool:
        vm = self._vms.pop(sandbox_id, None)
        if vm is None:
            return False
        if vm.process.returncode is None:
            vm.process.terminate()
            try:
                await asyncio.wait_for(vm.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                vm.process.kill()
        sock = self._socket_path(sandbox_id)
        if sock.exists():
            sock.unlink()
        if vm.info.workspace_path.exists():
            shutil.rmtree(vm.info.workspace_path)
        return True

    async def status(self, sandbox_id: str) -> str:
        vm = self._vms.get(sandbox_id)
        if vm is None:
            return "not_found"
        if vm.process.returncode is not None:
            return "stopped"
        return "running" if vm.started else "created"

    async def exec_command(
        self,
        sandbox_id: str,
        command: str,
        args: Optional[List[str]] = None,
        timeout: Optional[int] = None,
    ) -> ExecResult:
        """Execute a command in the VM via SSH over virtio-vsock.

        A production deployment should configure a vsock guest agent or
        SSH server inside the guest image.  This implementation shells
        out to ``ssh`` targeting the VM's IP address.
        """
        vm = self._vms.get(sandbox_id)
        if vm is None:
            return ExecResult(stdout="", stderr="VM not found", exit_code=1)

        ip = vm.info.ip_address
        if ip is None:
            return ExecResult(stdout="", stderr="VM has no IP address assigned", exit_code=1)

        full_cmd = [command] + (args or [])
        ssh_cmd = [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            f"root@{ip}",
            "--",
            *full_cmd,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *ssh_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout or 15
            )
            return ExecResult(
                stdout=stdout.decode(errors="ignore"),
                stderr=stderr.decode(errors="ignore"),
                exit_code=proc.returncode or 0,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ExecResult(stdout="", stderr="Execution timed out", exit_code=-1)


class ProcessRuntime(ContainerRuntime):
    """Filesystem-based runtime wrapping :class:`ContainerFallback`."""

    def __init__(
        self,
        base_workspace_dir: str = "/tmp/workspaces",
        base_snapshot_dir: str = "/tmp/snapshots",
    ) -> None:
        self._fallback = ContainerFallback(
            base_workspace_dir=base_workspace_dir,
            base_snapshot_dir=base_snapshot_dir,
        )
        self._containers: Dict[str, ContainerInfo] = {}

    async def create(
        self,
        sandbox_id: str,
        image: str,
        resource_limits: Optional[ResourceLimits] = None,
    ) -> ContainerInfo:
        loop = asyncio.get_event_loop()
        ok = await loop.run_in_executor(
            None, self._fallback.create_container, sandbox_id, image
        )
        if not ok:
            raise RuntimeError(f"Failed to create container for {sandbox_id}")
        workspace = self._fallback._get_workspace_path(sandbox_id)
        info = ContainerInfo(
            sandbox_id=sandbox_id,
            workspace_path=workspace,
            ip_address="127.0.0.1",
            created_at=time.time(),
        )
        self._containers[sandbox_id] = info
        return info

    async def start(self, sandbox_id: str) -> bool:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._fallback.start_container, sandbox_id
        )

    async def stop(self, sandbox_id: str) -> bool:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._fallback.stop_container, sandbox_id
        )

    async def destroy(self, sandbox_id: str) -> bool:
        self._containers.pop(sandbox_id, None)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._fallback.remove_container, sandbox_id
        )

    async def status(self, sandbox_id: str) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._fallback.container_status, sandbox_id
        )

    async def exec_command(
        self,
        sandbox_id: str,
        command: str,
        args: Optional[List[str]] = None,
        timeout: Optional[int] = None,
    ) -> ExecResult:
        info = self._containers.get(sandbox_id)
        if info is None:
            return ExecResult(stdout="", stderr="Container not found", exit_code=1)
        full_cmd = [command] + (args or [])
        try:
            proc = await asyncio.create_subprocess_exec(
                *full_cmd,
                cwd=str(info.workspace_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout or 15
            )
            return ExecResult(
                stdout=stdout.decode(errors="ignore"),
                stderr=stderr.decode(errors="ignore"),
                exit_code=proc.returncode or 0,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return ExecResult(stdout="", stderr="Execution timed out", exit_code=-1)


def _firecracker_available(bin_name: str = "firecracker") -> bool:
    """Return True if the firecracker binary is on $PATH."""
    return shutil.which(bin_name) is not None


def create_runtime(backend: str = "auto") -> ContainerRuntime:
    """Factory that returns the best available runtime.

    * ``"firecracker"`` — always use :class:`FirecrackerRuntime`.
    * ``"process"`` — always use :class:`ProcessRuntime`.
    * ``"auto"`` (default) — use Firecracker when available, otherwise
      fall back to :class:`ProcessRuntime`.
    """
    if backend == "firecracker" or (backend == "auto" and _firecracker_available()):
        return FirecrackerRuntime()
    return ProcessRuntime()


# -- private helpers ----------------------------------------------------------

@dataclass
class _VMState:
    info: ContainerInfo
    process: asyncio.subprocess.Process
    limits: ResourceLimits
    started: bool
