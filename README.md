# Cloud Terminal Platform

A production-grade cloud terminal platform similar to Zo.computer, featuring user identity management, workspace isolation, snapshot/restore capabilities, multi-agent workspace sharing, a pluggable container runtime, and a worker marketplace.

## Overview

This platform provides:

- **Real Identity**: JWT-based authentication with external IdP integration
- **Stateless Control Plane**: API-driven container and workspace management
- **Portable User State**: Filesystem-based snapshots for pause/resume
- **Agent Workspace API**: Higher-level workspace abstraction for AI agents with multi-agent sharing
- **Pluggable Container Runtime**: Firecracker microVM or process-based backend, auto-detected
- **S3/MinIO Storage Backend**: Remote snapshot storage with multipart upload support
- **Prometheus Metrics**: Built-in `/metrics` endpoint with request, sandbox, and snapshot metrics
- **WebSocket Terminal**: Interactive shell access via xterm.js-compatible WebSocket
- **Worker Marketplace**: Publish and discover reusable workers
- **Resource Quotas**: Per-sandbox execution, memory, storage, and network limits
- **Disaster Recovery**: Snapshot backup and restoration with retry logic
- **Rate Limiting**: Per-client API rate limiting with burst protection
- **Tool Integrations**: 150+ pre-built tool integrations via Composio (GitHub, Slack, Notion, etc.)
- **Event Bus**: Cross-service event-driven architecture for auditing and extensibility
- **Input Validation**: Comprehensive security validation for all user inputs

## Architecture

```
Identity (JWT)
 ↓
┌─────────────────────────────────────┐
│           API Gateway               │
│     + Rate Limiting Middleware      │
├──────────┬──────────┬───────────────┤
│ Sandbox  │ Snapshot │ Agent         │
│ API      │ API      │ Workspace API │
├──────────┴──────────┴───────────────┤
│       Container Runtime             │
│   (Firecracker / Process)           │
├─────────────────────────────────────┤
│  Storage │ Metrics │ Quota Manager  │
│  (S3)    │ (Prom)  │               │
├─────────────────────────────────────┤
│  Event Bus │ Tool Integrations      │
│  (Pub/Sub) │ (Composio SDK)         │
└─────────────────────────────────────┘
```

## Components

### 1. Authentication Module (`auth.py`)

- JWT token validation
- User ID extraction
- Workspace/container mapping

### 2. Sandbox API (`sandbox_api.py`)

- REST API for sandbox lifecycle (create, exec, keepalive, mount, destroy)
- File read/write/list operations within sandboxes
- Preview URL registration
- Background job management
- WebSocket terminal endpoint (`/sandboxes/{id}/terminal`)

### 3. Snapshot API (`snapshot_api.py`)

- REST API for snapshot create/restore/list/delete
- Automatic retention enforcement
- Prometheus metrics integration

### 4. Snapshot Manager (`snapshot_manager.py`)

- Pure-Python snapshot creation and restoration (replaces shell scripts)
- Zstandard-compressed tar archives
- Retry logic with exponential backoff
- Optional remote storage backend support

### 5. Agent Workspace API (`agent_api.py`)

- Higher-level workspace abstraction for AI agents
- Workspace CRUD with tagging
- Multi-agent sharing with read/write/admin permissions
- Command execution delegation to sandboxes
- Worker marketplace (publish, search, discover)

### 6. Container Runtime (`serverless_workers_sdk/container_runtime.py`)

- Abstract `ContainerRuntime` interface with pluggable backends
- `FirecrackerRuntime`: Full microVM isolation via Firecracker API sockets
- `ProcessRuntime`: Lightweight filesystem-based fallback
- Auto-detection factory (`create_runtime("auto")`)

### 7. Storage Backend (`serverless_workers_sdk/storage.py`)

- `S3StorageBackend`: S3/MinIO-compatible with multipart upload for large snapshots
- `LocalStorageBackend`: Filesystem-based for development
- Auto-detection from environment variables

### 8. Metrics (`serverless_workers_sdk/metrics.py`)

- Prometheus-compatible text format exposition
- Counter, Gauge, and Histogram metric types
- Pre-defined metrics: sandbox creation, execution, snapshots, HTTP requests, quota violations
- FastAPI middleware for automatic request instrumentation

### 9. Resource Quotas (`serverless_workers_sdk/quota.py`)

- Per-sandbox execution rate limiting (rolling 1-hour window)
- Concurrent sandbox limits
- Memory, storage, CPU, and network egress tracking
- Warning thresholds at 80% utilization

