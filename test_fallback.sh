#!/bin/bash
# Test script to verify fallback functionality

echo "Testing fallback container management..."

# Test the fallback by temporarily masking the docker command
# We'll create a temporary directory and add it to PATH
TEST_DIR=$(mktemp -d)
OLD_PATH=$PATH

# Create a fake docker command that always fails
echo '#!/bin/bash' > $TEST_DIR/docker
echo 'echo "Docker not available" >&2' >> $TEST_DIR/docker
echo 'exit 1' >> $TEST_DIR/docker
chmod +x $TEST_DIR/docker

# Update PATH to use our fake docker
export PATH="$TEST_DIR:$PATH"

echo "Running with simulated Docker-unavailable environment..."

echo "Testing container creation..."
./manage_container.sh create test_user_123

echo "Testing container status..."
./manage_container.sh status test_user_123

echo "Testing snapshot creation..."
./create_snapshot.sh test_user_123 test_snapshot_001

echo "Testing snapshot restoration..."
./restore_snapshot.sh test_user_123 test_snapshot_001

echo "Testing container stop..."
./manage_container.sh stop test_user_123

echo "Testing container start..."
./manage_container.sh start test_user_123

echo "Testing container removal..."
./manage_container.sh remove test_user_123

echo "Test completed!"

# Clean up
export PATH=$OLD_PATH
rm -rf $TEST_DIR