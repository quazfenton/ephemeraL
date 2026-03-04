# Comprehensive Technical Review & Improvement Plan
**Review Date:** March 3, 2026  
**Project:** Ephemeral - Cloud Terminal Platform  
**Reviewer:** AI Code Review Agent  

---

## Executive Summary

This document contains a meticulous, line-by-line review of the ephemeral codebase with specific findings, code fixes, unimplemented features, security concerns, edge cases, and actionable improvement plans. The review covered **24 Python files**, **4 TypeScript files**, **15 documentation files**, and all configuration files.

**Overall Assessment:** The codebase demonstrates solid architectural foundations with JWT-based identity, pluggable container runtimes, snapshot/restore capabilities, and a worker marketplace. However, several critical gaps exist in implementation completeness, security hardening, edge case handling, and SDK integration depth.

---

## Part 1: Critical Findings & Immediate Fixes Required

### 1.1 SECURITY VULNERABILITIES

#### 🔴 CRITICAL: Missing Import in snapshot_manager.py

**File:** `snapshot_manager.py`  
**Line:** ~170-220 (in `restore_snapshot` method)

**Issue:** The code references `tempfile` module but it's not imported at the top of the file.

```python
# CURRENT CODE (BROKEN):
@staticmethod
def _extract_snapshot(snapshot_path: Path, workspace: Path) -> None:
    user_id = workspace.name
    
    with tempfile.TemporaryDirectory(dir=workspace.parent, prefix=f"{user_id}_extract_") as stage_dir_str:
        # ... rest of method
```

**Fix Required:**
```python
# ADD TO IMPORTS AT TOP OF FILE:
import tempfile
```

**Impact:** Snapshot restoration will fail with `NameError: name 'tempfile' is not defined`

---

#### 🔴 CRITICAL: Incomplete Code in snapshot_manager.py

**File:** `snapshot_manager.py`  
**Line:** ~230-240

**Issue:** There's duplicated/truncated code that appears to be a copy-paste error with incomplete method implementation.

```python
# CURRENT CODE (BROKEN - lines 228-240):
                            continue
                        tar.extract(member, path=workspace_parent)

    # -- list -----------------------------------------------------------------
```

**Analysis:** This appears to be leftover from an incomplete edit. The `continue` statement and `tar.extract` call are orphaned code that doesn't belong to any valid code block.

**Fix Required:** Remove lines 228-230 entirely as they are remnants of incomplete refactoring.

---

#### 🟡 HIGH: Missing status Module Import in sandbox_api.py

**File:** `sandbox_api.py`  
**Line:** ~108-125 (in `delete_sandbox` endpoint)

**Issue:** The code references `status.HTTP_403_FORBIDDEN`, `status.HTTP_404_NOT_FOUND`, etc. but `status` is not imported.

```python
# CURRENT CODE (BROKEN):
from fastapi import FastAPI, HTTPException, Path as FastAPIPath, Depends, Header, WebSocket, WebSocketDisconnect
# Missing: from fastapi import status

# Later in code:
raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to delete this sandbox.")
```

**Fix Required:**
```python
# UPDATE IMPORT:
from fastapi import FastAPI, HTTPException, Path as FastAPIPath, Depends, Header, WebSocket, WebSocketDisconnect, status
```

---

#### 🟡 HIGH: Missing Method in WorkspaceManager (agent_api.py)

**File:** `agent_api.py`  
**Line:** ~285-295 (in `list_collaborators` endpoint)

**Issue:** The endpoint calls `manager.get_workspace_shares(workspace_id)` which doesn't exist in the `WorkspaceManager` class.

```python
# CURRENT CODE (BROKEN):
@app.get("/workspaces/{workspace_id}/collaborators", tags=["sharing"])
async def list_collaborators(workspace_id: str, current_user: str = Depends(get_current_user)):
    access = await manager.check_access(workspace_id, current_user)
    if access is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    shares = await manager.get_workspace_shares(workspace_id)  # ❌ METHOD DOESN'T EXIST
    return {"collaborators": shares}
```

**Fix Required - Add method to WorkspaceManager class:**
```python
async def get_workspace_shares(self, workspace_id: str) -> dict:
    """Get all shares for a workspace."""
    async with self._lock:
        if workspace_id not in self._workspaces:
            raise KeyError(workspace_id)
        return self._shares.get(workspace_id, {}).copy()
```

---

#### 🟡 HIGH: Missing Method in WorkspaceManager (agent_api.py)

