#!/bin/bash
# Test script to verify fallback functionality

set -euo pipefail  # Exit on error, undefined vars, and pipe failures

echo "Testing fallback container management..."

# Get script directory for relative paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Test the fallback by temporarily masking the docker command
# We'll create a temporary directory and add it to PATH
TEST_DIR=$(mktemp -d)
OLD_PATH="$PATH"

# Cleanup function
cleanup() {
    echo "Cleaning up..."
    export PATH="$OLD_PATH"
    rm -rf "$TEST_DIR"
}
trap cleanup EXIT INT TERM

# Create a fake docker command that always fails
echo '#!/bin/bash' > "$TEST_DIR/docker"
echo 'echo "Docker not available" >&2' >> "$TEST_DIR/docker"
echo 'exit 1' >> "$TEST_DIR/docker"
chmod +x "$TEST_DIR/docker"

# Update PATH to use our fake docker
export PATH="$TEST_DIR:$PATH"

echo "Running with simulated Docker-unavailable environment..."

echo "Testing container creation..."
if "$SCRIPT_DIR/manage_container.sh" create test_user_123; then
    echo "✓ Container creation succeeded"
else
    echo "✗ Container creation failed"
    exit 1
fi

echo "Testing container status..."
STATUS=$("$SCRIPT_DIR/manage_container.sh" status test_user_123 2>&1)
if echo "$STATUS" | grep -q "running"; then
    echo "✓ Container status check succeeded - container is running"
else
    echo "✗ Container status check failed - expected 'running', got: $STATUS"
    exit 1
fi

echo "Testing snapshot creation..."
if "$SCRIPT_DIR/create_snapshot.sh" test_user_123 test_snapshot_001; then
    echo "✓ Snapshot creation succeeded"
else
    echo "✗ Snapshot creation failed"
    exit 1
fi

echo "Testing snapshot restoration..."
if "$SCRIPT_DIR/restore_snapshot.sh" test_user_123 test_snapshot_001; then
    echo "✓ Snapshot restoration succeeded"
else
    echo "✗ Snapshot restoration failed"
    exit 1
fi

echo "Testing container stop..."
if "$SCRIPT_DIR/manage_container.sh" stop test_user_123; then
    echo "✓ Container stop succeeded"
else
    echo "✗ Container stop failed"
    exit 1
fi

echo "Testing container start..."
if "$SCRIPT_DIR/manage_container.sh" start test_user_123; then
    echo "✓ Container start succeeded"
else
    echo "✗ Container start failed"
    exit 1
fi

echo "Testing container removal..."
if "$SCRIPT_DIR/manage_container.sh" remove test_user_123; then
    echo "✓ Container removal succeeded"
else
    echo "✗ Container removal failed"
    exit 1
fi

echo "All tests completed successfully!"