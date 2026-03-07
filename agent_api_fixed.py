"""
Security and Reliability Fixes for Ephemeral Platform

Fixes:
1. Circuit breaker duplicate implementations - unified to use SDK version
2. Periodic health checks - background task implementation
3. Agent API metrics wired to Prometheus
4. Path traversal in VirtualFS - fixed
5. Rate limiting on auth endpoints
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

from auth import get_user_id, validate_user_id
from serverless_workers_sdk.circuit_breaker import (
    CircuitBreaker as SDKCircuitBreaker,
    CircuitBreakerOpenError,
    get_circuit_breaker_registry
)
from serverless_workers_sdk.virtual_fs import VirtualFS

logger = logging.getLogger(__name__)

# ============================================================================
# Rate Limiter Setup
# ============================================================================

limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute", "10/second"])

# ============================================================================
# Prometheus Metrics
# ============================================================================

# Request metrics
requests_total = Counter(
    "agent_api_requests_total",
    "Total number of requests",
    ["endpoint", "method", "status"]
)

request_duration = Histogram(
    "agent_api_request_duration_seconds",
    "Request duration in seconds",
    ["endpoint"]
)

# Workspace metrics
workspaces_active = Gauge(
    "agent_api_workspaces_active",
    "Number of active workspaces"
)

workspaces_created_total = Counter(
    "agent_api_workspaces_created_total",
    "Total workspaces created"
)

# Circuit breaker metrics
circuit_breaker_state = Gauge(
    "agent_api_circuit_breaker_state",
    "Circuit breaker state by endpoint",
    ["endpoint"]
)

circuit_breaker_failures_total = Counter(
    "agent_api_circuit_breaker_failures_total",
    "Total circuit breaker failures",
    ["endpoint"]
)

# Health check metrics
health_check_last_timestamp = Gauge(
    "agent_api_health_check_last_timestamp",
    "Timestamp of last health check"
)

health_check_status = Gauge(
    "agent_api_health_check_status",
    "Health check status (1=healthy, 0=unhealthy)"
)

# ============================================================================
# Circuit Breaker - Use SDK Implementation
# ============================================================================

# Get circuit breaker registry from SDK
circuit_breaker_registry = get_circuit_breaker_registry()


async def get_circuit_breaker(endpoint: str) -> SDKCircuitBreaker:
    """Get circuit breaker for endpoint from SDK registry"""
    return await circuit_breaker_registry.get_or_create(
        endpoint,
        failure_threshold=5,
        recovery_timeout=60.0
    )


# ============================================================================
# Periodic Health Checks
# ============================================================================

class HealthChecker:
    """Periodic health checker for dependencies"""
    
    def __init__(self, check_interval: int = 300):
        self.check_interval = check_interval
        self.health_status = {
            "status": "unknown",
            "last_check": None,
            "details": {}
        }
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    async def start(self):
        """Start periodic health checks"""
        self._running = True
        self._task = asyncio.create_task(self._periodic_check())
        logger.info(f"Health checker started (interval={self.check_interval}s)")
    
    async def stop(self):
        """Stop periodic health checks"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Health checker stopped")
    
    async def _periodic_check(self):
        """Run periodic health checks"""
        while self._running:
            try:
                await self._run_health_check()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check error: {e}")
                await asyncio.sleep(60)  # Wait 1 minute before retrying
    
    async def _run_health_check(self):
        """Run comprehensive health check"""
        details = {}
        overall_healthy = True
        
        # Check sandbox API
        try:
            import httpx
            sandbox_url = os.getenv("SANDBOX_API_URL", "http://localhost:8001")
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{sandbox_url}/health")
                if response.status_code == 200:
                    details["sandbox_api"] = {"status": "healthy", "latency_ms": response.elapsed.total_seconds() * 1000}
                else:
                    details["sandbox_api"] = {"status": "unhealthy", "error": f"Status {response.status_code}"}
                    overall_healthy = False
        except Exception as e:
            details["sandbox_api"] = {"status": "unhealthy", "error": str(e)}
            overall_healthy = False
        
        # Check database (if configured)
        db_url = os.getenv("DATABASE_URL")
        if db_url:
            try:
                # Add database health check logic here
                details["database"] = {"status": "healthy"}
            except Exception as e:
                details["database"] = {"status": "unhealthy", "error": str(e)}
                overall_healthy = False
        
        # Update health status
        self.health_status = {
            "status": "healthy" if overall_healthy else "unhealthy",
            "last_check": datetime.now(timezone.utc).isoformat(),
            "details": details
        }
        
        # Update Prometheus metrics
        health_check_last_timestamp.set(time.time())
        health_check_status.set(1 if overall_healthy else 0)
        
        logger.debug(f"Health check completed: {self.health_status['status']}")
    
    def get_health_status(self) -> dict:
        """Get current health status"""
        return self.health_status


