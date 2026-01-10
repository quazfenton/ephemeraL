"""
Snapshot API Module
Provides REST API endpoints for snapshot creation and restoration
"""

from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
import subprocess
import os
from datetime import datetime
from auth import get_user_id


app = FastAPI(title="Snapshot API")


class SnapshotCreateRequest(BaseModel):
    """Request model for creating a snapshot"""
    user_id: str


class SnapshotRestoreRequest(BaseModel):
    """Request model for restoring a snapshot"""
    user_id: str
    snapshot_id: str


class SnapshotResponse(BaseModel):
    """Response model for snapshot operations"""
    success: bool
    message: str
    snapshot_id: Optional[str] = None
    size: Optional[str] = None


def generate_snapshot_id() -> str:
    """Generate a unique snapshot ID based on timestamp"""
    return f"snap_{datetime.now().strftime('%Y_%m_%d_%H%M%S')}"


@app.post("/snapshot/create", response_model=SnapshotResponse)
async def create_snapshot(request: SnapshotCreateRequest):
    """
    Create a snapshot of user workspace
    
    POST /snapshot/create
    Body: { "user_id": "u_123" }
    """
    try:
        snapshot_id = generate_snapshot_id()
        
        # Execute snapshot creation script
        result = subprocess.run(
            ["./create_snapshot.sh", request.user_id, snapshot_id],
            capture_output=True,
            text=True,
            check=True
        )
        
        # Get snapshot size
        snapshot_path = f"/srv/snapshots/{request.user_id}/{snapshot_id}.tar.zst"
        size = subprocess.check_output(
            ["du", "-h", snapshot_path],
            text=True
        ).split()[0]
        
        return SnapshotResponse(
            success=True,
            message="Snapshot created successfully",
            snapshot_id=snapshot_id,
            size=size
        )
    except subprocess.CalledProcessError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Snapshot creation failed: {e.stderr}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {str(e)}"
        )


@app.post("/snapshot/restore", response_model=SnapshotResponse)
async def restore_snapshot(request: SnapshotRestoreRequest):
    """
    Restore a snapshot to user workspace
    
    POST /snapshot/restore
    Body: {
      "user_id": "u_123",
      "snapshot_id": "snap_001"
    }
    """
    try:
        # Execute snapshot restoration script
        result = subprocess.run(
            ["./restore_snapshot.sh", request.user_id, request.snapshot_id],
            capture_output=True,
            text=True,
            check=True
        )
        
        return SnapshotResponse(
            success=True,
            message="Snapshot restored successfully",
            snapshot_id=request.snapshot_id
        )
    except subprocess.CalledProcessError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Snapshot restoration failed: {e.stderr}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {str(e)}"
        )


@app.get("/snapshot/list/{user_id}")
async def list_snapshots(user_id: str):
    """
    List all snapshots for a user
    
    GET /snapshot/list/{user_id}
    """
    try:
        snapshot_dir = f"/srv/snapshots/{user_id}"
        
        if not os.path.exists(snapshot_dir):
            return {"snapshots": []}
        
        snapshots = []
        for filename in os.listdir(snapshot_dir):
            if filename.endswith(".tar.zst"):
                filepath = os.path.join(snapshot_dir, filename)
                stat = os.stat(filepath)
                snapshots.append({
                    "snapshot_id": filename.replace(".tar.zst", ""),
                    "size": stat.st_size,
                    "created_at": datetime.fromtimestamp(stat.st_ctime).isoformat()
                })
        
        # Sort by creation time, newest first
        snapshots.sort(key=lambda x: x["created_at"], reverse=True)
        
        return {"snapshots": snapshots}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list snapshots: {str(e)}"
        )


# Automatic Snapshots Configuration
SNAPSHOT_CONFIG = {
    "on_idle_suspend": True,
    "on_explicit_save": True,
    "daily": False,
    "retention_count": 5  # Keep last 5 snapshots
}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
