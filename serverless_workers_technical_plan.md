# Advanced Technical Plan: Serverless Worker System with Secure Sandboxing

## Overview

This document outlines a comprehensive technical plan for building a serverless worker system similar to Cloudflare's Sandbox SDK, but implemented independently without relying on proprietary services. The system provides secure, isolated code execution environments with features like preview URLs, file system operations, and WASM-based execution.

## Architecture Overview

```
Client (Browser / Agent)
        |
        |  WebSocket / HTTP
        v
Ingress Router (FastAPI / ASGI)
        |
        |  sandbox_id → owner routing
        v
Sandbox Manager
        |
        |  RPC / in-process
        v
Sandbox Runtime
  ├── Python control plane
  ├── WASM execution engine
  ├── Snapshot restore
  ├── Virtual FS
  ├── HTTP multiplexer
  └── WS hub
```

## Core Components

### 1. Sandbox Runtime

Each sandbox is a long-lived Python process that behaves like a Durable Object, providing single-threaded isolation and persistent state.

```python
# sandbox/runtime.py
import asyncio
from typing import Dict, Callable, Optional
from .virtual_fs import VirtualFS
from .wasm_engine import WasmEngine

class SandboxRuntime:
    def __init__(self, sandbox_id: str, snapshot: Optional[bytes] = None):
        self.id = sandbox_id
        self.fs = VirtualFS()
        self.servers: Dict[int, Callable] = {}  # port -> handler
        self.wasm = WasmEngine(snapshot)
        self.ws_clients = set()
        self.is_running = False
        
    async def start(self):
        """Initialize the sandbox runtime"""
        self.is_running = True
        # Restore from snapshot if provided
        if self.wasm.snapshot:
            await self.wasm.restore_from_snapshot()
            
    async def handle_http(self, request):
        """Handle HTTP requests to the sandbox"""
        port = request.scope.get("sandbox_port")
        if not port:
            return Response("Invalid request", status=400)
            
        server = self.servers.get(port)
        if not server:
            return Response("Port not listening", status=502)
        
        return await server(request)
        
    async def serve(self, port: int, handler: Callable):
        """Register an HTTP handler for a specific port"""
        self.servers[port] = handler
        
    async def exec_python(self, code: str):
        """Execute Python code in the sandbox"""
        return await self.wasm.exec_python(code)
        
    async def write_file(self, path: str, content: str):
        """Write content to a file in the virtual filesystem"""
        await self.fs.write(path, content.encode())
        
    async def read_file(self, path: str) -> bytes:
        """Read content from a file in the virtual filesystem"""
        return await self.fs.read(path)
        
    async def exec(self, cmd: str, arg: str):
        """Execute a command in the sandbox"""
        if cmd == "python":
            code = await self.fs.read(arg)
            return await self.wasm.exec_python(code.decode())
        elif cmd == "node":
            # Execute JavaScript in WASM
            code = await self.fs.read(arg)
            return await self.wasm.exec_javascript(code.decode())
        else:
            raise ValueError(f"Command '{cmd}' not allowed")
            
    async def snapshot(self) -> bytes:
        """Create a snapshot of the current sandbox state"""
        return await self.wasm.create_snapshot()
        
    async def stop(self):
        """Stop the sandbox runtime"""
        self.is_running = False
        # Clean up resources
        for ws in self.ws_clients:
            await ws.close()
        self.ws_clients.clear()
```

### 2. Virtual File System

A virtual filesystem that provides file operations within the sandbox:

```python
# sandbox/virtual_fs.py
import asyncio
from typing import Optional
import os

class VirtualFS:
    def __init__(self):
        self.files: Dict[str, bytes] = {}
        self.mounts = {}  # External storage mounts
        
    async def read(self, path: str) -> bytes:
        """Read a file from the virtual filesystem"""
        if path in self.files:
            return self.files[path]
        raise FileNotFoundError(f"File not found: {path}")
        
    async def write(self, path: str, content: bytes):
        """Write content to a file in the virtual filesystem"""
        # Validate path to prevent directory traversal
        if ".." in path:
            raise ValueError("Invalid path: directory traversal detected")
        
        self.files[path] = content
        
    async def list_dir(self, path: str) -> list:
        """List files in a directory"""
        # Implementation for listing directory contents
        pass
        
    async def delete(self, path: str):
        """Delete a file from the virtual filesystem"""
        if path in self.files:
            del self.files[path]
```

