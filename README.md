# Cloud Terminal Platform

A production-grade cloud terminal platform similar to Zo.computer, featuring user identity management, workspace isolation, and snapshot/restore capabilities.

## Overview

This platform provides:

- **Real Identity**: JWT-based authentication with external IdP integration
- **Stateless Control Plane**: API-driven container and workspace management
- **Portable User State**: Filesystem-based snapshots for pause/resume
- **Disaster Recovery**: Snapshot backup and restoration
- **Migration-Ready Architecture**: Cross-region capable design

## Architecture

```markdown
Identity (JWT)
 ↓
Session API
 ↓
Workspace
 ↓
Container / microVM
 ↓
Snapshots
```

## Components

### 1. Authentication Module (`auth.py`)

- JWT token validation
- User ID extraction
- Workspace/container mapping

### 2. Snapshot Scripts

- `create_snapshot.sh`: Create filesystem snapshots
- `restore_snapshot.sh`: Restore from snapshots

### 3. Snapshot API (`snapshot_api.py`)

- REST API for snapshot operations
- Automatic snapshot management
- Snapshot listing and metadata

### 4. Documentation

- `data_models.md`: Data structures and architecture
- `identity_config.md`: Identity provider setup guide

## Setup

### Prerequisites

- Docker installed and running
- Python 3.11+
- bash shell
- zstd compression tool

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

4. Make scripts executable:

```bash
chmod +x create_snapshot.sh restore_snapshot.sh
```

### Running the API

Start the FastAPI server:

```bash
python snapshot_api.py
```

Or with uvicorn directly:

```bash
uvicorn snapshot_api:app --host 0.0.0.0 --port 8000
```

## API Endpoints

### Create Snapshot

```bash
POST /snapshot/create
Content-Type: application/json

{
  "user_id": "u_123"
}
```

### Restore Snapshot

```bash
POST /snapshot/restore
Content-Type: application/json

{
  "user_id": "u_123",
  "snapshot_id": "snap_001"
}
```

### List Snapshots

```bash
GET /snapshot/list/{user_id}
```

## Directory Structure

```markdown
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