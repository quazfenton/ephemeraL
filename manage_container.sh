#!/bin/bash
#
# Container Management Script with Fallback
# Manages user containers for the cloud terminal platform
# Falls back to directory-based isolation when Docker is unavailable
#

set -e

ACTION="$1"
USER_ID="$2"

if [ -z "$ACTION" ] || [ -z "$USER_ID" ]; then
    echo "Usage: $0 <action> <user_id>"
    echo ""
    echo "Actions:"
    echo "  create   - Create a new container for user"
    echo "  start    - Start user's container"
    echo "  stop     - Stop user's container"
    echo "  restart  - Restart user's container"
    echo "  remove   - Remove user's container"
    echo "  status   - Check container status"
    echo ""
    echo "Example: $0 create u_123"
    exit 1
fi

# Validate USER_ID format (alphanumeric, underscore, hyphen only)
if ! [[ "$USER_ID" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "Error: Invalid user_id format. Only alphanumeric characters, underscores, and hyphens allowed."
    exit 1
fi

# Check if Docker is available
if command -v docker &> /dev/null && docker version &> /dev/null; then
    USE_DOCKER=true
    echo "Using Docker for container management"
else
    USE_DOCKER=false
    echo "Docker not available, using fallback directory-based isolation"
fi

# Determine workspace and snapshot directories based on environment
if [ "$USE_DOCKER" = true ]; then
    WORKSPACE_DIR="/srv/workspaces/${USER_ID}"
    CONTAINER_NAME="shell-${USER_ID}"
    CONTAINER_IMAGE="${CONTAINER_IMAGE:-ubuntu:22.04}"
    
    # Ensure parent directories exist with proper permissions
    mkdir -p "/srv/workspaces" "/srv/snapshots"
    chmod 700 "/srv/workspaces" "/srv/snapshots"
    
    case "$ACTION" in
        create)
            echo "Creating container for user: ${USER_ID}"

            # Create workspace directory
            mkdir -p "${WORKSPACE_DIR}"

            # Create container with workspace mounted
            docker run -d \
                --name "${CONTAINER_NAME}" \
                --hostname "cloud-terminal" \
                -v "${WORKSPACE_DIR}:/workspace" \
                -w /workspace \
                --restart unless-stopped \
                "${CONTAINER_IMAGE}" \
                sleep infinity

            echo "Container created: ${CONTAINER_NAME}"
            ;;

        start)
            echo "Starting container: ${CONTAINER_NAME}"
            docker start "${CONTAINER_NAME}"
            echo "Container started"
            ;;

        stop)
            echo "Stopping container: ${CONTAINER_NAME}"
            docker stop "${CONTAINER_NAME}"
            echo "Container stopped"
            ;;

        restart)
            echo "Restarting container: ${CONTAINER_NAME}"
            docker restart "${CONTAINER_NAME}"
            echo "Container restarted"
            ;;

        remove)
            echo "Removing container: ${CONTAINER_NAME}"
            docker stop "${CONTAINER_NAME}" || true
            docker rm "${CONTAINER_NAME}"
            echo "Container removed"
            echo "Note: Workspace directory preserved at ${WORKSPACE_DIR}"
            ;;

        status)
            echo "Container status for: ${CONTAINER_NAME}"
            docker ps -a --filter "name=^${CONTAINER_NAME}$" --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"
            ;;

        *)
            echo "Error: Unknown action '${ACTION}'"
            exit 1
            ;;
    esac
else
    # Use fallback Python implementation
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PYTHON_FALLBACK="${SCRIPT_DIR}/container_fallback.py"
    
    if [ ! -f "$PYTHON_FALLBACK" ]; then
        echo "Error: Fallback script not found: $PYTHON_FALLBACK"
        exit 1
    fi
    
    echo "Executing fallback action: $ACTION for user: $USER_ID"
    python3 "$PYTHON_FALLBACK" "$ACTION" "$USER_ID"
fi