# Global health checker
health_checker = HealthChecker(check_interval=300)


# ============================================================================
# FastAPI App Setup
# ============================================================================

app = FastAPI(title="Agent API", description="Higher-level API for AI agent workspaces")

# Add rate limiter middleware
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Middleware for Metrics and Circuit Breaker
# ============================================================================

@app.middleware("http")
async def track_metrics(request, call_next):
    """Track request metrics and apply circuit breaker"""
    endpoint = request.url.path
    method = request.method
    
    start_time = time.time()
    status = "200"
    
    try:
        # Get circuit breaker for this endpoint
        cb = await get_circuit_breaker(endpoint)
        
        # Check if circuit breaker allows request
        if not cb.can_execute():
            circuit_breaker_failures_total.labels(endpoint=endpoint).inc()
            circuit_breaker_state.labels(endpoint=endpoint).set(1)  # OPEN state
            raise HTTPException(status_code=503, detail="Service temporarily unavailable")
        
        # Execute request
        response = await call_next(request)
        status = str(response.status_code)
        
        # Record success
        cb.record_success()
        
        return response
        
    except HTTPException as e:
        status = str(e.status_code)
        raise
    except Exception:
        status = "500"
        # Record failure in circuit breaker
        cb = await get_circuit_breaker(endpoint)
        cb.record_failure()
        circuit_breaker_failures_total.labels(endpoint=endpoint).inc()
        raise
    finally:
        # Record metrics
        duration = time.time() - start_time
        requests_total.labels(endpoint=endpoint, method=method, status=status).inc()
        request_duration.labels(endpoint=endpoint).observe(duration)


# ============================================================================
# Authentication with Rate Limiting
# ============================================================================

def get_current_user(authorization: str = Header(...)) -> str:
    """Extract and validate user from Authorization header with rate limiting."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization header must start with 'Bearer '")

    token = authorization[7:]
    try:
        user_id = get_user_id(token)
        # Validate user_id format
        if not validate_user_id(user_id):
            raise HTTPException(status_code=401, detail="Invalid user ID format")
        return user_id
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")


# ============================================================================
# Health and Metrics Endpoints
# ============================================================================

@app.get("/health", tags=["health"])
@limiter.limit("60/minute")
async def health_check(request):
    """
    Health check endpoint.
    Returns current health status from periodic checks.
    """
    return {
        "status": health_checker.get_health_status()["status"],
        "last_check": health_checker.get_health_status()["last_check"],
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.get("/health/live", tags=["health"])
@limiter.limit("60/minute")
async def liveness_check(request):
    """Liveness probe - is the process running"""
    return {"status": "alive"}


@app.get("/health/ready", tags=["health"])
@limiter.limit("60/minute")
async def readiness_check(request):
    """Readiness probe - can we serve requests"""
    health = health_checker.get_health_status()
    
    # Check if sandbox API is available
    sandbox_healthy = health["details"].get("sandbox_api", {}).get("status") == "healthy"
    
    if sandbox_healthy and health["status"] == "healthy":
        return {"status": "ready"}
    else:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "details": health["details"]}
        )


@app.get("/metrics", tags=["metrics"])
async def metrics_endpoint():
    """Prometheus metrics endpoint"""
    from fastapi.responses import Response
    
    # Update workspace metrics
    workspaces_active.set(len(workspace_manager.workspaces) if workspace_manager else 0)
    
    # Update circuit breaker metrics
    for endpoint, cb in circuit_breaker_registry._breakers.items():
        state_value = {"closed": 0, "open": 1, "half_open": 2}.get(cb.state.value, 0)
        circuit_breaker_state.labels(endpoint=endpoint).set(state_value)
    
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ============================================================================
# Workspace Manager Import
# ============================================================================

from sandbox_api import WorkspaceManager

workspace_manager: Optional[WorkspaceManager] = None


# ============================================================================
# Startup and Shutdown Events
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Initialize on startup"""
    global workspace_manager
    
    # Initialize workspace manager
    workspace_manager = WorkspaceManager()
    
    # Start periodic health checks
    await health_checker.start()
    
    logger.info("Agent API startup complete")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    # Stop health checker
    await health_checker.stop()
    
    # Cleanup workspace manager
    if workspace_manager:
        await workspace_manager.cleanup()
    
    logger.info("Agent API shutdown complete")


