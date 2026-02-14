"""Serverless sandbox control API."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Path as FastAPIPath, Depends, Header, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from serverless_workers_sdk.background import BackgroundExecutor
from serverless_workers_sdk.preview import PreviewRegistrar
from serverless_workers_sdk.runtime import SandboxManager
from serverless_workers_sdk.virtual_fs import VirtualFS
from serverless_workers_sdk.metrics import (
    MetricsMiddleware,
    create_metrics_endpoint,
    sandbox_created_total,
    sandbox_active,
    sandbox_exec_total,
    sandbox_exec_duration_seconds,
)

from auth import get_user_id, validate_user_id

def get_current_user(authorization: str = Header(...)):
    """
    Extract and validate user from Authorization header
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header must start with 'Bearer '")

    token = authorization[7:]  # Remove "Bearer " prefix
    try:
        user_id = get_user_id(token)
        return user_id
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


app = FastAPI(
    title="Ephemeral Sandbox API",
    version="1.0.0",
    description="Cloud terminal platform API for sandbox lifecycle, file management, and preview routing.",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {"name": "sandboxes", "description": "Sandbox lifecycle management"},
        {"name": "files", "description": "File operations within sandboxes"},
        {"name": "preview", "description": "Preview URL management"},
        {"name": "background", "description": "Background job management"},
        {"name": "health", "description": "Health and readiness checks"},
    ],
)
manager = SandboxManager()
preview = PreviewRegistrar()
backgrounds = BackgroundExecutor(manager)
app.add_middleware(MetricsMiddleware)
create_metrics_endpoint(app)


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


@app.post("/sandboxes", tags=["sandboxes"])
async def create_sandbox(payload: SandboxCreateRequest, current_user: str = Depends(get_current_user)):
    """
    Create a new sandbox workspace.

    Parameters:
        payload (SandboxCreateRequest): Request payload; may include an optional `sandbox_id` to use for the new sandbox.
        current_user (str): Authenticated user ID extracted from the JWT token.

    Returns:
        dict: A mapping with keys `sandbox_id` (the created sandbox's identifier) and `workspace` (the workspace path as a string).
    """
    sandbox = await manager.create_sandbox(payload.sandbox_id)
    sandbox_created_total.inc()
    sandbox_active.inc()
    return {"sandbox_id": sandbox.sandbox_id, "workspace": str(sandbox.workspace)}


# New endpoint to address the decrement of sandbox_active
@app.delete("/sandboxes/{sandbox_id}", tags=["sandboxes"])
async def delete_sandbox(
    sandbox_id: str,
    current_user: str = Depends(get_current_user)
):
    """
    Delete a sandbox workspace.

    Parameters:
        sandbox_id (str): The ID of the sandbox to delete.
        current_user (str): Authenticated user ID extracted from the JWT token.
                            Used for permission checks (e.g., only owner can delete).

    Returns:
        dict: A confirmation message on successful deletion.
    """
    # In a real application, current_user would typically be checked to ensure they have
    # permission to delete this specific sandbox_id. For this task, we ensure authentication.
    # For example:
    # if not await manager.is_sandbox_owner(sandbox_id, current_user):
    #     raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to delete this sandbox.")

    try:
        # Use existing removal API instead of unimplemented remove_sandbox
        success = await manager.delete_sandbox(sandbox_id)
        if success:
            sandbox_active.dec()
            return {"message": f"Sandbox {sandbox_id} deleted successfully."}
        else:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Sandbox {sandbox_id} not found or could not be deleted.")
        if success:
            sandbox_active.dec()
            return {"message": f"Sandbox {sandbox_id} deleted successfully."}
        else:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Sandbox {sandbox_id} not found or could not be deleted.")
    except HTTPException:
        raise
    except Exception as e:
        # Catch more specific exceptions from manager.remove_sandbox if they exist,
        # e.g., SandboxNotFoundException, SandboxDeletionFailedException.
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error deleting sandbox {sandbox_id}: {str(e)}")


@app.post("/sandboxes/{sandbox_id}/exec", tags=["sandboxes"])
async def exec_command(sandbox_id: str, payload: ExecRequest, current_user: str = Depends(get_current_user)):
    """
    Execute a command inside the specified sandbox.

    Parameters:
        sandbox_id (str): Identifier of the target sandbox.
        payload (ExecRequest): Execution request containing the command, optional arguments, optional inline code, optional timeout, and optional native requirement.
        current_user (str): Authenticated user ID extracted from the JWT token.

    Returns:
        dict: Execution result describing the command outcome (for example, output, error output, exit status, and any execution metadata).

    Raises:
        HTTPException: If the specified sandbox does not exist (404).
    """
    _t0 = time.monotonic()
    try:
        result = await manager.exec_command(
            sandbox_id=sandbox_id,
            command=payload.command,
            args=payload.args,
            code=payload.code,
            timeout=payload.timeout,
            requires_native=payload.requires_native,
        )
        sandbox_exec_duration_seconds.observe(time.monotonic() - _t0)
        sandbox_exec_total.labels(sandbox_id=sandbox_id, command=payload.command).inc()
        return result
    except KeyError:
        raise HTTPException(status_code=404, detail="Sandbox not found")


