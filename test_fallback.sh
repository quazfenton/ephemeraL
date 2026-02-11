#!/bin/bash
# Test script to verify fallback functionality

set -e  # Exit on any error

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
trap cleanup EXIT

# Create a fake docker command that always fails
echo '#!/bin/bash' > "$TEST_DIR/docker"
echo 'echo "Docker not available" >&2' >> "$TEST_DIR/docker"
echo 'exit 1' >> "$TEST_DIR/docker"
chmod +x "$TEST_DIR/docker"

# Update PATH to use our fake docker
export PATH="$TEST_DIR:$PATH"

echo "Running with simulated Docker-unavailable environment..."

echo "Testing container creation..."
"$SCRIPT_DIR/manage_container.sh" create test_user_123

echo "Testing container status..."
"$SCRIPT_DIR/manage_container.sh" status test_user_123

echo "Testing snapshot creation..."
"$SCRIPT_DIR/create_snapshot.sh" test_user_123 test_snapshot_001

echo "Testing snapshot restoration..."
"$SCRIPT_DIR/restore_snapshot.sh" test_user_123 test_snapshot_001

echo "Testing container stop..."
"$SCRIPT_DIR/manage_container.sh" stop test_user_123

echo "Testing container start..."
"$SCRIPT_DIR/manage_container.sh" start test_user_123

echo "Testing container removal..."
"$SCRIPT_DIR/manage_container.sh" remove test_user_123

echo "All tests completed successfully!"