### 3. WASM Execution Engine

A secure execution environment using WebAssembly:

```python
# sandbox/wasm_engine.py
import asyncio
from typing import Optional
import pyodide

class WasmEngine:
    def __init__(self, snapshot: Optional[bytes] = None):
        self.snapshot = snapshot
        self.runtime = None
        self.timeout_limit = 30  # seconds
        self.memory_limit = 100 * 1024 * 1024  # 100MB
        
    async def initialize(self):
        """Initialize the WASM runtime"""
        # Initialize Pyodide or other WASM runtime
        self.runtime = await pyodide.loadPyodide()
        
    async def exec_python(self, code: str):
        """Execute Python code in the WASM environment"""
        try:
            # Set up execution context with resource limits
            result = await asyncio.wait_for(
                self._execute_with_context(code),
                timeout=self.timeout_limit
            )
            return result
        except asyncio.TimeoutError:
            raise TimeoutError("Execution timed out")
            
    async def _execute_with_context(self, code: str):
        """Execute code with security context"""
        # Execute in isolated WASM environment
        return await self.runtime.runPythonAsync(code)
        
    async def exec_javascript(self, code: str):
        """Execute JavaScript code in the WASM environment"""
        # Implementation for JS execution
        pass
        
    async def create_snapshot(self) -> bytes:
        """Create a snapshot of the current WASM state"""
        # Implementation for creating state snapshot
        pass
        
    async def restore_from_snapshot(self):
        """Restore the WASM state from a snapshot"""
        # Implementation for restoring state
        pass
```

## Preview URL System

### 4. Ingress Router

The ingress router handles public HTTP traffic and routes it to specific sandboxes:

```python
# ingress/router.py
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response
from sandbox.manager import get_sandbox

app = FastAPI()

@app.api_route("/preview/{sandbox_id}/{port}/{path:path}", 
               methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def preview_handler(
    request: Request, 
    sandbox_id: str, 
    port: int, 
    path: str
):
    """Route preview requests to the appropriate sandbox"""
    try:
        sandbox = await get_sandbox(sandbox_id)
        
        # Validate port is allowed
        if port not in sandbox.servers:
            return Response("Port not listening", status_code=502)
        
        # Set up request context for the sandbox
        request.scope["sandbox_port"] = port
        request.scope["sandbox_path"] = path
        request.scope["sandbox_id"] = sandbox_id
        
        return await sandbox.handle_http(request)
        
    except Exception as e:
        return Response(f"Error: {str(e)}", status_code=500)

@app.websocket("/preview/{sandbox_id}/{port}")
async def ws_preview_handler(
    websocket: WebSocket, 
    sandbox_id: str, 
    port: int
):
    """Handle WebSocket connections to sandbox services"""
    await websocket.accept()
    
    try:
        sandbox = await get_sandbox(sandbox_id)
        
        # Add WebSocket to sandbox's client list
        sandbox.ws_clients.add(websocket)
        
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            
            # Handle the message in the sandbox
            response = await sandbox.handle_ws_message(port, data)
            
            # Send response back to client
            await websocket.send_text(response)
            
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        # Clean up WebSocket connection
        if websocket in sandbox.ws_clients:
            sandbox.ws_clients.remove(websocket)
        await websocket.close()
```

### 5. Preview URL Management

A service to manage and generate preview URLs:

```python
# sandbox/preview_service.py
from typing import Dict
import uuid
from urllib.parse import urljoin

class PreviewService:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.active_previews: Dict[str, Dict] = {}  # sandbox_id -> info
        
    def generate_preview_url(self, sandbox_id: str, port: int) -> str:
        """Generate a preview URL for a sandbox and port"""
        url = f"{self.base_url}/preview/{sandbox_id}/{port}"
        return url
        
    async def register_preview(self, sandbox_id: str, port: int, metadata: dict = None):
        """Register a new preview endpoint"""
        preview_id = str(uuid.uuid4())
        
        self.active_previews[sandbox_id] = {
            "preview_id": preview_id,
            "port": port,
            "created_at": time.time(),
            "metadata": metadata or {}
        }
        
        return preview_id
        
    async def deregister_preview(self, sandbox_id: str):
        """Remove a preview endpoint"""
        if sandbox_id in self.active_previews:
            del self.active_previews[sandbox_id]
            
    def get_active_previews(self) -> Dict:
        """Get all active preview endpoints"""
        return self.active_previews.copy()
```

## Security Model

### 6. Isolation and Security Controls

The system implements multiple layers of security:

```python
# sandbox/security.py
import resource
import sys
import time
from typing import Optional

class SecurityContext:
    def __init__(self):
        self.max_execution_time = 30  # seconds
        self.max_memory = 100 * 1024 * 1024  # 100MB
        self.allowed_commands = {"python", "node", "ls", "cat", "echo"}
        self.file_access_whitelist = ["/tmp", "/workspace"]
        
    def enforce_limits(self):
        """Enforce system resource limits"""
        # Set memory limit
        resource.setrlimit(resource.RLIMIT_AS, (self.max_memory, self.max_memory))
        
        # Set CPU time limit
        resource.setrlimit(resource.RLIMIT_CPU, (self.max_execution_time, self.max_execution_time))
        
    def validate_path(self, path: str) -> bool:
        """Validate file path to prevent directory traversal"""
        if ".." in path:
            return False

        # Check if path is in allowed directories
        for allowed_dir in self.file_access_whitelist:
            if path.startswith(allowed_dir):
                return True

        return False
        
    def validate_command(self, cmd: str) -> bool:
        """Validate if command is allowed"""
        return cmd in self.allowed_commands
        
    def sanitize_input(self, input_str: str) -> str:
        """Sanitize user input to prevent injection attacks"""
        # Remove dangerous characters
        dangerous_chars = [";", "&", "|", "`", "$", "(", ")"]
        sanitized = input_str
        for char in dangerous_chars:
            sanitized = sanitized.replace(char, "")
        return sanitized
```

### 7. Network Security

Network access controls to prevent unauthorized connections:

```python
# sandbox/network_security.py
import socket
from contextlib import contextmanager

class NetworkSecurity:
    def __init__(self):
        self.allowed_hosts = set()
        self.blocked_hosts = {"localhost", "127.0.0.1", "::1"}
        self.outbound_connections = []
        
    @contextmanager
    def restricted_socket(self):
        """Context manager to restrict socket operations"""
        original_socket = socket.socket
        # Capture the current instance's attributes to pass to RestrictedSocket
        blocked_hosts = self.blocked_hosts
        allowed_hosts = self.allowed_hosts
        outbound_connections = self.outbound_connections

        class RestrictedSocket:
            def __init__(self, family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0, fileno=None):
                if family != socket.AF_INET or type != socket.SOCK_STREAM:
                    raise PermissionError("Only TCP IPv4 connections allowed")

            def connect(self, address):
                host, port = address
                if host in blocked_hosts:
                    raise PermissionError(f"Connection to {host} blocked")
                if host not in allowed_hosts and not self._is_allowed_port(port):
                    raise PermissionError(f"Connection to {host}:{port} not allowed")

                # Track outbound connection
                outbound_connections.append(address)
                # Note: This simplified example doesn't actually make the connection
                # In a real implementation, you'd need to handle the actual socket connection differently

            def _is_allowed_port(self, port: int) -> bool:
                # Allow only common web ports
                return port in [80, 443, 8080, 3000, 5000, 8000]

        socket.socket = RestrictedSocket
        try:
            yield
        finally:
            socket.socket = original_socket
