#!/bin/bash
#
# Snapshot Creation Script with Fallback
# Creates filesystem snapshot of user workspace
# Falls back to directory-based snapshots when Docker is unavailable
#

set -e

USER_ID="$1"
SNAPSHOT_ID="$2"

if [ -z "$USER_ID" ] || [ -z "$SNAPSHOT_ID" ]; then
    echo "Usage: $0 <user_id> <snapshot_id>"
    echo "Example: $0 u_123 snap_001"
    exit 1
fi

# Validate inputs to prevent path traversal
if [[ ! "$USER_ID" =~ ^[a-zA-Z0-9_-]+$ ]] || [[ ! "$SNAPSHOT_ID" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "Error: user_id and snapshot_id must contain only alphanumeric characters, underscores, and hyphens"
    exit 1
fi

# Check if Docker is available
if command -v docker &> /dev/null && docker version &> /dev/null; then
    USE_DOCKER=true
    echo "Using Docker for snapshot management"
else
    USE_DOCKER=false
    echo "Docker not available, using fallback directory-based snapshots"
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

    # Set up trap to ensure container is restarted even if script fails
    trap 'echo "Ensuring container is restarted..."; docker start "${CONTAINER_NAME}" 2>/dev/null || true' EXIT

    echo "Creating snapshot for user: ${USER_ID}"
    echo "Snapshot ID: ${SNAPSHOT_ID}"

    # Step 1 — Stop container (clean state)
    echo "Stopping container..."
    docker stop "${CONTAINER_NAME}" || true

    # Step 2 — Create snapshot directory if it doesn't exist
    mkdir -p "${SNAPSHOT_DIR}"

    # Step 3 — Verify workspace directory exists
    if [ ! -d "${WORKSPACE_DIR}" ]; then
        echo "Workspace not found: ${WORKSPACE_DIR}" >&2
        exit 1
    fi

    # Step 4 — Archive workspace
    echo "Archiving workspace..."
    tar --zstd -cf \
      "${SNAPSHOT_FILE}" \
      -C "${WORKSPACE_DIR}" .

    echo "Snapshot created successfully: ${SNAPSHOT_FILE}"
    echo "Size: $(du -h "${SNAPSHOT_FILE}" | cut -f1)"

    # Restart container (this will be handled by trap too)
    echo "Restarting container..."
    docker start "${CONTAINER_NAME}"

    echo "Done!"
else
    # Use fallback Python implementation
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PYTHON_FALLBACK="${SCRIPT_DIR}/container_fallback.py"
    
    if [ ! -f "$PYTHON_FALLBACK" ]; then
        echo "Error: Fallback script not found: $PYTHON_FALLBACK"
        exit 1
    fi
    
    echo "Creating snapshot using fallback method for user: ${USER_ID}"
    echo "Snapshot ID: ${SNAPSHOT_ID}"
    
    python3 "$PYTHON_FALLBACK" "snapshot" "$USER_ID" "$SNAPSHOT_ID"
fi