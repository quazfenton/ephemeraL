# Data Models and Architecture

## Identity Model

```
user_id
 ├─ auth method
 ├─ sessions
 ├─ workspace
 ├─ usage limits
 ├─ snapshots
```

Everything else depends on this stable user identity.

### Example User ID Format

```
u_auth0_abc123
```

## Identity Flow

```
Browser / Client
 ↓ login
Identity Provider
 ↓ JWT
Session API
 ↓ user_id
Spawner / Meter / Snapshot
```

## Snapshot Model

```
snapshot_id
 ├─ user_id
 ├─ filesystem archive
 ├─ created_at
 ├─ size
```

### Example Snapshot Filename

```
snap_2026_01_01_120000.tar.zst
```

## Directory Structure

```
/srv/snapshots/
 └─ u_123/
     ├─ snap_001.tar.zst
     ├─ snap_002.tar.zst
```

Identity namespaces everything. No cross-user leakage possible.

**Security Note**: Isolation depends on filesystem permissions. Ensure strict permissions on user directories (e.g., chmod 700 or equivalent), ensure snapshots inherit restrictive ownership, and verify that umask and backup/restore flows preserve those permissions.

## Platform Architecture

```
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

## Identity Security Rules

✔ One user → one workspace
✔ Tokens required for all APIs
✔ Containers never see auth tokens
✔ LLM never sees identity secrets

This prevents privilege escalation.

## Snapshot Strategy Comparison

| Platform | Snapshot Strategy |
|----------|-------------------|
| Codespaces | FS snapshot + image cache |
| Replit | Workspace snapshots |
| Fly.io | Volume snapshots |
| Zo-like | FS archive |

## Why Filesystem Snapshots Work

Dev environments are:
- **File-driven**: Code, configs, git repos
- **Tool-driven**: Installed packages, CLIs
- **Not memory-driven**: State persists in files

Tools like tmux, git, code, and configs all live in the filesystem. That's why snapshotting files is enough.

## Automatic Snapshots Configuration

Take snapshots:
- On idle suspend
- On explicit "Save"
- Daily (optional)

Retention policy:
- Keep last 5 snapshots
- Delete older ones

## Snapshot Storage Options

| Storage | Notes |
|---------|-------|
| Local disk | Fast, cheap |
| S3-compatible | Scalable |
| R2 / Backblaze | Cheap |

Snapshots are just files - store them anywhere.

## Production-Grade Features

At this point you have:

✅ Real identity
✅ Stateless control plane
✅ Portable user state
✅ Disaster recovery
✅ Migration-ready architecture

## Advanced Features (Optional)

- 🔁 Live snapshotting (no stop)
- 🧳 Cross-region restore
- 🧠 Agent memory on top of snapshots
- 🔒 Per-snapshot encryption
- 🧪 Snapshot diffing
