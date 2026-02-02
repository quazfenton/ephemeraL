#!/bin/bash
#
# Snapshot Creation Script
# Creates filesystem snapshot of user workspace
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

WORKSPACE_DIR="/srv/workspaces/${USER_ID}"
SNAPSHOT_DIR="/srv/snapshots/${USER_ID}"
SNAPSHOT_FILE="${SNAPSHOT_DIR}/${SNAPSHOT_ID}.tar.zst"
CONTAINER_NAME="shell-${USER_ID}"

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
