"""Serverless sandbox control API."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Path as FastAPIPath
from pydantic import BaseModel

from serverless_workers_sdk.background import BackgroundExecutor
from serverless_workers_sdk.preview import PreviewRegistrar
from serverless_workers_sdk.runtime import SandboxManager
from serverless_workers_sdk.virtual_fs import VirtualFS

app = FastAPI(title="Sandbox Control API", version="1.0")
manager = SandboxManager()
preview = PreviewRegistrar()
backgrounds = BackgroundExecutor(manager)


class SandboxCreateRequest(BaseModel):
    sandbox_id: Optional[str] = None


class ExecRequest(BaseModel):
    command: str
    args: Optional[list[str]] = None
    code: Optional[str] = None
    timeout: Optional[int] = None
    requires_native: bool = False


class FileWriteRequest(BaseModel):
    path: str
    data: str


class PreviewRequest(BaseModel):
    port: int


class MountRequest(BaseModel):
    alias: str
    target: str


class BackgroundRequest(BaseModel):
    command: str
    args: Optional[list[str]] = None
    interval: int = 5


@app.post("/sandboxes")
async def create_sandbox(payload: SandboxCreateRequest):
    """
    Create a new sandbox workspace.
    
    Parameters:
        payload (SandboxCreateRequest): Request payload; may include an optional `sandbox_id` to use for the new sandbox.
    
    Returns:
        dict: A mapping with keys `sandbox_id` (the created sandbox's identifier) and `workspace` (the workspace path as a string).
    """
    sandbox = await manager.create_sandbox(payload.sandbox_id)
    return {"sandbox_id": sandbox.sandbox_id, "workspace": str(sandbox.workspace)}


@app.post("/sandboxes/{sandbox_id}/exec")
async def exec_command(sandbox_id: str, payload: ExecRequest):
    """
    Execute a command inside the specified sandbox.
    
    Parameters:
        sandbox_id (str): Identifier of the target sandbox.
        payload (ExecRequest): Execution request containing the command, optional arguments, optional inline code, optional timeout, and optional native requirement.
    
    Returns:
        dict: Execution result describing the command outcome (for example, output, error output, exit status, and any execution metadata).
    
    Raises:
        HTTPException: If the specified sandbox does not exist (404).
    """
    try:
        result = await manager.exec_command(
            sandbox_id=sandbox_id,
            command=payload.command,
            args=payload.args,
            code=payload.code,
            timeout=payload.timeout,
            requires_native=payload.requires_native,
        )
        return result
    except KeyError:
        raise HTTPException(status_code=404, detail="Sandbox not found")


@app.post("/sandboxes/{sandbox_id}/files")
async def write_file(sandbox_id: str, payload: FileWriteRequest):
    """
    Write a UTF-8 string into a file inside the specified sandbox.
    
    Parameters:
        sandbox_id (str): Identifier of the target sandbox.
        payload (FileWriteRequest): Request payload containing `path` (destination path within the sandbox) and `data` (string content to write).
    
    Returns:
        dict: {"success": True} on successful write.
    
    Raises:
        HTTPException: 404 if the sandbox does not exist.
        HTTPException: 400 if the provided path or data are invalid.
    """
    try:
        sandbox = await manager.get_sandbox(sandbox_id)
        sandbox.fs.write(payload.path, payload.data.encode())
        return {"success": True}
    except KeyError:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/sandboxes/{sandbox_id}/files")
async def list_files(sandbox_id: str, path: Optional[str] = ""):
    """
    List entries in a sandbox directory.
    
    Parameters:
        sandbox_id (str): Identifier of the sandbox to inspect.
        path (str): Path inside the sandbox to list; empty string refers to the sandbox root.
    
    Returns:
        dict: A mapping with key `"entries"` containing the directory entries returned by the sandbox filesystem.
    """
    try:
        sandbox = await manager.get_sandbox(sandbox_id)
        return {"entries": sandbox.fs.list_dir(path)}
    except KeyError:
        raise HTTPException(status_code=404, detail="Sandbox not found")


@app.get("/sandboxes/{sandbox_id}/files/{file_path:path}")
async def read_file(sandbox_id: str, file_path: str = FastAPIPath(...)):
    """
    Read a file's contents from a sandbox's virtual filesystem.
    
    Parameters:
        sandbox_id (str): ID of the sandbox to read from.
        file_path (str): Path of the file inside the sandbox.
    
    Returns:
        dict: Dictionary with key "content" containing the file content decoded to a string (decoding errors ignored).
    
    Raises:
        HTTPException: 404 with detail "Sandbox not found" if the sandbox does not exist, or 404 with detail "File not found" if the file does not exist.
    """
    try:
        sandbox = await manager.get_sandbox(sandbox_id)
        content = sandbox.fs.read(file_path)
        return {"content": content.decode(errors="ignore")}
    except KeyError:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")


@app.post("/sandboxes/{sandbox_id}/preview")
async def register_preview(sandbox_id: str, payload: PreviewRequest):
    """
    Register a network preview for the specified sandbox and return its public URL.
    
    Registers a preview backend listening on the provided port and records the resulting public URL with the sandbox manager.
    
    Parameters:
        sandbox_id (str): Identifier of the sandbox to attach the preview to.
        payload (PreviewRequest): Request containing the `port` to expose for the preview.
    
    Returns:
        dict: Dictionary with key `"url"` containing the public preview URL.
    
    Raises:
        HTTPException: Raises a 404 error if the sandbox is not found.
    """
    try:
        await manager.get_sandbox(sandbox_id)  # verify sandbox exists
        backend = f"http://127.0.0.1:{payload.port}"
        url = await preview.register(sandbox_id, payload.port, backend)
        await manager.register_preview(sandbox_id, payload.port, url)
        return {"url": url}
    except KeyError:
        raise HTTPException(status_code=404, detail="Sandbox not found")


@app.post("/sandboxes/{sandbox_id}/keepalive")
async def keep_alive(sandbox_id: str):
    """
    Mark the sandbox identified by `sandbox_id` as active to prevent expiration.
    
    Returns:
        dict: `{"status": "ok"}` when the sandbox was successfully marked active.
    
    Raises:
        HTTPException: with status code 404 if the sandbox does not exist.
    """
    try:
        await manager.keep_alive(sandbox_id)
        return {"status": "ok"}
    except KeyError:
        raise HTTPException(status_code=404, detail="Sandbox not found")


@app.post("/sandboxes/{sandbox_id}/mount")
async def mount_path(sandbox_id: str, payload: MountRequest):
    """
    Mounts a host filesystem path into the specified sandbox under the provided alias.

    Parameters:
        sandbox_id (str): Identifier of the target sandbox.
        payload (MountRequest): Mount specification; `alias` is the mount name inside the sandbox,
                               `target` is the host path to mount. Only paths under the configured
                               safe base directory are allowed.

    Returns:
        result (dict): Dictionary with key `success` set to `True` on successful mount.

    Raises:
        HTTPException: 404 if the sandbox does not exist.
        HTTPException: 403 if the mount target is outside the allowed base directory.
        HTTPException: 404 if the mount target is missing.
    """
    try:
        target = Path(payload.target).resolve()
        safe_base = Path("/sandbox/mounts").resolve()

        if not target.is_relative_to(safe_base):
            raise HTTPException(
                status_code=403,
                detail="Mount target must be under the allowed base directory"
            )

        await manager.mount(sandbox_id, payload.alias, target)
        return {"success": True}
    except KeyError:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Mount target missing")


@app.post("/sandboxes/{sandbox_id}/background")
async def start_background(sandbox_id: str, payload: BackgroundRequest):
    """
    Start a repeating background job in the specified sandbox.
    
    Parameters:
        sandbox_id (str): ID of the sandbox to run the job in.
        payload (BackgroundRequest): Job configuration including `command`, optional `args`, and `interval`.
    
    Returns:
        dict: {"job_id": "<job id>"} containing the identifier of the started background job.
    
    Raises:
        HTTPException: with status code 404 if the sandbox is not found.
    """
    try:
        job = await backgrounds.start_job(
            sandbox_id=sandbox_id,
            command=payload.command,
            args=payload.args,
            interval=payload.interval,
        )
        return {"job_id": job.job_id}
    except KeyError:
        raise HTTPException(status_code=404, detail="Sandbox not found")


@app.delete("/sandboxes/{sandbox_id}/background/{job_id}")
async def stop_background(sandbox_id: str, job_id: str):
    """
    Stop a running background job for the given sandbox.
    
    Parameters:
        sandbox_id (str): Identifier of the sandbox that owns the background job.
        job_id (str): Identifier of the background job to stop.
    
    Returns:
        dict: `{"stopped": True}` when the job was successfully stopped.
    
    Raises:
        HTTPException: 404 if the specified job was not found.
    """
    success = await backgrounds.stop_job(sandbox_id, job_id)
    if not success:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"stopped": True}


@app.on_event("shutdown")
async def shutdown_event():
    """
    Close the preview registrar and background executor, releasing their associated resources when the application shuts down.

    This is executed as the FastAPI shutdown event handler to ensure all resources are cleanly closed.
    """
    # Stop all background jobs
    await backgrounds.shutdown()
    
    # Close the preview registrar
    await preview.close()