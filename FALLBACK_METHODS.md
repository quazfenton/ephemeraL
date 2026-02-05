# Fallback Containerization Methods

This document describes the fallback mechanisms implemented for environments where Docker is not available, such as Modal environments.

## Problem Statement

The original cloud terminal platform relies on Docker for containerization, but in some environments like Modal, Docker may not be available or accessible. This creates a need for alternative methods to provide:

1. Workspace isolation
2. Snapshot/restore functionality
3. Container lifecycle management

## Solution Overview

Three fallback mechanisms have been implemented:

### 1. Python-Based Directory Isolation (Primary Fallback)

The `container_fallback.py` script provides a pure Python implementation that:

- Creates isolated workspace directories instead of containers
- Uses file system markers to track "container" state
- Implements snapshot functionality using tar.zst archives
- Maintains the same interface as the Docker-based system

### 2. Enhanced Shell Scripts with Auto-Detection

Updated scripts that automatically detect Docker availability:

- `manage_container.sh` - Container lifecycle management
- `create_snapshot.sh` - Snapshot creation
- `restore_snapshot.sh` - Snapshot restoration

These scripts check for Docker availability and fall back to the Python implementation when Docker is not available.

### 3. Service Mount Alternative (Advanced Option)

The `service_mount_alt.sh` script provides an alternative using bind mounts for stronger isolation when Docker is not available but system-level operations are permitted.

## How It Works

### Docker Detection Logic

Scripts use the following logic to determine which implementation to use:

```bash
if command -v docker &> /dev/null && docker version &> /dev/null; then
    USE_DOCKER=true
else
    USE_DOCKER=false
fi
```

### Directory-Based Isolation

When Docker is not available, the system:

1. Creates workspace directories in `/tmp/workspaces/{user_id}`
2. Uses `.container_running` marker files to track state
3. Stores snapshots in `/tmp/snapshots/{user_id}/`
4. Maintains the same API and interface as the Docker version

### Snapshot Process

The fallback snapshot process:

1. Temporarily stops the "container" (removes running marker)
2. Creates a tar.zst archive of the workspace
3. Restarts the "container" if it was previously running
4. Maintains the same file format as the Docker version

## Usage

The scripts work identically to the original versions:

```bash
# Container management
./manage_container.sh create u_123
./manage_container.sh start u_123
./manage_container.sh stop u_123
./manage_container.sh status u_123

# Snapshot operations
./create_snapshot.sh u_123 snap_001
./restore_snapshot.sh u_123 snap_001
```

The system automatically chooses the appropriate implementation based on Docker availability.

## Security Considerations

- Input validation remains the same as the original implementation
- Path traversal prevention is maintained
- User isolation is achieved through directory separation
- File permissions are properly managed

## Limitations

Compared to Docker-based isolation:

- Less secure process isolation
- No resource limits enforcement
- No network isolation
- Relies on file system permissions for isolation

However, for many use cases, especially in trusted environments like Modal, this provides sufficient isolation while maintaining functionality.

## Integration with Existing Systems

The fallback mechanisms maintain compatibility with:

- The existing FastAPI snapshot API
- Authentication and user ID validation
- The same directory structure expectations
- The same snapshot file format