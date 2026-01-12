#!/bin/bash
#
# Snapshot Restore Script
# Restores user workspace from snapshot
#

set -e

USER_ID="$1"
SNAPSHOT_ID="$2"

# Validate input format (alphanumeric, underscores, hyphens only)
if [[ ! "$USER_ID" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "Error: Invalid USER_ID format. Only alphanumeric, underscore, and hyphen allowed."
    exit 1
fi
if [[ ! "$SNAPSHOT_ID" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "Error: Invalid SNAPSHOT_ID format. Only alphanumeric, underscore, and hyphen allowed."
    exit 1
fi

if [ -z "$USER_ID" ] || [ -z "$SNAPSHOT_ID" ]; then
    echo "Usage: $0 <user_id> <snapshot_id>"
    echo "Example: $0 u_123 snap_001"
    exit 1
fi

WORKSPACE_DIR="/srv/workspaces/${USER_ID}"
SNAPSHOT_DIR="/srv/snapshots/${USER_ID}"
SNAPSHOT_FILE="${SNAPSHOT_DIR}/${SNAPSHOT_ID}.tar.zst"
CONTAINER_NAME="shell-${USER_ID}"

if [ ! -f "${SNAPSHOT_FILE}" ]; then
    echo "Error: Snapshot file not found: ${SNAPSHOT_FILE}"
    exit 1
fi

echo "Restoring snapshot for user: ${USER_ID}"
echo "Snapshot ID: ${SNAPSHOT_ID}"

# Step 1 — Stop container
echo "Stopping container..."
docker stop "${CONTAINER_NAME}" || true

# Step 2 — Clear workspace
echo "Clearing workspace..."
rm -rf "${WORKSPACE_DIR:?}"/*

# Step 3 — Extract snapshot
echo "Extracting snapshot..."
tar --zstd -xf "${SNAPSHOT_FILE}" \
  -C "${WORKSPACE_DIR}"

# Step 4 — Restart container
echo "Restarting container..."
docker start "${CONTAINER_NAME}"

echo "Snapshot restored successfully!"
echo "User can resume exactly where they left off."