**File:** `agent_api.py`  
**Line:** ~300-310 (in `revoke_access` endpoint)

**Issue:** The endpoint calls `manager.revoke_workspace_access(workspace_id, agent_id)` which doesn't exist.

**Fix Required - Add method to WorkspaceManager class:**
```python
async def revoke_workspace_access(self, workspace_id: str, agent_id: str) -> bool:
    """Revoke an agent's access to a workspace."""
    async with self._lock:
        if workspace_id not in self._shares:
            return False
        if agent_id in self._shares[workspace_id]:
            del self._shares[workspace_id][agent_id]
            # Update workspace shared_with list
            if workspace_id in self._workspaces:
                self._workspaces[workspace_id].shared_with = list(self._shares[workspace_id].keys())
            return True
        return False
```

---

### 1.2 SYNTAX ERRORS & TYPOS

#### 🟡 MEDIUM: Duplicate Return Statement in metrics.py

**File:** `serverless_workers_sdk/metrics.py`  
**Line:** ~47-50

```python
# CURRENT CODE (DUPLICATE):
def _format_labels(labels: Dict[str, str]) -> str:
    if not labels:
        return ""
    def escape_value(value: str) -> str:
        return value.replace("\\", "\\\\").replace("\n", "\\n").replace("\"", "\\\"")
    pairs = ",".join(f'{k}="{escape_value(v)}"' for k, v in sorted(labels.items()))
    return "{" + pairs + "}"
    return "{" + pairs + "}"  # ❌ DUPLICATE - UNREACHABLE CODE
```

**Fix:** Remove line 50 (the duplicate return statement).

---

#### 🟡 MEDIUM: Typo in quota.py Logging

**File:** `serverless_workers_sdk/quota.py`  
**Line:** ~108-112

```python
# CURRENT CODE (DUPLICATE LOGIC):
if ratio >= QUOTA_WARNING_THRESHOLD and ratio < 1.0:
    logger.warning(
        "Sandbox %s approaching memory limit: %dMB/%dMB",
        sandbox_id, memory_mb, self.quota.max_memory_mb,
    )
logger.warning(  # ❌ DUPLICATE - LOGS TWICE
    "Sandbox %s approaching memory limit: %dMB/%dMB",
    sandbox_id, memory_mb, self.quota.max_memory_mb,
)
```

**Issue:** The warning is logged twice - once conditionally and once unconditionally.

**Fix:** Remove lines 112-114 (the duplicate unconditional log).

---

### 1.3 MISSING ERROR HANDLING

#### 🟡 MEDIUM: No Error Handling in Preview Registrar

**File:** `serverless_workers_sdk/preview.py`  
**Line:** ~35-45

```python
# CURRENT CODE:
async def register(self, sandbox_id: str, port: int, backend: str, metadata: dict | None = None) -> str:
    payload = {
        "sandbox_id": sandbox_id,
        "port": port,
        "backend_url": backend,
        "metadata": metadata or {},
    }
    resp = await self.client.post(f"{PREVIEW_GATEWAY}/preview/register", json=payload)
    resp.raise_for_status()
    body = resp.json()
    return body["url"]  # ❌ NO ERROR HANDLING IF "url" KEY MISSING
```

**Fix Required:**
```python
async def register(self, sandbox_id: str, port: int, backend: str, metadata: dict | None = None) -> str:
    payload = {
        "sandbox_id": sandbox_id,
        "port": port,
        "backend_url": backend,
        "metadata": metadata or {},
    }
    try:
        resp = await self.client.post(f"{PREVIEW_GATEWAY}/preview/register", json=payload)
        resp.raise_for_status()
        body = resp.json()
        if "url" not in body:
            raise RuntimeError("Preview registration response missing 'url' field")
        return body["url"]
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Preview registration failed: {e.response.status_code}") from e
    except httpx.RequestError as e:
        raise RuntimeError(f"Preview service unavailable: {e}") from e
```

---

#### 🟡 MEDIUM: No Connection Retry in Storage Backend

**File:** `serverless_workers_sdk/storage.py`  
**Line:** ~100-120 (S3 upload methods)

**Issue:** S3 operations can fail due to transient network issues but there's no retry logic.

**Fix Required:** Add retry decorator or use boto3's built-in retry configuration:

```python
def _get_client(self):
    if self._client is None:
        import boto3
        from botocore.config import Config
        
        retry_config = Config(
            retries={
                'max_attempts': 3,
                'mode': 'standard'
            }
        )
        
        kwargs: dict = {
            "service_name": "s3",
            "aws_access_key_id": self._config.access_key,
            "aws_secret_access_key": self._config.secret_key,
            "region_name": self._config.region,
            "config": retry_config,
        }
        if self._config.endpoint_url:
            kwargs["endpoint_url"] = self._config.endpoint_url
        self._client = boto3.client(**kwargs)
    return self._client
```

---

## Part 2: Incomplete Implementations & Missing Features

### 2.1 UNIMPLEMENTED ENDPOINTS (PSEUDOCODE/MOCK)

#### 🔴 CRITICAL: agent_api.py - Workspace Exec Endpoint is Mock

**File:** `agent_api.py`  
**Line:** ~260-275

```python
# CURRENT CODE (MOCK IMPLEMENTATION):
@app.post("/workspaces/{workspace_id}/exec", tags=["workspaces"])
async def exec_in_workspace(workspace_id: str, payload: ExecRequest, current_user: str = Depends(get_current_user)):
    # ... access checks ...
    return {
        "workspace_id": workspace_id,
        "sandbox_id": workspace.sandbox_id,
        "command": payload.command,
        "args": payload.args,
        "status": "delegated",  # ❌ JUST RETURNS STATUS, DOESN'T ACTUALLY EXECUTE
    }
```

**Issue:** The endpoint doesn't actually execute the command - it just returns a mock response.

**Fix Required - Full Implementation:**
```python
@app.post("/workspaces/{workspace_id}/exec", tags=["workspaces"])
async def exec_in_workspace(
    workspace_id: str, 
    payload: ExecRequest, 
    current_user: str = Depends(get_current_user)
):
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
    
    # ACTUALLY EXECUTE THE COMMAND via sandbox_api
    import httpx
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"http://127.0.0.1:8000/sandboxes/{workspace.sandbox_id}/exec",
            json={
                "command": payload.command,
                "args": payload.args or [],
                "timeout": payload.timeout,
            },
            headers={"Authorization": f"Bearer {current_user}"},
            timeout=payload.timeout or 30.0,
        )
        
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Sandbox not found")
        elif response.status_code != 200:
            raise HTTPException(status_code=502, detail="Command execution failed")
        
        return response.json()
```

---

#### 🟡 HIGH: container_runtime.py - Firecracker SSH Execution Incomplete

**File:** `serverless_workers_sdk/container_runtime.py`  
**Line:** ~220-250

```python
# CURRENT CODE:
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
    
    # ❌ SSH IMPLEMENTATION ASSUMES NETWORK CONFIG THAT DOESN'T EXIST
```

**Issue:** Firecracker microVMs don't have network access by default - they need explicit network interface configuration. The current code assumes VMs have IP addresses but never configures networking.

**Fix Required - Add Network Configuration:**
```python
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

    # Configure machine
    await self._api_call(sandbox_id, "PUT", "/machine-config", {
        "vcpu_count": limits.vcpu_count,
        "mem_size_mib": limits.mem_size_mib,
    })
    
    # Configure boot
    await self._api_call(sandbox_id, "PUT", "/boot-source", {
        "kernel_image_path": self._kernel_image,
        "boot_args": "console=ttyS0 reboot=k panic=1 pci=off ip=172.16.0.2::172.16.0.1:255.255.255.0::eth0:off",
    })
    
    # Configure rootfs
    await self._api_call(sandbox_id, "PUT", "/drives/rootfs", {
        "drive_id": "rootfs",
        "path_on_host": image,
        "is_root_device": True,
        "is_read_only": False,
    })
    
    # ADD: Configure network interface
    await self._api_call(sandbox_id, "PUT", "/network-interfaces/eth0", {
        "iface_id": "eth0",
        "guest_mac": "AA:FC:00:00:00:01",
        "host_dev_name": f"veth_{sandbox_id[:8]}",
    })

    created_at = time.time()
    info = ContainerInfo(
        sandbox_id=sandbox_id,
        workspace_path=workspace,
        ip_address="172.16.0.2",  # Assign static IP
        created_at=created_at,
    )
```

**Additional Requirement:** Create network interfaces on host:
```python
async def _setup_network_interface(self, sandbox_id: str) -> None:
    """Create veth pair for VM networking."""
    veth_name = f"veth_{sandbox_id[:8]}"
    await asyncio.create_subprocess_exec(
        "ip", "link", "add", veth_name, "type", "veth", "peer", "name", f"{veth_name}_ns"
    )
    await asyncio.create_subprocess_exec("ip", "link", "set", veth_name, "up")
```