```

## Deployment Options

### 8. Local/Bare Metal Deployment

For local deployments using systemd and FastAPI:

```ini
# sandbox-pool.service
[Unit]
Description=Sandbox Pool Service
After=network.target

[Service]
Type=simple
User=sandbox-user
WorkingDirectory=/opt/sandbox-system
ExecStart=/usr/bin/python3 -m sandbox.pool_manager
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 9. Kubernetes Deployment

For containerized deployments:

```yaml
# k8s/sandbox-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sandbox-manager
spec:
  replicas: 3
  selector:
    matchLabels:
      app: sandbox-manager
  template:
    metadata:
      labels:
        app: sandbox-manager
    spec:
      containers:
      - name: sandbox-manager
        image: sandbox-manager:latest
        ports:
        - containerPort: 8000
        env:
        - name: BASE_URL
          value: "https://my-sandbox-platform.com"
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
---
apiVersion: v1
kind: Service
metadata:
  name: sandbox-service
spec:
  selector:
    app: sandbox-manager
  ports:
    - protocol: TCP
      port: 80
      targetPort: 8000
  type: LoadBalancer
```

### 10. Firecracker MicroVM Implementation

For enhanced security using MicroVMs:

```python
# sandbox/firecracker_runtime.py
import asyncio
import json
import subprocess
from pathlib import Path
from typing import Optional

class FirecrackerRuntime:
    def __init__(self, vm_id: str, kernel_path: str, rootfs_path: str):
        self.vm_id = vm_id
        self.kernel_path = kernel_path
        self.rootfs_path = rootfs_path
        self.vm_process = None
        self.socket_path = f"/tmp/firecracker-{vm_id}.socket"
        
    async def start_vm(self):
        """Start the Firecracker VM"""
        cmd = [
            "firecracker",
            "--api-sock", self.socket_path,
            "--config-file", self._create_config()
        ]
        
        self.vm_process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Wait for VM to boot
        await asyncio.sleep(2)
        
    def _create_config(self) -> str:
        """Create Firecracker configuration"""
        config = {
            "boot-source": {
                "kernel_image_path": self.kernel_path,
                "boot_args": "console=ttyS0 reboot=k panic=1 pci=off"
            },
            "drives": [
                {
                    "drive_id": "rootfs",
                    "path_on_host": self.rootfs_path,
                    "is_root_device": True,
                    "is_read_only": False
                }
            ],
            "machine-config": {
                "vcpu_count": 2,
                "mem_size_mib": 1024,
                "ht_enabled": False
            }
        }
        
        config_path = f"/tmp/firecracker-config-{self.vm_id}.json"
        with open(config_path, 'w') as f:
            json.dump(config, f)
            
        return config_path
        
    async def execute_in_vm(self, command: str) -> str:
        """Execute a command inside the VM"""
        # Send command via Firecracker API
        # Implementation details for VM communication
        pass
        
    async def stop_vm(self):
        """Stop the Firecracker VM"""
        if self.vm_process:
            self.vm_process.terminate()
            await self.vm_process.wait()
```

## User API Interface

### 11. SDK-Like Interface

Provide a familiar API similar to Cloudflare's Sandbox SDK:

```python
# sandbox/client.py
import asyncio
import aiohttp
from typing import Optional, Dict, Any

class SandboxClient:
    def __init__(self, base_url: str, api_key: Optional[str] = None):
        self.base_url = base_url
        self.api_key = api_key
        self.session: Optional[aiohttp.ClientSession] = None
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
            
    async def create_sandbox(self, metadata: Optional[Dict] = None) -> str:
        """Create a new sandbox instance"""
        async with self.session.post(
            f"{self.base_url}/sandboxes",
            json={"metadata": metadata or {}},
            headers=self._get_headers()
        ) as resp:
            result = await resp.json()
            return result["sandbox_id"]
            
    async def get_sandbox(self, sandbox_id: str):
        """Get a sandbox instance"""
        return Sandbox(self, sandbox_id)
        
    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

class Sandbox:
    def __init__(self, client: SandboxClient, sandbox_id: str):
        self.client = client
        self.id = sandbox_id
        
    async def exec_python(self, code: str) -> Dict[str, Any]:
        """Execute Python code in the sandbox"""
        async with self.client.session.post(
            f"{self.client.base_url}/sandboxes/{self.id}/exec",
            json={"language": "python", "code": code},
            headers=self.client._get_headers()
        ) as resp:
            return await resp.json()
            
    async def write_file(self, path: str, content: str):
        """Write content to a file in the sandbox"""
        async with self.client.session.put(
            f"{self.client.base_url}/sandboxes/{self.id}/files/{path}",
            data=content.encode(),
            headers=self.client._get_headers()
        ) as resp:
            return resp.status == 200
            
    async def read_file(self, path: str) -> str:
        """Read content from a file in the sandbox"""
        async with self.client.session.get(
            f"{self.client.base_url}/sandboxes/{self.id}/files/{path}",
            headers=self.client._get_headers()
        ) as resp:
            return await resp.text()
            
    async def serve(self, port: int, handler_func):
        """Register an HTTP handler for a port in the sandbox"""
        # This would typically involve sending the handler code to the sandbox
        # and registering it with the internal HTTP server
        pass
        
    async def get_preview_url(self, port: int) -> str:
        """Get the preview URL for a specific port"""
        return f"{self.client.base_url}/preview/{self.id}/{port}"

# Usage example
async def main():
    async with SandboxClient("https://my-sandbox-platform.com") as client:
        # Create a new sandbox
        sandbox_id = await client.create_sandbox({"purpose": "testing"})
        sandbox = await client.get_sandbox(sandbox_id)
        
        # Execute Python code
        result = await sandbox.exec_python("print('Hello from sandbox!')")
        print(result)
        
        # Write a file
        await sandbox.write_file("/workspace/hello.py", """
import time
print(f"Current time: {time.time()}")
""")
        
        # Read the file back
        content = await sandbox.read_file("/workspace/hello.py")
        print(content)
        
        # Get a preview URL
        preview_url = await sandbox.get_preview_url(3000)
        print(f"Preview URL: {preview_url}")

if __name__ == "__main__":
    asyncio.run(main())
```

## Performance Optimizations

### 12. Snapshot and Restore System

Efficient cold start optimization using snapshots:

```python
# sandbox/snapshot_manager.py
import asyncio
import pickle
import zstandard as zstd
from typing import Optional, Dict
import time

class SnapshotManager:
    def __init__(self, storage_backend):
        self.storage = storage_backend
        self.compressor = zstd.ZstdCompressor(level=10)
        self.decompressor = zstd.ZstdDecompressor()
        
    async def create_snapshot(self, sandbox_id: str, state_data: Dict) -> str:
        """Create a compressed snapshot of sandbox state"""
        # Serialize state
        serialized_state = pickle.dumps(state_data)
        
        # Compress the state
        compressed_state = self.compressor.compress(serialized_state)
        
        # Generate snapshot ID
        snapshot_id = f"{sandbox_id}-{int(time.time())}"
        
        # Store in backend
        await self.storage.put(f"snapshots/{snapshot_id}", compressed_state)
        
        return snapshot_id
        
    async def restore_snapshot(self, snapshot_id: str) -> Optional[Dict]:
        """Restore sandbox state from snapshot"""
        try:
            # Retrieve from backend
            compressed_state = await self.storage.get(f"snapshots/{snapshot_id}")
            
            # Decompress
            serialized_state = self.decompressor.decompress(compressed_state)
            
            # Deserialize
            state_data = pickle.loads(serialized_state)
            
            return state_data
        except Exception:
            return None
            
    async def cleanup_old_snapshots(self, retention_days: int = 7):
        """Clean up snapshots older than retention period"""
        cutoff_time = time.time() - (retention_days * 24 * 3600)
        
        snapshots = await self.storage.list("snapshots/")
        for snapshot_key in snapshots:
            timestamp = int(snapshot_key.split("-")[-1])
            if timestamp < cutoff_time:
                await self.storage.delete(snapshot_key)
```