### 10. Preview Router (`preview_router.py`)

- HTTP reverse proxy into sandbox preview ports
- Automatic fallback container promotion on upstream failure
- Health checking and target registry

### 11. Rate Limiting (`serverless_workers_sdk/rate_limiter.py`)

- Per-client rate limiting based on IP and User-Agent
- Configurable sustained and burst limits
- Automatic window cleanup to prevent memory leaks
- Whitelist support for trusted clients
- Standard rate limit headers (X-RateLimit-*, Retry-After)

### 12. Configuration (`serverless_workers_sdk/config.py`)

- Centralized Pydantic-based configuration
- Environment variable overrides
- Type-safe settings with validation
- Support for all service configuration options

### 13. Event Bus (`serverless_workers_sdk/event_bus.py`)

- Pub/sub event-driven architecture
- Synchronous and asynchronous event handlers
- Event history for debugging and replay
- Pre-defined event types for all major operations
- Error handling with graceful degradation

### 14. Tool Integration (`serverless_workers_sdk/tool_integration.py`)

- Composio SDK integration for 150+ tools
- Per-sandbox tool configuration
- OAuth token management
- Pre-built tool sets for common roles (developer, analyst, etc.)
- FastAPI routes for tool management

### 15. Input Validation (`serverless_workers_sdk/validation.py`)

- File path validation with directory traversal prevention
- Command and argument validation
- Shell injection prevention
- URL validation with private IP blocking
- Request payload validation

### 16. Documentation

- `data_models.md`: Data structures and architecture
- `identity_config.md`: Identity provider setup guide
- `COMPREHENSIVE_REVIEW_AND_PLAN_2026-03-03.md`: Technical review and improvement plan

## Local Development

```bash
# Start all services
docker compose -f docker-compose.dev.yml up

# Services available:
# - Sandbox API:    http://localhost:8000 (docs: /docs)
# - Preview Router: http://localhost:8001
# - Snapshot API:   http://localhost:8002 (docs: /docs)
# - Agent API:      http://localhost:8003 (docs: /docs)
# - MinIO Console:  http://localhost:9001
# - Prometheus:     http://localhost:9090
```

## Setup

### Prerequisites

- Docker installed and running
- Python 3.11+
- bash shell
- zstd compression tool (or `pip install zstandard`)

### Installation

1. Install Python dependencies:

```bash
pip install -r requirements.txt
```

2. Configure identity provider:

   - Choose an IdP (Auth0, Clerk, Supabase, or Keycloak)
   - Update `PUBLIC_KEY` in `auth.py` with your IdP's public key

3. Create required directories:

```bash
sudo mkdir -p /srv/workspaces
sudo mkdir -p /srv/snapshots
```

### Running the APIs

Start the Sandbox API:

```bash
uvicorn sandbox_api:app --host 0.0.0.0 --port 8000
```

Start the Snapshot API:

```bash
uvicorn snapshot_api:app --host 0.0.0.0 --port 8002
```

Start the Agent Workspace API:

```bash
uvicorn agent_api:app --host 0.0.0.0 --port 8003
```

Start the Preview Router:

```bash
uvicorn preview_router:app --host 0.0.0.0 --port 8001
```

## API Documentation

All APIs serve interactive OpenAPI documentation:

- **Swagger UI**: `http://<host>:<port>/docs`
- **ReDoc**: `http://<host>:<port>/redoc`

## API Endpoints

### Sandbox API (`sandbox_api.py`)

| Method | Endpoint | Description |
| --- | --- | --- |
| `POST` | `/sandboxes` | Create a new sandbox |
| `POST` | `/sandboxes/{id}/exec` | Execute a command |
| `POST` | `/sandboxes/{id}/files` | Write a file |
| `GET` | `/sandboxes/{id}/files` | List directory |
| `GET` | `/sandboxes/{id}/files/{path}` | Read a file |
| `POST` | `/sandboxes/{id}/preview` | Register a preview URL |
| `POST` | `/sandboxes/{id}/keepalive` | Keep sandbox alive |
| `POST` | `/sandboxes/{id}/mount` | Mount a host path |
| `POST` | `/sandboxes/{id}/background` | Start a background job |
| `DELETE` | `/sandboxes/{id}/background/{job_id}` | Stop a background job |
| `WS` | `/sandboxes/{id}/terminal` | WebSocket terminal access |
| `GET` | `/health` | Health check |
| `GET` | `/health/ready` | Readiness check |
| `GET` | `/metrics` | Prometheus metrics |