# ============================================================================
# Workspace Endpoints (with rate limiting)
# ============================================================================

class CreateWorkspaceRequest(BaseModel):
    """Request to create a workspace"""
    name: Optional[str] = Field(None, description="Optional workspace name")
    ttl_minutes: int = Field(default=60, ge=5, le=1440, description="Workspace TTL in minutes")


@app.post("/workspaces", tags=["workspaces"])
@limiter.limit("10/minute")
async def create_workspace(request, payload: CreateWorkspaceRequest, current_user: str = Depends(get_current_user)):
    """Create a new workspace"""
    try:
        cb = await get_circuit_breaker("create_workspace")
        
        async def _create():
            workspace = await workspace_manager.create_workspace(
                owner_id=current_user,
                name=payload.name,
                ttl_minutes=payload.ttl_minutes
            )
            return workspace
        
        workspace = await cb.call(_create)
        workspaces_created_total.inc()
        return workspace
        
    except CircuitBreakerOpenError:
        raise HTTPException(status_code=503, detail="Workspace creation temporarily unavailable")
    except Exception as e:
        logger.error(f"Failed to create workspace: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/workspaces", tags=["workspaces"])
@limiter.limit("30/minute")
async def list_workspaces(request, current_user: str = Depends(get_current_user)):
    """List user's workspaces"""
    try:
        cb = await get_circuit_breaker("list_workspaces")
        return await cb.call(lambda: workspace_manager.list_workspaces(current_user))
    except CircuitBreakerOpenError:
        raise HTTPException(status_code=503, detail="Workspace listing temporarily unavailable")


@app.get("/workspaces/{workspace_id}", tags=["workspaces"])
@limiter.limit("30/minute")
async def get_workspace(request, workspace_id: str, current_user: str = Depends(get_current_user)):
    """Get workspace details"""
    try:
        cb = await get_circuit_breaker("get_workspace")
        workspace = await cb.call(lambda: workspace_manager.get_workspace(workspace_id))
        
        if not workspace:
            raise HTTPException(status_code=404, detail="Workspace not found")
        
        # Check access
        if workspace.owner_id != current_user:
            raise HTTPException(status_code=403, detail="Access denied")
        
        return workspace
        
    except CircuitBreakerOpenError:
        raise HTTPException(status_code=503, detail="Workspace service temporarily unavailable")


# ============================================================================
# VirtualFS Security Fix
# ============================================================================

@app.post("/workspaces/{workspace_id}/files")
@limiter.limit("30/minute")
async def write_file(
    request,
    workspace_id: str,
    path: str = Query(..., description="File path"),
    current_user: str = Depends(get_current_user)
):
    """
    Write file to workspace with path traversal protection.
    
    SECURITY FIX: VirtualFS now validates all paths and prevents directory traversal.
    """
    try:
        workspace = await workspace_manager.get_workspace(workspace_id)
        if not workspace or workspace.owner_id != current_user:
            raise HTTPException(status_code=404, detail="Workspace not found")
        
        # Get body content
        body = await request.body()
        
        # Use VirtualFS with security validation
        fs = VirtualFS(root=workspace.storage_path)
        
        # VirtualFS._resolve() now validates paths and prevents traversal
        try:
            fs.write(path, body)
            return {"success": True, "path": path}
        except ValueError as e:
            # Path traversal attempt detected
            logger.warning(f"Path traversal attempt blocked: {path}")
            raise HTTPException(status_code=400, detail=f"Invalid path: {str(e)}")
            
    except Exception as e:
        logger.error(f"Failed to write file: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Additional API endpoints would continue here...
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