### 13. Resource Pool Management

Efficient management of sandbox resources:

```python
# sandbox/pool_manager.py
import asyncio
from typing import Dict, List, Optional
from collections import deque
import time

class SandboxPool:
    def __init__(self, max_size: int = 100, idle_timeout: int = 300):
        self.max_size = max_size
        self.idle_timeout = idle_timeout
        self.active_sandboxes: Dict[str, 'SandboxRuntime'] = {}
        self.idle_sandboxes: deque = deque()
        self.creation_lock = asyncio.Lock()
        
    async def get_sandbox(self, sandbox_id: Optional[str] = None) -> 'SandboxRuntime':
        """Get an available sandbox, creating one if needed"""
        async with self.creation_lock:
            # Try to get an idle sandbox
            if self.idle_sandboxes:
                sandbox = self.idle_sandboxes.popleft()
                sandbox.id = sandbox_id or f"sandbox-{len(self.active_sandboxes)}"
                self.active_sandboxes[sandbox.id] = sandbox
                return sandbox
                
            # Create new sandbox if under limit
            if len(self.active_sandboxes) < self.max_size:
                sandbox = await self._create_new_sandbox(sandbox_id)
                self.active_sandboxes[sandbox.id] = sandbox
                return sandbox
                
            # Wait for an available sandbox (implement queueing)
            raise RuntimeError("Sandbox pool exhausted")
            
    async def return_sandbox(self, sandbox: 'SandboxRuntime'):
        """Return a sandbox to the pool"""
        if sandbox.id in self.active_sandboxes:
            del self.active_sandboxes[sandbox.id]
            
        # Reset sandbox state
        await sandbox.reset()
        
        # Add to idle pool if under size limit
        if len(self.idle_sandboxes) < self.max_size:
            self.idle_sandboxes.append(sandbox)
        else:
            # Destroy if pool is full
            await sandbox.destroy()
            
    async def _create_new_sandbox(self, sandbox_id: Optional[str] = None) -> 'SandboxRuntime':
        """Create a new sandbox instance"""
        from .runtime import SandboxRuntime
        
        sandbox_id = sandbox_id or f"sandbox-{int(time.time() * 1000000)}"
        sandbox = SandboxRuntime(sandbox_id)
        await sandbox.start()
        return sandbox
        
    async def cleanup_idle_sandboxes(self):
        """Periodically clean up idle sandboxes"""
        current_time = time.time()
        expired_sandboxes = []
        
        for sandbox in list(self.idle_sandboxes):
            if hasattr(sandbox, 'last_used') and \
               current_time - sandbox.last_used > self.idle_timeout:
                expired_sandboxes.append(sandbox)
                
        for sandbox in expired_sandboxes:
            if sandbox in self.idle_sandboxes:
                self.idle_sandboxes.remove(sandbox)
                await sandbox.destroy()
                
    async def get_stats(self) -> Dict:
        """Get pool statistics"""
        return {
            "active_count": len(self.active_sandboxes),
            "idle_count": len(self.idle_sandboxes),
            "max_size": self.max_size,
            "utilization": len(self.active_sandboxes) / self.max_size
        }
```

## Conclusion

This technical plan outlines a comprehensive approach to building a serverless worker system with secure sandboxing capabilities. The architecture provides:

1. **Secure Isolation**: Multiple layers of security including WASM execution, network restrictions, and resource limits
2. **Preview URLs**: Full HTTP routing system that mimics Cloudflare's preview functionality
3. **State Management**: Efficient snapshot and restore mechanisms for fast cold starts
4. **Flexible Deployment**: Options for local, containerized, or MicroVM deployments
5. **Developer Experience**: Familiar API interface similar to existing sandbox SDKs

The system balances security, performance, and developer experience while remaining vendor-independent and deployable on various infrastructure platforms.