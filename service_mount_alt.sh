#!/bin/bash
#
# Service Mount Alternative Script
# Provides workspace isolation using bind mounts when Docker is unavailable
#

set -e

ACTION="$1"
USER_ID="$2"

if [ -z "$ACTION" ] || [ -z "$USER_ID" ]; then
    echo "Usage: $0 <action> <user_id>"
    echo ""
    echo "Actions:"
    echo "  create   - Create a workspace for user with bind mount isolation"
    echo "  start    - Start user's workspace"
    echo "  stop     - Stop user's workspace"
    echo "  destroy  - Destroy user's workspace (unmount and remove)"
    echo ""
    echo "Example: $0 create u_123"
    exit 1
fi

# Validate USER_ID format (alphanumeric, underscore, hyphen, pipe allowed for IdP formats)
# Block dot-segments to prevent path traversal
if [[ "$USER_ID" =~ \.\. ]] || [[ "$USER_ID" =~ ^\.\.$ ]] || [[ "$USER_ID" =~ ^\.$ ]]; then
    echo "Error: Invalid user_id format. Dot-segments ('..' or '.') not allowed to prevent path traversal."
    exit 1
elif ! [[ "$USER_ID" =~ ^[a-zA-Z0-9_\-\|]+$ ]]; then
    echo "Error: Invalid user_id format. Only alphanumeric characters, underscores, hyphens, and pipes allowed."
    exit 1
fi

# Base directories
BASE_WORKSPACES="/srv/workspaces"
BASE_SNAPSHOTS="/srv/snapshots"
USER_WORKSPACE="${BASE_WORKSPACES}/${USER_ID}"
TEMP_WORKSPACE="/tmp/workspaces/${USER_ID}"

# Ensure base directories exist
mkdir -p "$BASE_WORKSPACES" "$BASE_SNAPSHOTS" "/tmp/workspaces"
chmod 755 "$BASE_WORKSPACES" "$BASE_SNAPSHOTS" "/tmp/workspaces"

case "$ACTION" in
    create)
        echo "Creating workspace for user: ${USER_ID}"
        
        # Create user workspace directory
        mkdir -p "$USER_WORKSPACE"
        
        # Create temporary workspace directory
        mkdir -p "$TEMP_WORKSPACE"
        
        # Set up basic directory structure
        mkdir -p "$TEMP_WORKSPACE/code" "$TEMP_WORKSPACE/.config" "$TEMP_WORKSPACE/.cache"
        
        # Create a marker file to indicate workspace is active
        touch "$TEMP_WORKSPACE/.workspace_active"
        
        # Bind mount the temporary workspace to the user workspace
        # This provides isolation similar to a container
        if ! mountpoint -q "$USER_WORKSPACE" 2>/dev/null; then
            sudo mount --bind "$TEMP_WORKSPACE" "$USER_WORKSPACE"
        fi
        
        echo "Workspace created and mounted for user: ${USER_ID}"
        echo "Workspace path: $USER_WORKSPACE"
        ;;
    
    start)
        echo "Starting workspace for user: ${USER_ID}"
        
        # Check if workspace exists
        if [ ! -d "$USER_WORKSPACE" ]; then
            echo "Error: Workspace does not exist for user: ${USER_ID}"
            exit 1
        fi
        
        # Ensure the bind mount is active
        if ! mountpoint -q "$USER_WORKSPACE" 2>/dev/null; then
            if [ -d "$TEMP_WORKSPACE" ]; then
                sudo mount --bind "$TEMP_WORKSPACE" "$USER_WORKSPACE"
                echo "Workspace mounted for user: ${USER_ID}"
            else
                echo "Error: Temporary workspace directory missing for user: ${USER_ID}"
                exit 1
            fi
        else
            echo "Workspace already mounted for user: ${USER_ID}"
        fi
        ;;
    
    stop)
        echo "Stopping workspace for user: ${USER_ID}"
        
        # Unmount the bind mount if it exists
        if mountpoint -q "$USER_WORKSPACE" 2>/dev/null; then
            sudo umount "$USER_WORKSPACE"
            echo "Workspace unmounted for user: ${USER_ID}"
        else
            echo "Workspace not mounted for user: ${USER_ID}"
        fi
        
        # Remove the active marker
        if [ -f "$TEMP_WORKSPACE/.workspace_active" ]; then
            rm -f "$TEMP_WORKSPACE/.workspace_active"
        fi
        ;;
    
    destroy)
        echo "Destroying workspace for user: ${USER_ID}"
        
        # Unmount if mounted
        if mountpoint -q "$USER_WORKSPACE" 2>/dev/null; then
            sudo umount "$USER_WORKSPACE"
            echo "Workspace unmounted"
        fi
        
        # Remove temporary workspace directory
        if [ -d "$TEMP_WORKSPACE" ]; then
            rm -rf "$TEMP_WORKSPACE"
            echo "Temporary workspace removed"
        fi
        
        # Note: Don't remove the user workspace directory in /srv as it might contain persistent data
        echo "Workspace destroyed for user: ${USER_ID}"
        ;;
    
    *)
        echo "Error: Unknown action '${ACTION}'"
        exit 1
        ;;
esac