---

### 2.2 MISSING INTEGRATIONS

#### 🟡 HIGH: No Composio Integration for Tool Calling

**Finding:** The technical plans mention advanced agent capabilities but there's no integration with Composio or similar tool-calling frameworks.

**Documentation Reference:** Based on the review instructions mentioning `docs/sdk/composio-llms-full.txt`, Composio provides:
- 150+ pre-built tool integrations (GitHub, Slack, Notion, etc.)
- OAuth management for agents
- Action execution with proper authentication

**Implementation Plan:**

1. **Add Composio to requirements.txt:**
```txt
composio-core>=0.5.0
composio-openai>=0.5.0  # or composio-anthropic for Claude
```

2. **Create new file: `serverless_workers_sdk/tool_integration.py`:**
```python
from composio import Composio, Action, App
from typing import Dict, Any, Optional

class ToolIntegrationManager:
    def __init__(self, api_key: Optional[str] = None):
        self.client = Composio(api_key=api_key)
        self._active_connections: Dict[str, Dict] = {}
    
    async def setup_agent_tools(self, sandbox_id: str, agent_id: str, tools: list[str]) -> Dict[str, Any]:
        """
        Set up tool connections for an agent in a sandbox.
        
        Args:
            sandbox_id: The sandbox where tools will be available
            agent_id: The agent identifier
            tools: List of tool names (e.g., ["github", "slack", "notion"])
        
        Returns:
            Dict with connection statuses and available actions
        """
        connections = {}
        for tool_name in tools:
            try:
                # Get available actions for this tool
                actions = self.client.actions.get_actions(app=App(tool_name))
                
                # Create connection if needed
                connection = self.client.connections.get_or_create(
                    app=App(tool_name),
                    entity_id=agent_id,
                )
                
                connections[tool_name] = {
                    "status": "connected",
                    "connection_id": connection.id,
                    "available_actions": [a.name for a in actions],
                }
            except Exception as e:
                connections[tool_name] = {
                    "status": "error",
                    "error": str(e),
                }
        
        self._active_connections[sandbox_id] = connections
        return connections
    
    async def execute_tool_action(
        self, 
        sandbox_id: str, 
        action_name: str, 
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a tool action in the context of a sandbox."""
        if sandbox_id not in self._active_connections:
            raise RuntimeError(f"No tools configured for sandbox {sandbox_id}")
        
        try:
            result = self.client.actions.execute(
                action=Action(action_name),
                params=params,
                entity_id=sandbox_id,  # Use sandbox as entity
            )
            return {
                "success": True,
                "result": result,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
    
    async def teardown_tools(self, sandbox_id: str) -> None:
        """Clean up tool connections when sandbox is destroyed."""
        if sandbox_id in self._active_connections:
            # Disconnect all tools
            for tool_name, conn_info in self._active_connections[sandbox_id].items():
                if conn_info.get("connection_id"):
                    try:
                        self.client.connections.disconnect(conn_info["connection_id"])
                    except Exception:
                        pass  # Best effort cleanup
            del self._active_connections[sandbox_id]
```

3. **Integrate with sandbox_api.py:**
```python
# Add to imports
from serverless_workers_sdk.tool_integration import ToolIntegrationManager

# Initialize with manager
tool_manager = ToolIntegrationManager(api_key=os.getenv("COMPOSIO_API_KEY"))

# Add new endpoint
@app.post("/sandboxes/{sandbox_id}/tools/configure", tags=["sandboxes"])
async def configure_tools(
    sandbox_id: str,
    tools: list[str],
    current_user: str = Depends(get_current_user),
):
    """Configure tool integrations for a sandbox."""
    try:
        sandbox = await manager.get_sandbox(sandbox_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    result = await tool_manager.setup_agent_tools(sandbox_id, current_user, tools)
    return {"sandbox_id": sandbox_id, "tools": result}

@app.post("/sandboxes/{sandbox_id}/tools/execute", tags=["sandboxes"])
async def execute_tool(
    sandbox_id: str,
    action: str,
    params: dict,
    current_user: str = Depends(get_current_user),
):
    """Execute a tool action in a sandbox."""
    try:
        await manager.get_sandbox(sandbox_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    
    result = await tool_manager.execute_tool_action(sandbox_id, action, params)
    if result["success"]:
        return result
    else:
        raise HTTPException(status_code=400, detail=result["error"])

# Add to shutdown
@app.on_event("shutdown")
async def shutdown_event():
    await backgrounds.shutdown()
    await preview.close()
    # Clean up all tool connections
    for sandbox_id in list(tool_manager._active_connections.keys()):
        await tool_manager.teardown_tools(sandbox_id)
```

