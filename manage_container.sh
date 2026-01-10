#!/bin/bash
#
# Container Management Script
# Manages user containers for the cloud terminal platform
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

WORKSPACE_DIR="/srv/workspaces/${USER_ID}"
CONTAINER_NAME="shell-${USER_ID}"
CONTAINER_IMAGE="${CONTAINER_IMAGE:-ubuntu:22.04}"

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
        docker ps -a --filter "name=${CONTAINER_NAME}" --format "table {{.Names}}\t{{.Status}}\t{{.Image}}"
        ;;
        
    *)
        echo "Error: Unknown action '${ACTION}'"
        exit 1
        ;;
esac