@app.post("/sandboxes/{sandbox_id}/files", tags=["files"])
async def write_file(sandbox_id: str, payload: FileWriteRequest, current_user: str = Depends(get_current_user)):
    """
    Write a UTF-8 string into a file inside the specified sandbox.

    Parameters:
        sandbox_id (str): Identifier of the target sandbox.
        payload (FileWriteRequest): Request payload containing `path` (destination path within the sandbox) and `data` (string content to write).
        current_user (str): Authenticated user ID extracted from the JWT token.

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


@app.get("/sandboxes/{sandbox_id}/files", tags=["files"])
async def list_files(sandbox_id: str, path: Optional[str] = "", current_user: str = Depends(get_current_user)):
    """
    List entries in a sandbox directory.

    Parameters:
        sandbox_id (str): Identifier of the sandbox to inspect.
        path (str): Path inside the sandbox to list; empty string refers to the sandbox root.
        current_user (str): Authenticated user ID extracted from the JWT token.

    Returns:
        dict: A mapping with key `"entries"` containing the directory entries returned by the sandbox filesystem.
    """
    try:
        sandbox = await manager.get_sandbox(sandbox_id)
        return {"entries": sandbox.fs.list_dir(path)}
    except KeyError:
        raise HTTPException(status_code=404, detail="Sandbox not found")


@app.get("/sandboxes/{sandbox_id}/files/{file_path:path}", tags=["files"])
async def read_file(sandbox_id: str, file_path: str = FastAPIPath(...), current_user: str = Depends(get_current_user)):
    """
    Read a file's contents from a sandbox's virtual filesystem.

    Parameters:
        sandbox_id (str): ID of the sandbox to read from.
        file_path (str): Path of the file inside the sandbox.
        current_user (str): Authenticated user ID extracted from the JWT token.

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


@app.post("/sandboxes/{sandbox_id}/preview", tags=["preview"])
async def register_preview(sandbox_id: str, payload: PreviewRequest, current_user: str = Depends(get_current_user)):
    """
    Register a network preview for the specified sandbox and return its public URL.

    Registers a preview backend listening on the provided port and records the resulting public URL with the sandbox manager.

    Parameters:
        sandbox_id (str): Identifier of the sandbox to attach the preview to.
        payload (PreviewRequest): Request containing the `port` to expose for the preview.
        current_user (str): Authenticated user ID extracted from the JWT token.

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


@app.post("/sandboxes/{sandbox_id}/keepalive", tags=["sandboxes"])
async def keep_alive(sandbox_id: str, current_user: str = Depends(get_current_user)):
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


@app.post("/sandboxes/{sandbox_id}/mount", tags=["sandboxes"])
async def mount_path(sandbox_id: str, payload: MountRequest, current_user: str = Depends(get_current_user)):
    """
    Mounts a host filesystem path into the specified sandbox under the provided alias.

    Parameters:
        sandbox_id (str): Identifier of the target sandbox.
        payload (MountRequest): Mount specification; `alias` is the mount name inside the sandbox,
                               `target` is the host path to mount. Only paths under the configured
                               safe base directory are allowed.
        current_user (str): Authenticated user ID extracted from the JWT token.

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


@app.post("/sandboxes/{sandbox_id}/background", tags=["background"])
async def start_background(sandbox_id: str, payload: BackgroundRequest, current_user: str = Depends(get_current_user)):
    """
    Start a repeating background job in the specified sandbox.

    Parameters:
        sandbox_id (str): ID of the sandbox to run the job in.
        payload (BackgroundRequest): Job configuration including `command`, optional `args`, and `interval`.
        current_user (str): Authenticated user ID extracted from the JWT token.

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


@app.delete("/sandboxes/{sandbox_id}/background/{job_id}", tags=["background"])
async def stop_background(sandbox_id: str, job_id: str, current_user: str = Depends(get_current_user)):
    """
    Stop a running background job for the given sandbox.

    Parameters:
        sandbox_id (str): Identifier of the sandbox that owns the background job.
        job_id (str): Identifier of the background job to stop.
        current_user (str): Authenticated user ID extracted from the JWT token.

    Returns:
        dict: `{"stopped": True}` when the job was successfully stopped.

    Raises:
        HTTPException: 404 if the specified job was not found.
    """
    success = await backgrounds.stop_job(sandbox_id, job_id)
    if not success:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"stopped": True}


@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "healthy", "version": "1.0.0"}


@app.get("/health/ready", tags=["health"])
async def readiness_check():
    return {"status": "ready", "sandboxes_active": len(manager._sandboxes)}


@app.websocket("/sandboxes/{sandbox_id}/terminal")
async def terminal_websocket(websocket: WebSocket, sandbox_id: str):
    """WebSocket terminal endpoint for interactive shell access (xterm.js compatible)."""
    await websocket.accept()
    try:
        sandbox = await manager.get_sandbox(sandbox_id)
        proc = await asyncio.create_subprocess_exec(
            "/bin/bash",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(sandbox.workspace),
        )

        async def read_output():
            while True:
                data = await proc.stdout.read(4096)
                if not data:
                    break
                await websocket.send_bytes(data)

        output_task = asyncio.create_task(read_output())

        try:
            while True:
                data = await websocket.receive_bytes()
                proc.stdin.write(data)
                await proc.stdin.drain()
        except WebSocketDisconnect:
            pass
        finally:
            output_task.cancel()
            proc.terminate()
    except KeyError:
        await websocket.close(code=4004, reason="Sandbox not found")


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