---

#### 🟡 MEDIUM: No LangChain/LangGraph Integration for Agent Workflows

**Finding:** The agent workspace API supports multi-agent collaboration but lacks integration with agent orchestration frameworks.

**Implementation Plan:**

Add to requirements.txt:
```txt
langchain>=0.3.0
langgraph>=0.2.0
```

Create `serverless_workers_sdk/agent_orchestrator.py`:
```python
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated, List
import operator

class AgentState(TypedDict):
    messages: Annotated[List[HumanMessage | AIMessage], operator.add]
    sandbox_id: str
    current_agent: str

class AgentOrchestrator:
    def __init__(self, sandbox_manager):
        self.sandbox_manager = sandbox_manager
        self._graphs: Dict[str, StateGraph] = {}
    
    def create_collaborative_workflow(self, workspace_id: str, agent_roles: List[str]) -> StateGraph:
        """
        Create a collaborative workflow where multiple agents work together.
        
        Args:
            workspace_id: The workspace identifier
            agent_roles: List of agent role names (e.g., ["researcher", "coder", "reviewer"])
        """
        workflow = StateGraph(AgentState)
        
        # Add node for each agent
        for agent_role in agent_roles:
            workflow.add_node(
                agent_role, 
                lambda state, role=agent_role: self._execute_agent_step(state, role)
            )
        
        # Create round-robin flow
        for i, agent_role in enumerate(agent_roles):
            next_agent = agent_roles[(i + 1) % len(agent_roles)]
            workflow.add_edge(agent_role, next_agent)
        
        # Set entry point
        workflow.set_entry_point(agent_roles[0])
        
        # Add conditional exit (when task complete)
        workflow.add_conditional_edges(
            agent_roles[-1],
            lambda state: "complete" if self._is_task_complete(state) else "continue",
            {
                "complete": END,
                "continue": agent_roles[0],
            }
        )
        
        self._graphs[workspace_id] = workflow
        return workflow
    
    async def _execute_agent_step(self, state: AgentState, agent_role: str) -> AgentState:
        """Execute a single step for an agent in its sandbox context."""
        sandbox_id = state["sandbox_id"]
        
        # Execute command in sandbox based on agent role
        if agent_role == "coder":
            result = await self.sandbox_manager.exec_command(
                sandbox_id=sandbox_id,
                command="python",
                code=self._extract_code_from_messages(state["messages"]),
            )
        elif agent_role == "researcher":
            result = await self.sandbox_manager.exec_command(
                sandbox_id=sandbox_id,
                command="python",
                args=["-c", "import requests; print(requests.get('https://api.example.com/data').json())"],
            )
        else:
            result = {"stdout": "", "stderr": f"Unknown agent role: {agent_role}", "exit_code": 1}
        
        state["messages"].append(AIMessage(content=result["stdout"]))
        state["current_agent"] = agent_role
        return state
    
    def _is_task_complete(self, state: AgentState) -> bool:
        """Check if the collaborative task is complete."""
        # Simple heuristic: check for completion marker in messages
        last_message = state["messages"][-1] if state["messages"] else None
        if last_message and isinstance(last_message, AIMessage):
            return "[COMPLETE]" in last_message.content
        return False
```

---

### 2.3 MISSING EDGE CASE HANDLING

#### 🟡 MEDIUM: No Rate Limiting on API Endpoints

**File:** All API files (`sandbox_api.py`, `snapshot_api.py`, `agent_api.py`)

**Issue:** No rate limiting is implemented, allowing potential DoS attacks.

**Fix Required - Add rate limiting middleware:**