### Snapshot API (`snapshot_api.py`)

| Method | Endpoint | Description |
| --- | --- | --- |
| `POST` | `/snapshot/create` | Create a snapshot |
| `POST` | `/snapshot/restore` | Restore a snapshot |
| `GET` | `/snapshot/list` | List user snapshots |
| `DELETE` | `/snapshot/{snapshot_id}` | Delete a snapshot |

### Agent Workspace API (`agent_api.py`)

| Method | Endpoint | Description |
| --- | --- | --- |
| `POST` | `/workspaces` | Create a workspace |
| `GET` | `/workspaces` | List owned workspaces |
| `GET` | `/workspaces/{id}` | Get workspace details |
| `DELETE` | `/workspaces/{id}` | Delete a workspace |
| `POST` | `/workspaces/{id}/exec` | Execute in workspace sandbox |
| `POST` | `/workspaces/{id}/share` | Share with other agents |
| `GET` | `/workspaces/{id}/collaborators` | List collaborators |
| `DELETE` | `/workspaces/{id}/share/{agent_id}` | Revoke agent access |
| `POST` | `/marketplace/publish` | Publish a worker |
| `GET` | `/marketplace/search` | Search marketplace |
| `GET` | `/marketplace/{worker_id}` | Get worker details |
| `GET` | `/health` | Health check |

### Preview Router (`preview_router.py`)

| Method | Endpoint | Description |
| --- | --- | --- |
| `POST` | `/preview/register` | Register a preview target |
| `GET` | `/preview/list` | List registered previews |
| `ALL` | `/preview/{sandbox_id}/{port}/{path}` | Proxy to preview target |

## Monitoring

All API services expose Prometheus-compatible metrics at `GET /metrics`. Available metrics include:

- `sandbox_created_total` — Total sandboxes created
- `sandbox_active` — Currently active sandboxes (gauge)
- `sandbox_exec_total` — Total command executions (by sandbox and command)
- `sandbox_exec_duration_seconds` — Execution duration histogram
- `snapshot_created_total` / `snapshot_restored_total` — Snapshot operations
- `snapshot_size_bytes` — Snapshot size distribution
- `http_requests_total` — HTTP requests by method, path, and status
- `http_request_duration_seconds` — Request latency histogram
- `quota_violations_total` — Quota violation counter by type

## Directory Structure

```
/srv/
├── workspaces/
│   └── {user_id}/          # User workspace files
│       ├── code/
│       ├── .config/
│       └── ...
└── snapshots/
    └── {user_id}/          # User snapshots
        ├── snap_001.tar.zst
        ├── snap_002.tar.zst
        └── ...
```

## Security

### Identity Security Rules

✔ One user → one workspace\
✔ Tokens required for all APIs\
✔ Containers never see auth tokens\
✔ LLM never sees identity secrets

This prevents privilege escalation.

### Snapshot Security

- Snapshots are namespaced by user_id
- No cross-user access possible
- Filesystem permissions enforced
- Path traversal protection in tar extraction
- Optional: Add per-snapshot encryption

## Snapshot Strategy

### What Gets Snapshotted

✅ Workspace filesystem\
✅ User files and code\
✅ Installed dependencies\
✅ Configuration files

❌ Container memory (not needed)\
❌ Kernel state

### Why This Works

Dev environments are:

- **File-driven**: Code, configs, git repos
- **Tool-driven**: Installed packages, CLIs
- **Not memory-driven**: State persists in files

### Automatic Snapshots

Configured to take snapshots:

- On idle suspend
- On explicit "Save" action
- Daily (optional)

Retention: Keep last 5 snapshots, delete older ones.

## Comparison with Other Platforms

| Platform | Snapshot Strategy |
| --- | --- |
| GitHub Codespaces | FS snapshot + image cache |
| Replit | Workspace snapshots |
| Fly.io | Volume snapshots |
| This Platform | FS archive (Zo-like) |

## Advanced Features (Future)

- 🔁 Live snapshotting (no container stop)
- 🧳 Cross-region restore
- 🧠 Agent memory on top of snapshots
- 🔒 Per-snapshot encryption
- 🧪 Snapshot diffing

## Storage Options

| Storage | Use Case |
| --- | --- |
| Local disk | Development, fast access |
| S3-compatible | Production, scalable |
| R2 / Backblaze | Cost-optimized |
