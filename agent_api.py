"""Agent Workspace API — higher-level API on top of the sandbox system for AI agents."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Header, Query
from pydantic import BaseModel

from auth import get_user_id, validate_user_id

logger = logging.getLogger(__name__)


def get_current_user(authorization: str = Header(...)):
    """Extract and validate user from Authorization header."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header must start with 'Bearer '")

    token = authorization[7:]
    try:
        return get_user_id(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class AgentWorkspace(BaseModel):
    agent_id: str
    workspace_id: str
    sandbox_id: Optional[str] = None
    name: str
    description: Optional[str] = None
    created_at: str
    status: str = "active"
    shared_with: list[str] = []
    tags: list[str] = []


class CreateWorkspaceRequest(BaseModel):
    name: str
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    sandbox_config: Optional[dict] = None


class ShareWorkspaceRequest(BaseModel):
    target_agent_ids: list[str]
    permission: str = "read"


class WorkerListing(BaseModel):
    worker_id: str
    name: str
    description: str
    author: str
    version: str = "1.0.0"
    tags: list[str] = []
    endpoint_url: str
    pricing: dict = {}
    rating: float = 0.0
    installs: int = 0


class PublishWorkerRequest(BaseModel):
    name: str
    description: str
    tags: list[str] = []
    endpoint_url: str
    pricing: Optional[dict] = None


class ExecRequest(BaseModel):
    command: str
    args: Optional[list[str]] = None
    timeout: Optional[int] = None


# ---------------------------------------------------------------------------
# WorkspaceManager
# ---------------------------------------------------------------------------

class WorkspaceManager:
    """In-memory workspace, sharing, and marketplace store."""

    def __init__(self) -> None:
        self._workspaces: dict[str, AgentWorkspace] = {}
        self._shares: dict[str, dict[str, str]] = {}
        self._marketplace: dict[str, WorkerListing] = {}
        self._lock = asyncio.Lock()

    async def create_workspace(
        self,
        agent_id: str,
        name: str,
        description: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> AgentWorkspace:
        async with self._lock:
            workspace_id = str(uuid.uuid4())
            workspace = AgentWorkspace(
                agent_id=agent_id,
                workspace_id=workspace_id,
                name=name,
                description=description,
                created_at=datetime.now(timezone.utc).isoformat(),
                tags=tags or [],
            )
            self._workspaces[workspace_id] = workspace
            self._shares[workspace_id] = {}
            logger.info("Created workspace %s for agent %s", workspace_id, agent_id)
            return workspace

    async def get_workspace(self, workspace_id: str) -> AgentWorkspace:
        async with self._lock:
            if workspace_id not in self._workspaces:
                raise KeyError(workspace_id)
            return self._workspaces[workspace_id]

    async def list_workspaces(self, agent_id: str) -> list[AgentWorkspace]:
        async with self._lock:
            return [
                ws for ws in self._workspaces.values()
                if ws.agent_id == agent_id
            ]

    async def delete_workspace(self, workspace_id: str) -> bool:
        async with self._lock:
            if workspace_id not in self._workspaces:
                return False
            del self._workspaces[workspace_id]
            self._shares.pop(workspace_id, None)
            logger.info("Deleted workspace %s", workspace_id)
            return True

    async def share_workspace(
        self,
        workspace_id: str,
        target_ids: list[str],
        permission: str,
    ) -> dict:
        async with self._lock:
            if workspace_id not in self._workspaces:
                raise KeyError(workspace_id)
            shares = self._shares.setdefault(workspace_id, {})
            for agent_id in target_ids:
                shares[agent_id] = permission
            workspace = self._workspaces[workspace_id]
            workspace.shared_with = list(shares.keys())
            logger.info("Shared workspace %s with %s", workspace_id, target_ids)
            return shares

    async def check_access(self, workspace_id: str, agent_id: str) -> Optional[str]:
        async with self._lock:
            if workspace_id not in self._workspaces:
                return None
            workspace = self._workspaces[workspace_id]
            if workspace.agent_id == agent_id:
                return "admin"
            return self._shares.get(workspace_id, {}).get(agent_id)

    async def publish_worker(self, author: str, listing: PublishWorkerRequest) -> WorkerListing:
        async with self._lock:
            worker_id = str(uuid.uuid4())
            worker = WorkerListing(
                worker_id=worker_id,
                name=listing.name,
                description=listing.description,
                author=author,
                tags=listing.tags,
                endpoint_url=listing.endpoint_url,
                pricing=listing.pricing or {},
            )
            self._marketplace[worker_id] = worker
            logger.info("Published worker %s by %s", worker_id, author)
            return worker

    async def search_marketplace(
        self,
        query: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> list[WorkerListing]:
        async with self._lock:
            results = list(self._marketplace.values())
            if query:
                q = query.lower()
                results = [
                    w for w in results
                    if q in w.name.lower() or q in w.description.lower()
                ]
            if tags:
                tag_set = set(tags)
                results = [
                    w for w in results
                    if tag_set & set(w.tags)
                ]
            return results


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Agent Workspace API",
    version="1.0.0",
    description="Higher-level workspace API for AI agents, built on top of the ephemeral sandbox system.",
    openapi_tags=[
        {"name": "workspaces", "description": "Agent workspace lifecycle management"},
        {"name": "sharing", "description": "Workspace sharing and collaboration"},
        {"name": "marketplace", "description": "Worker marketplace for discovering and publishing workers"},
    ],
)

manager = WorkspaceManager()


# ---------------------------------------------------------------------------
# Workspace endpoints
# ---------------------------------------------------------------------------

@app.post("/workspaces", tags=["workspaces"])
async def create_workspace(payload: CreateWorkspaceRequest, current_user: str = Depends(get_current_user)):
    """Create a new agent workspace."""
    workspace = await manager.create_workspace(
        agent_id=current_user,
        name=payload.name,
        description=payload.description,
        tags=payload.tags,
    )
    return workspace


@app.get("/workspaces", tags=["workspaces"])
async def list_workspaces(current_user: str = Depends(get_current_user)):
    """List all workspaces owned by the current agent."""
    return await manager.list_workspaces(current_user)


@app.get("/workspaces/{workspace_id}", tags=["workspaces"])
async def get_workspace(workspace_id: str, current_user: str = Depends(get_current_user)):
    """Get workspace details."""
    access = await manager.check_access(workspace_id, current_user)
    if access is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    try:
        return await manager.get_workspace(workspace_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Workspace not found")


@app.delete("/workspaces/{workspace_id}", tags=["workspaces"])
async def delete_workspace(workspace_id: str, current_user: str = Depends(get_current_user)):
    """Delete a workspace."""
    access = await manager.check_access(workspace_id, current_user)
    if access != "admin":
        raise HTTPException(status_code=403, detail="Only the workspace owner can delete it")
    deleted = await manager.delete_workspace(workspace_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"deleted": True}


@app.post("/workspaces/{workspace_id}/exec", tags=["workspaces"])
async def exec_in_workspace(workspace_id: str, payload: ExecRequest, current_user: str = Depends(get_current_user)):
    """Execute a command inside the workspace's sandbox."""
    access = await manager.check_access(workspace_id, current_user)
    if access is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if access == "read":
        raise HTTPException(status_code=403, detail="Read-only access cannot execute commands")
    try:
        workspace = await manager.get_workspace(workspace_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if not workspace.sandbox_id:
        raise HTTPException(status_code=400, detail="Workspace has no sandbox attached")
    return {
        "workspace_id": workspace_id,
        "sandbox_id": workspace.sandbox_id,
        "command": payload.command,
        "args": payload.args,
        "status": "delegated",
    }


# ---------------------------------------------------------------------------
# Sharing endpoints
# ---------------------------------------------------------------------------

@app.post("/workspaces/{workspace_id}/share", tags=["sharing"])
async def share_workspace(workspace_id: str, payload: ShareWorkspaceRequest, current_user: str = Depends(get_current_user)):
    """Share a workspace with other agents."""
    access = await manager.check_access(workspace_id, current_user)
    if access != "admin":
        raise HTTPException(status_code=403, detail="Only the workspace owner can share it")
    if payload.permission not in ("read", "write", "admin"):
        raise HTTPException(status_code=400, detail="Permission must be read, write, or admin")
    try:
        shares = await manager.share_workspace(workspace_id, payload.target_agent_ids, payload.permission)
        return {"shared": True, "collaborators": shares}
    except KeyError:
        raise HTTPException(status_code=404, detail="Workspace not found")


@app.get("/workspaces/{workspace_id}/collaborators", tags=["sharing"])
async def list_collaborators(workspace_id: str, current_user: str = Depends(get_current_user)):
    """List all collaborators on a workspace."""
    access = await manager.check_access(workspace_id, current_user)
    if access is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    shares = await manager.get_workspace_shares(workspace_id)
    return {"collaborators": shares}


@app.delete("/workspaces/{workspace_id}/share/{agent_id}", tags=["sharing"])
async def revoke_access(workspace_id: str, agent_id: str, current_user: str = Depends(get_current_user)):
    """Revoke an agent's access to a workspace."""
    access = await manager.check_access(workspace_id, current_user)
    if access != "admin":
        raise HTTPException(status_code=403, detail="Only the workspace owner can revoke access")
    try:
        revoked = await manager.revoke_workspace_access(workspace_id, agent_id)
        if not revoked:
            raise HTTPException(status_code=404, detail="Agent not found in collaborators for this workspace")
    except KeyError:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"revoked": True}


# ---------------------------------------------------------------------------
# Marketplace endpoints
# ---------------------------------------------------------------------------

@app.post("/marketplace/publish", tags=["marketplace"])
async def publish_worker(payload: PublishWorkerRequest, current_user: str = Depends(get_current_user)):
    """Publish a worker to the marketplace."""
    worker = await manager.publish_worker(current_user, payload)
    return worker


@app.get("/marketplace/search", tags=["marketplace"])
async def search_marketplace(
    q: Optional[str] = Query(None, description="Search query"),
    tags: Optional[str] = Query(None, description="Comma-separated tags to filter by"),
    current_user: str = Depends(get_current_user),
):
    """Search the worker marketplace."""
    tag_list = [t.strip() for t in tags.split(",")] if tags else None
    results = await manager.search_marketplace(query=q, tags=tag_list)
    return {"results": results}


@app.get("/marketplace/{worker_id}", tags=["marketplace"])
async def get_worker(worker_id: str, current_user: str = Depends(get_current_user)):
    """Get details for a marketplace worker."""
    async with manager._lock:
        worker = manager._marketplace.get(worker_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")
    return worker


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "healthy", "service": "agent-workspace-api"}
