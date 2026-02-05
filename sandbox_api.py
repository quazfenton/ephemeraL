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
    sandbox = await manager.create_sandbox(payload.sandbox_id)
    return {"sandbox_id": sandbox.sandbox_id, "workspace": str(sandbox.workspace)}


@app.post("/sandboxes/{sandbox_id}/exec")
async def exec_command(sandbox_id: str, payload: ExecRequest):
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
    try:
        sandbox = await manager.get_sandbox(sandbox_id)
        return {"entries": sandbox.fs.list_dir(path)}
    except KeyError:
        raise HTTPException(status_code=404, detail="Sandbox not found")


@app.get("/sandboxes/{sandbox_id}/files/{file_path:path}")
async def read_file(sandbox_id: str, file_path: str = FastAPIPath(...)):
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
    try:
        sandbox = await manager.get_sandbox(sandbox_id)
        backend = f"http://127.0.0.1:{payload.port}"
        url = await preview.register(sandbox_id, payload.port, backend)
        await manager.register_preview(sandbox_id, payload.port, url)
        return {"url": url}
    except KeyError:
        raise HTTPException(status_code=404, detail="Sandbox not found")


@app.post("/sandboxes/{sandbox_id}/keepalive")
async def keep_alive(sandbox_id: str):
    try:
        await manager.keep_alive(sandbox_id)
        return {"status": "ok"}
    except KeyError:
        raise HTTPException(status_code=404, detail="Sandbox not found")


@app.post("/sandboxes/{sandbox_id}/mount")
async def mount_path(sandbox_id: str, payload: MountRequest):
    try:
        target = Path(payload.target)
        await manager.mount(sandbox_id, payload.alias, target)
        return {"success": True}
    except KeyError:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Mount target missing")


@app.post("/sandboxes/{sandbox_id}/background")
async def start_background(sandbox_id: str, payload: BackgroundRequest):
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
    success = await backgrounds.stop_job(sandbox_id, job_id)
    if not success:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"stopped": True}


@app.on_event("shutdown")
async def shutdown_event():
    await preview.close()
