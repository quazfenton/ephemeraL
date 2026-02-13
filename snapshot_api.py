"""
Snapshot API Module
Provides REST API endpoints for snapshot creation, restoration, and management.
"""

import re
from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from auth import get_user_id, validate_user_id
from snapshot_manager import SnapshotManager
from serverless_workers_sdk.metrics import (
    snapshot_created_total,
    snapshot_restored_total,
    snapshot_size_bytes,
)

snap_mgr = SnapshotManager()

app = FastAPI(
    title="Snapshot API",
    description="Manage workspace snapshots for ephemeral environments",
    version="2.0.0",
)


class SnapshotCreateRequest(BaseModel):
    """Request model for creating a snapshot"""
    pass


class SnapshotRestoreRequest(BaseModel):
    """Request model for restoring a snapshot"""
    snapshot_id: str


class SnapshotResponse(BaseModel):
    """Response model for snapshot operations"""
    success: bool
    message: str
    snapshot_id: Optional[str] = None
    size: Optional[str] = None


def _human_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}PB"


def get_current_user(authorization: str = Header(...)):
    """
    Extract and validate user from Authorization header
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header must start with 'Bearer '")

    token = authorization[7:]
    try:
        user_id = get_user_id(token)
        return user_id
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def validate_input(input_str: str) -> bool:
    """
    Validate input strings to prevent path traversal and command injection
    """
    return bool(re.match(r'^[a-zA-Z0-9_-]+$', input_str))


SNAPSHOT_CONFIG = {
    "on_idle_suspend": True,
    "on_explicit_save": True,
    "daily": False,
    "retention_count": 5,
}


@app.post("/snapshot/create", response_model=SnapshotResponse, tags=["snapshots"])
async def create_snapshot(current_user: str = Depends(get_current_user)):
    """
    Create a snapshot of the requesting user's workspace.

    Returns a SnapshotResponse with the snapshot ID and human-readable size.
    """
    if not validate_user_id(current_user):
        raise HTTPException(status_code=400, detail="Invalid user ID format")

    try:
        result = await snap_mgr.create_snapshot(current_user)
        await snap_mgr.enforce_retention(current_user, keep_count=SNAPSHOT_CONFIG["retention_count"])

        snapshot_created_total.inc()
        snapshot_size_bytes.observe(result.size_bytes)

        return SnapshotResponse(
            success=True,
            message="Snapshot created successfully",
            snapshot_id=result.snapshot_id,
            size=_human_size(result.size_bytes),
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Snapshot creation failed: {e}")


@app.post("/snapshot/restore", response_model=SnapshotResponse, tags=["snapshots"])
async def restore_snapshot(request: SnapshotRestoreRequest, current_user: str = Depends(get_current_user)):
    """
    Restore a snapshot to user workspace.

    POST /snapshot/restore
    Headers: Authorization: Bearer <jwt_token>
    Body: {"snapshot_id": "snap_001"}
    """
    if not validate_user_id(current_user):
        raise HTTPException(status_code=400, detail="Invalid user ID format")

    if not validate_input(request.snapshot_id):
        raise HTTPException(status_code=400, detail="Invalid snapshot ID format")

    try:
        await snap_mgr.restore_snapshot(current_user, request.snapshot_id)

        snapshot_restored_total.inc()

        return SnapshotResponse(
            success=True,
            message="Snapshot restored successfully",
            snapshot_id=request.snapshot_id,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Snapshot restoration failed: {e}")


@app.get("/snapshot/list", tags=["snapshots"])
async def list_snapshots(current_user: str = Depends(get_current_user)):
    """
    List all snapshots for the authenticated user.

    GET /snapshot/list
    Headers: Authorization: Bearer <jwt_token>
    """
    if not validate_user_id(current_user):
        raise HTTPException(status_code=400, detail="Invalid user ID format")

    try:
        snapshots = await snap_mgr.list_snapshots(current_user)
        return {
            "snapshots": [
                {
                    "snapshot_id": s.snapshot_id,
                    "size": s.size_bytes,
                    "created_at": s.created_at.isoformat(),
                }
                for s in snapshots
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list snapshots: {e}")


@app.delete("/snapshot/{snapshot_id}", response_model=SnapshotResponse, tags=["snapshots"])
async def delete_snapshot(snapshot_id: str, current_user: str = Depends(get_current_user)):
    """
    Delete a specific snapshot for the authenticated user.

    DELETE /snapshot/{snapshot_id}
    Headers: Authorization: Bearer <jwt_token>
    """
    if not validate_user_id(current_user):
        raise HTTPException(status_code=400, detail="Invalid user ID format")

    if not validate_input(snapshot_id):
        raise HTTPException(status_code=400, detail="Invalid snapshot ID format")

    deleted = await snap_mgr.delete_snapshot(current_user, snapshot_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    return SnapshotResponse(
        success=True,
        message="Snapshot deleted successfully",
        snapshot_id=snapshot_id,
    )


if __name__ == "__main__":
    import uvicorn
    import os

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))

    uvicorn.run(app, host=host, port=port)