Create new file `serverless_workers_sdk/rate_limiter.py`:
```python
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from collections import defaultdict
import time
from typing import Dict, Tuple

class RateLimiter(BaseHTTPMiddleware):
    def __init__(
        self, 
        app,
        requests_per_minute: int = 60,
        burst_limit: int = 10,
    ):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.burst_limit = burst_limit
        self._request_counts: Dict[str, list] = defaultdict(list)
    
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host
        user_agent = request.headers.get("user-agent", "unknown")
        key = f"{client_ip}:{user_agent}"
        
        now = time.time()
        window_start = now - 60  # 1-minute window
        
        # Clean old requests
        self._request_counts[key] = [
            ts for ts in self._request_counts[key] 
            if ts > window_start
        ]
        
        # Check rate limit
        if len(self._request_counts[key]) >= self.requests_per_minute:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "rate_limit_exceeded",
                    "message": f"Rate limit exceeded. Max {self.requests_per_minute} requests per minute.",
                    "retry_after": 60,
                },
                headers={"Retry-After": "60"},
            )
        
        # Check burst limit (more than 10 requests in 1 second)
        recent_burst = [ts for ts in self._request_counts[key] if now - ts < 1]
        if len(recent_burst) >= self.burst_limit:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "burst_limit_exceeded",
                    "message": f"Burst limit exceeded. Max {self.burst_limit} requests per second.",
                },
            )
        
        # Record this request
        self._request_counts[key].append(now)
        
        # Process request
        response = await call_next(request)
        return response
```

Add to each API app:
```python
# In sandbox_api.py, snapshot_api.py, agent_api.py
from serverless_workers_sdk.rate_limiter import RateLimiter

app.add_middleware(RateLimiter, requests_per_minute=60, burst_limit=10)
```

---

#### 🟡 MEDIUM: No Input Validation on File Paths

**File:** `sandbox_api.py` - `read_file` endpoint

**Issue:** While `VirtualFS._resolve()` has path traversal protection, the API endpoint doesn't validate the `file_path` parameter before passing it to the filesystem.

**Current Code:**
```python
@app.get("/sandboxes/{sandbox_id}/files/{file_path:path}", tags=["files"])
async def read_file(sandbox_id: str, file_path: str = FastAPIPath(...), current_user: str = Depends(get_current_user)):
    try:
        sandbox = await manager.get_sandbox(sandbox_id)
        content = sandbox.fs.read(file_path)  # ❌ NO VALIDATION BEFORE USE
        return {"content": content.decode(errors="ignore")}
```

**Fix Required:**
```python
import re

def validate_file_path(path: str) -> bool:
    """Validate file path to prevent directory traversal and null byte injection."""
    if not path:
        return False
    # Check for null bytes
    if "\x00" in path:
        return False
    # Check for absolute paths
    if path.startswith("/"):
        return False
    # Check for directory traversal
    if ".." in path.split("/"):
        return False
    # Check for shell metacharacters
    if re.search(r'[;&|`$(){}]', path):
        return False
    return True

@app.get("/sandboxes/{sandbox_id}/files/{file_path:path}", tags=["files"])
async def read_file(sandbox_id: str, file_path: str = FastAPIPath(...), current_user: str = Depends(get_current_user)):
    if not validate_file_path(file_path):
        raise HTTPException(status_code=400, detail="Invalid file path")
    
    try:
        sandbox = await manager.get_sandbox(sandbox_id)
        content = sandbox.fs.read(file_path)
        return {"content": content.decode(errors="ignore")}
    except KeyError:
        raise HTTPException(status_code=404, detail="Sandbox not found")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
```

---

## Part 3: Architecture & Design Improvements

### 3.1 MISSING ABSTRACTIONS

#### 🟡 MEDIUM: No Unified Configuration Management

**Finding:** Configuration is scattered across environment variables, hardcoded values, and module-level constants.

**Fix Required - Create centralized config:**

New file `serverless_workers_sdk/config.py`:
```python
from pydantic import BaseSettings, Field
from typing import Optional, List
import os

class Settings(BaseSettings):
    # Identity
    jwt_public_key: str = Field(default="", env="JWT_PUBLIC_KEY")
    jwt_audience: Optional[str] = Field(default=None, env="JWT_AUDIENCE")
    jwt_issuer: Optional[str] = Field(default=None, env="JWT_ISSUER")
    
    # Sandbox
    sandbox_root: str = Field(default="/tmp/sandboxes", env="SANDBOX_ROOT")
    default_timeout: int = Field(default=15, env="DEFAULT_TIMEOUT")
    allowed_commands: List[str] = Field(default=["python", "node"], env="ALLOWED_COMMANDS")
    
    # Quota
    quota_executions_per_hour: int = Field(default=120, env="QUOTA_EXECUTIONS_PER_HOUR")
    quota_max_memory_mb: int = Field(default=2048, env="QUOTA_MAX_MEMORY_MB")
    quota_max_concurrent: int = Field(default=10, env="QUOTA_MAX_CONCURRENT")
    
    # Storage
    storage_backend: str = Field(default="auto", env="STORAGE_BACKEND")
    s3_endpoint: Optional[str] = Field(default=None, env="S3_ENDPOINT")
    s3_bucket: str = Field(default="ephemeral-snapshots", env="S3_BUCKET")
    
    # Preview
    preview_router_url: str = Field(default="http://127.0.0.1:8001", env="PREVIEW_ROUTER_URL")
    
    # Rate Limiting
    rate_limit_per_minute: int = Field(default=60, env="RATE_LIMIT_PER_MINUTE")
    rate_limit_burst: int = Field(default=10, env="RATE_LIMIT_BURST")
    
    # Tool Integrations
    composio_api_key: Optional[str] = Field(default=None, env="COMPOSIO_API_KEY")
    
    class Config:
        env_file = ".env"
        case_sensitive = False

