"""
Snapshot API Module
Provides REST API endpoints for snapshot creation and restoration
"""

import re
from pathlib import Path
from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel
from typing import Optional
import subprocess
import os
from datetime import datetime
from auth import get_user_id, validate_user_id

# Define absolute paths for scripts
SCRIPT_DIR = Path(__file__).parent.resolve()
CREATE_SNAPSHOT_SCRIPT = SCRIPT_DIR / "create_snapshot.sh"
RESTORE_SNAPSHOT_SCRIPT = SCRIPT_DIR / "restore_snapshot.sh"

# Validate that scripts exist
if not CREATE_SNAPSHOT_SCRIPT.exists():
    raise RuntimeError(f"Snapshot creation script not found: {CREATE_SNAPSHOT_SCRIPT}")

if not RESTORE_SNAPSHOT_SCRIPT.exists():
    raise RuntimeError(f"Snapshot restore script not found: {RESTORE_SNAPSHOT_SCRIPT}")


app = FastAPI(title="Snapshot API")


class SnapshotCreateRequest(BaseModel):
    """Request model for creating a snapshot"""
    # user_id is now derived from JWT token, not from request body
    pass


class SnapshotRestoreRequest(BaseModel):
    """Request model for restoring a snapshot"""
    snapshot_id: str  # user_id is now derived from JWT token


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


def validate_input(input_str: str) -> bool:
    """
    Validate input strings to prevent path traversal and command injection

    Args:
        input_str: Input string to validate

    Returns:
        True if valid, False otherwise
    """
    # Allow only alphanumeric characters, hyphens, and underscores
    return bool(re.match(r'^[a-zA-Z0-9_-]+$', input_str))


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
async def create_snapshot(request: SnapshotCreateRequest, current_user: str = Depends(get_current_user)):
    """
    Create a snapshot of user workspace

    POST /snapshot/create
    Headers: Authorization: Bearer <jwt_token>
    """
    try:
        snapshot_id = generate_snapshot_id()

        # Validate user_id from token
        if not validate_user_id(current_user):
            raise HTTPException(status_code=400, detail="Invalid user ID format")

        # Execute snapshot creation script
        result = subprocess.run(
            [str(CREATE_SNAPSHOT_SCRIPT), current_user, snapshot_id],
            capture_output=True,
            text=True,
            check=True
        )

        # Get snapshot size
        snapshot_path = f"/srv/snapshots/{current_user}/{snapshot_id}.tar.zst"

        # Validate the path to prevent directory traversal
        if "../" in snapshot_path or "..\\" in snapshot_path:
            raise HTTPException(status_code=500, detail="Invalid path detected")

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
async def restore_snapshot(request: SnapshotRestoreRequest, current_user: str = Depends(get_current_user)):
    """
    Restore a snapshot to user workspace

    POST /snapshot/restore
    Headers: Authorization: Bearer <jwt_token>
    Body: {
      "snapshot_id": "snap_001"
    }
    """
    try:
        # Validate user_id from token
        if not validate_user_id(current_user):
            raise HTTPException(status_code=400, detail="Invalid user ID format")

        # Validate snapshot_id to prevent path traversal and command injection
        if not validate_input(request.snapshot_id):
            raise HTTPException(status_code=400, detail="Invalid snapshot ID format")

        # Execute snapshot restoration script
        result = subprocess.run(
            [str(RESTORE_SNAPSHOT_SCRIPT), current_user, request.snapshot_id],
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


@app.get("/snapshot/list")
async def list_snapshots(current_user: str = Depends(get_current_user)):
    """
    List all snapshots for the authenticated user

    GET /snapshot/list
    Headers: Authorization: Bearer <jwt_token>
    """
    try:
        # Validate user_id from token
        if not validate_user_id(current_user):
            raise HTTPException(status_code=400, detail="Invalid user ID format")

        snapshot_dir = f"/srv/snapshots/{current_user}"

        # Validate the path to prevent directory traversal
        if "../" in snapshot_dir or "..\\" in snapshot_dir:
            raise HTTPException(status_code=500, detail="Invalid path detected")

        if not os.path.exists(snapshot_dir):
            return {"snapshots": []}

        snapshots = []
        for filename in os.listdir(snapshot_dir):
            if filename.endswith(".tar.zst"):
                filepath = os.path.join(snapshot_dir, filename)
                # Additional validation to ensure we're only accessing files in the intended directory
                if not filepath.startswith(f"/srv/snapshots/{current_user}/"):
                    continue  # Skip files that would result from path traversal attempts
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
    import os

    # Read host and port from environment variables with defaults
    host = os.getenv("HOST", "127.0.0.1")  # Default to localhost for dev
    port = int(os.getenv("PORT", "8000"))

    uvicorn.run(app, host=host, port=port)
