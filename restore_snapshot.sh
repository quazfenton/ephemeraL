#!/bin/bash
#
# Snapshot Restore Script with Fallback
# Restores user workspace from snapshot
# Falls back to directory-based restoration when Docker is unavailable
#

set -e

USER_ID="$1"
SNAPSHOT_ID="$2"

if [ -z "$USER_ID" ] || [ -z "$SNAPSHOT_ID" ]; then
    echo "Usage: $0 <user_id> <snapshot_id>"
    echo "Example: $0 u_123 snap_001"
    exit 1
fi

# Validate input format (alphanumeric, underscores, hyphens only)
if [[ ! "$USER_ID" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "Error: Invalid USER_ID format. Only alphanumeric, underscore, and hyphen allowed."
    exit 1
fi
if [[ ! "$SNAPSHOT_ID" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "Error: Invalid SNAPSHOT_ID format. Only alphanumeric, underscore, and hyphen allowed."
    exit 1
fi

# Check if Docker is available
if command -v docker &> /dev/null && docker version &> /dev/null; then
    USE_DOCKER=true
    echo "Using Docker for snapshot restoration"
else
    USE_DOCKER=false
    echo "Docker not available, using fallback directory-based restoration"
fi

if [ "$USE_DOCKER" = true ]; then
    # Original Docker-based implementation
    WORKSPACE_DIR="/srv/workspaces/${USER_ID}"
    SNAPSHOT_DIR="/srv/snapshots/${USER_ID}"
    SNAPSHOT_FILE="${SNAPSHOT_DIR}/${SNAPSHOT_ID}.tar.zst"
    CONTAINER_NAME="shell-${USER_ID}"

    # Ensure parent directories exist with proper permissions
    mkdir -p "/srv/workspaces" "/srv/snapshots"
    chmod 755 "/srv/workspaces" "/srv/snapshots"

    if [ ! -f "${SNAPSHOT_FILE}" ]; then
        echo "Error: Snapshot file not found: ${SNAPSHOT_FILE}"
        exit 1
    fi

    echo "Restoring snapshot for user: ${USER_ID}"
    echo "Snapshot ID: ${SNAPSHOT_ID}"

    # Step 1 — Stop container
    echo "Stopping container..."
    docker stop "${CONTAINER_NAME}" || true

    # Step 2 — Ensure workspace directory exists
    mkdir -p "${WORKSPACE_DIR}"

    # Step 3 — Clear workspace
    echo "Clearing workspace..."
    rm -rf "${WORKSPACE_DIR:?}"/*

    # Step 4 — Extract snapshot
    echo "Extracting snapshot..."
    tar --zstd -xf "${SNAPSHOT_FILE}" \
      -C "${WORKSPACE_DIR}"

    # Step 4 — Restart container
    echo "Restarting container..."
    docker start "${CONTAINER_NAME}"

    echo "Snapshot restored successfully!"
    echo "User can resume exactly where they left off."
else
    # Use fallback Python implementation
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PYTHON_FALLBACK="${SCRIPT_DIR}/container_fallback.py"
    
    if [ ! -f "$PYTHON_FALLBACK" ]; then
        echo "Error: Fallback script not found: $PYTHON_FALLBACK"
        exit 1
    fi
    
    echo "Restoring snapshot using fallback method for user: ${USER_ID}"
    echo "Snapshot ID: ${SNAPSHOT_ID}"
    
    python3 "$PYTHON_FALLBACK" "restore" "$USER_ID" "$SNAPSHOT_ID"
fi