# Global settings instance
settings = Settings()
```

---

#### 🟡 MEDIUM: No Event Bus for Cross-Service Communication

**Finding:** Services communicate via direct HTTP calls, creating tight coupling.

**Fix Required - Add event bus:**

New file `serverless_workers_sdk/event_bus.py`:
```python
import asyncio
from typing import Callable, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime
import json

@dataclass
class Event:
    type: str
    payload: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source: str = ""

class EventBus:
    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}
        self._event_history: List[Event] = []
        self._max_history = 1000
    
    def subscribe(self, event_type: str, handler: Callable[[Event], Any]):
        """Subscribe to an event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)
    
    def unsubscribe(self, event_type: str, handler: Callable):
        """Unsubscribe from an event type."""
        if event_type in self._subscribers:
            self._subscribers[event_type].remove(handler)
    
    async def publish(self, event: Event):
        """Publish an event to all subscribers."""
        # Store in history
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history:]
        
        # Notify subscribers
        handlers = self._subscribers.get(event.type, [])
        await asyncio.gather(
            *[self._safe_call(handler, event) for handler in handlers],
            return_exceptions=True,
        )
    
    async def _safe_call(self, handler: Callable, event: Event):
        try:
            if asyncio.iscoroutinefunction(handler):
                await handler(event)
            else:
                handler(event)
        except Exception as e:
            # Log error but don't fail other handlers
            print(f"Event handler error: {e}")
    
    def get_history(self, event_type: Optional[str] = None, limit: int = 100) -> List[Event]:
        """Get recent event history, optionally filtered by type."""
        history = self._event_history
        if event_type:
            history = [e for e in history if e.type == event_type]
        return history[-limit:]

# Global event bus
event_bus = EventBus()

# Pre-defined event types
class SandboxEvents:
    CREATED = "sandbox.created"
    DESTROYED = "sandbox.destroyed"
    EXECUTED = "sandbox.executed"
    QUOTA_EXCEEDED = "sandbox.quota_exceeded"

class SnapshotEvents:
    CREATED = "snapshot.created"
    RESTORED = "snapshot.restored"
    DELETED = "snapshot.deleted"
```

---

### 3.2 MISSING OBSERVABILITY

#### 🟡 MEDIUM: No Structured Logging

**Finding:** Logging uses print statements and basic logger without structured format.

**Fix Required:**

Add to requirements.txt:
```txt
structlog>=24.0.0
```

Create `serverless_workers_sdk/logging_config.py`:
```python
import structlog
import logging
import sys

def setup_logging(log_level: str = "INFO", json_format: bool = False):
    """Configure structured logging for the application."""
    
    timestamper = structlog.processors.TimeStamper(fmt="iso")
    
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.ExtraAdder(),
        timestamper,
    ]
    
    if json_format:
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Configure standard library logging
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level.upper()))
```

---

#### 🟡 MEDIUM: No Distributed Tracing

**Finding:** No request tracing across services (sandbox_api → preview_router → fallback).

**Fix Required - Add OpenTelemetry:**

Add to requirements.txt:
```txt
opentelemetry-api>=1.20.0
opentelemetry-sdk>=1.20.0
opentelemetry-instrumentation-fastapi>=0.41b0
```

Create `serverless_workers_sdk/tracing.py`:
```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

def setup_tracing(service_name: str, otlp_endpoint: str = "http://localhost:4317"):
    """Set up distributed tracing."""
    
    provider = TracerProvider(
        resource={
            "service.name": service_name,
        }
    )
    
    exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    
    return trace.get_tracer(__name__)

# Usage in each API:
# tracer = setup_tracing("sandbox-api")
# 
# @app.post("/sandboxes")
# async def create_sandbox(...):
#     with tracer.start_as_current_span("create_sandbox"):
#         sandbox = await manager.create_sandbox(...)
#         return sandbox
```

---

## Part 4: Testing Gaps

### 4.1 MISSING TEST COVERAGE

#### Tests Needed:

1. **`test_snapshot_manager.py`** - Comprehensive tests for snapshot creation/restoration
   - Test with large files (>100MB)
   - Test with symlinks
   - Test concurrent snapshot operations
   - Test retry logic on failure

2. **`test_auth.py`** - Authentication tests
   - Test JWT validation with various token states
   - Test token expiration handling
   - Test invalid signature detection
   - Test path traversal in user_id

3. **`test_rate_limiter.py`** - Rate limiting tests
   - Test burst detection
   - Test window sliding
   - Test multiple clients

4. **`test_tool_integration.py`** - Composio integration tests
   - Mock Composio API responses
   - Test connection lifecycle
   - Test error handling

---

## Part 5: Documentation Gaps

### 5.1 MISSING DOCUMENTATION

1. **API Reference Documentation** - Auto-generate from OpenAPI specs
2. **Deployment Guide** - Production deployment with Kubernetes
3. **Security Best Practices** - Hardening guide for production
4. **Troubleshooting Guide** - Common issues and solutions
5. **SDK Documentation** - How to use serverless_workers_sdk

---

## Part 6: Performance Optimizations

### 6.1 IDENTIFIED BOTTLENECKS

1. **Snapshot Creation Blocks Event Loop**
   - Current: Uses `asyncio.to_thread()` but compresses entire workspace
   - Fix: Stream compression with progress tracking

2. **No Connection Pooling for HTTP Clients**
   - Current: Creates new httpx client for each request
   - Fix: Use connection pools with keepalive

3. **No Caching for Frequent Operations**
   - Current: Re-reads same files repeatedly
   - Fix: Add LRU cache for file reads

---

## Part 7: Security Hardening

### 7.1 CRITICAL SECURITY ADDITIONS

1. **Add Content Security Policy headers**
2. **Implement request signing for inter-service communication**
3. **Add audit logging for all privileged operations**
4. **Implement secret rotation for API keys**
5. **Add network policies for container isolation**

---

## Appendix A: Complete Fix Checklist

### Immediate Fixes (Do First)
- [ ] Add `import tempfile` to snapshot_manager.py
- [ ] Remove orphaned code in snapshot_manager.py lines 228-230
- [ ] Add `status` import to sandbox_api.py
- [ ] Implement `get_workspace_shares()` in WorkspaceManager
- [ ] Implement `revoke_workspace_access()` in WorkspaceManager
- [ ] Remove duplicate return in metrics.py
- [ ] Fix duplicate logging in quota.py

### High Priority
- [ ] Implement actual command execution in agent_api.py `/workspaces/{id}/exec`
- [ ] Add Firecracker network configuration
- [ ] Add input validation for file paths
- [ ] Add rate limiting middleware
- [ ] Add retry logic to storage backend
- [ ] Add error handling to preview registrar

### Medium Priority
- [ ] Add Composio integration
- [ ] Add LangChain integration
- [ ] Implement centralized configuration
- [ ] Add event bus for cross-service communication
- [ ] Add structured logging
- [ ] Add distributed tracing
- [ ] Create missing test files

### Low Priority (Nice to Have)
- [ ] Add performance optimizations
- [ ] Create comprehensive documentation
- [ ] Add security hardening features
- [ ] Implement connection pooling

---

## Appendix B: New Files to Create

1. `serverless_workers_sdk/config.py` - Centralized configuration
2. `serverless_workers_sdk/event_bus.py` - Event bus for cross-service communication
3. `serverless_workers_sdk/rate_limiter.py` - Rate limiting middleware
4. `serverless_workers_sdk/tool_integration.py` - Composio integration
5. `serverless_workers_sdk/agent_orchestrator.py` - LangChain integration
6. `serverless_workers_sdk/logging_config.py` - Structured logging setup
7. `serverless_workers_sdk/tracing.py` - Distributed tracing setup
8. `test_snapshot_manager.py` - Snapshot manager tests
9. `test_auth.py` - Authentication tests
10. `test_rate_limiter.py` - Rate limiter tests

---

**Document Generated:** March 3, 2026  
**Next Review Date:** March 17, 2026  
**Status:** Ready for Implementation
