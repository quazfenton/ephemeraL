#!/usr/bin/env python3
"""
Container Fallback Module
Provides fallback containerization using system processes and directories
when Docker is not available (e.g., in Modal environment)
"""

import os
import sys
import subprocess
import shutil
import signal
import time
from pathlib import Path
from typing import Optional
import tempfile
import threading
import json
import pwd


class ContainerFallback:
    """
    Fallback container implementation using system processes and directories
    when Docker is not available.
    """
    
    def __init__(self, base_workspace_dir: str = "/tmp/workspaces", 
                 base_snapshot_dir: str = "/tmp/snapshots"):
        self.base_workspace_dir = Path(base_workspace_dir)
        self.base_snapshot_dir = Path(base_snapshot_dir)
        
        # Ensure base directories exist
        self.base_workspace_dir.mkdir(parents=True, exist_ok=True)
        self.base_snapshot_dir.mkdir(parents=True, exist_ok=True)
        
        # Track running containers (process IDs)
        self.running_containers = {}
        
    def _validate_user_id(self, user_id: str) -> bool:
        """Validate user ID format to prevent path traversal"""
        import re
        return bool(re.match(r'^[a-zA-Z0-9_-]+$', user_id))
    
    def _get_workspace_path(self, user_id: str) -> Path:
        """Get workspace path for user"""
        if not self._validate_user_id(user_id):
            raise ValueError(f"Invalid user_id format: {user_id}")
        return self.base_workspace_dir / user_id
    
    def _get_snapshot_path(self, user_id: str, snapshot_id: str) -> Path:
        """Get snapshot path for user and snapshot ID"""
        if not self._validate_user_id(user_id) or not self._validate_user_id(snapshot_id):
            raise ValueError(f"Invalid user_id or snapshot_id format")
        return self.base_snapshot_dir / user_id / f"{snapshot_id}.tar.zst"
    
    def create_container(self, user_id: str, image: str = "ubuntu:22.04") -> bool:
        """Create a workspace directory for the user (fallback equivalent of container)"""
        try:
            workspace_path = self._get_workspace_path(user_id)
            workspace_path.mkdir(parents=True, exist_ok=True)
            
            # Create basic directory structure similar to a container
            (workspace_path / "code").mkdir(exist_ok=True)
            (workspace_path / ".config").mkdir(exist_ok=True)
            (workspace_path / ".cache").mkdir(exist_ok=True)
            
            # Create a marker file to indicate container is "running"
            (workspace_path / ".container_running").touch()
            
            print(f"Created workspace for user: {user_id}")
            print(f"Workspace path: {workspace_path}")
            
            return True
        except Exception as e:
            print(f"Error creating container for user {user_id}: {e}")
            return False
    
    def start_container(self, user_id: str) -> bool:
        """Start a "container" by ensuring workspace exists and is accessible"""
        try:
            workspace_path = self._get_workspace_path(user_id)
            if not workspace_path.exists():
                print(f"Workspace does not exist for user: {user_id}")
                return False
            
            # Touch the marker file to indicate it's running
            (workspace_path / ".container_running").touch()
            
            print(f"Started container for user: {user_id}")
            return True
        except Exception as e:
            print(f"Error starting container for user {user_id}: {e}")
            return False
    
    def stop_container(self, user_id: str) -> bool:
        """Stop a "container" by removing the running marker"""
        try:
            workspace_path = self._get_workspace_path(user_id)
            if not workspace_path.exists():
                print(f"Workspace does not exist for user: {user_id}")
                return False
            
            # Remove the marker file to indicate it's stopped
            marker_file = workspace_path / ".container_running"
            if marker_file.exists():
                marker_file.unlink()
            
            print(f"Stopped container for user: {user_id}")
            return True
        except Exception as e:
            print(f"Error stopping container for user {user_id}: {e}")
            return False
    
    def restart_container(self, user_id: str) -> bool:
        """Restart a "container" by stopping and starting"""
        return self.stop_container(user_id) and self.start_container(user_id)
    
    def remove_container(self, user_id: str) -> bool:
        """Remove a "container" (workspace directory)"""
        try:
            workspace_path = self._get_workspace_path(user_id)
            if workspace_path.exists():
                # Remove the entire workspace directory
                shutil.rmtree(workspace_path)
                print(f"Removed workspace for user: {user_id}")
            else:
                print(f"Workspace does not exist for user: {user_id}")
            
            return True
        except Exception as e:
            print(f"Error removing container for user {user_id}: {e}")
            return False
    
    def container_status(self, user_id: str) -> str:
        """Check status of a "container" (workspace)"""
        try:
            workspace_path = self._get_workspace_path(user_id)
            if not workspace_path.exists():
                return "not_found"
            
            marker_file = workspace_path / ".container_running"
            if marker_file.exists():
                return "running"
            else:
                return "stopped"
        except Exception as e:
            print(f"Error checking status for user {user_id}: {e}")
            return "error"
    
    def create_snapshot(self, user_id: str, snapshot_id: str) -> bool:
        """Create a snapshot of the user's workspace"""
        try:
            workspace_path = self._get_workspace_path(user_id)
            if not workspace_path.exists():
                print(f"Workspace does not exist for user: {user_id}")
                return False
            
            # Stop the "container" temporarily for clean snapshot
            was_running = self.container_status(user_id) == "running"
            if was_running:
                self.stop_container(user_id)
            
            # Create snapshot directory
            snapshot_dir = self.base_snapshot_dir / user_id
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            
            # Create snapshot file path
            snapshot_path = self._get_snapshot_path(user_id, snapshot_id)
            
            # Create tar.zst archive of workspace
            import tarfile
            import zstandard as zstd

            # Create compressed archive using zstandard
            cctx = zstd.ZstdCompressor()
            with open(snapshot_path, 'wb') as dst:
                with cctx.stream_writer(dst) as compressor:
                    with tarfile.open(fileobj=compressor, mode='w|') as tar:
                        tar.add(str(workspace_path), arcname=user_id.split('/')[-1])
            
            print(f"Created snapshot: {snapshot_path}")
            
            # Restart container if it was running
            if was_running:
                self.start_container(user_id)
            
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error creating snapshot: {e}")
            return False
        except Exception as e:
            print(f"Error creating snapshot for user {user_id}: {e}")
            return False
    
    def restore_snapshot(self, user_id: str, snapshot_id: str) -> bool:
        """Restore a workspace from a snapshot"""
        try:
            # Get snapshot path
            snapshot_path = self._get_snapshot_path(user_id, snapshot_id)
            if not snapshot_path.exists():
                print(f"Snapshot not found: {snapshot_path}")
                return False
            
            # Stop the "container" temporarily
            was_running = self.container_status(user_id) == "running"
            if was_running:
                self.stop_container(user_id)
            
            # Get workspace path
            workspace_path = self._get_workspace_path(user_id)
            
            # Remove existing workspace
            if workspace_path.exists():
                shutil.rmtree(workspace_path)
            
            # Create workspace directory
            workspace_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Extract snapshot
            import tarfile
            import zstandard as zstd

            # Extract compressed archive using zstandard
            dctx = zstd.ZstdDecompressor()
            with open(snapshot_path, 'rb') as src:
                with dctx.stream_reader(src) as decompressor:
                    with tarfile.open(fileobj=decompressor, mode='r|') as tar:
                        tar.extractall(path=str(workspace_path.parent))
            
            print(f"Restored snapshot: {snapshot_path}")
            
            # Restart container if it was running
            if was_running:
                self.start_container(user_id)
            
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error restoring snapshot: {e}")
            return False
        except Exception as e:
            print(f"Error restoring snapshot for user {user_id}: {e}")
            return False
    
    def list_snapshots(self, user_id: str) -> list:
        """List all snapshots for a user"""
        try:
            snapshot_dir = self.base_snapshot_dir / user_id
            if not snapshot_dir.exists():
                return []
            
            snapshots = []
            for file_path in snapshot_dir.glob("*.tar.zst"):
                snapshot_id = file_path.stem  # Remove .tar.zst extension
                size = file_path.stat().st_size
                snapshots.append({
                    "snapshot_id": snapshot_id,
                    "size": size,
                    "path": str(file_path)
                })
            
            # Sort by modification time, newest first
            snapshots.sort(key=lambda x: Path(x["path"]).stat().st_mtime, reverse=True)
            return snapshots
        except Exception as e:
            print(f"Error listing snapshots for user {user_id}: {e}")
            return []


def detect_docker_availability():
    """Check if Docker is available"""
    try:
        result = subprocess.run(["docker", "version"], 
                              stdout=subprocess.PIPE, 
                              stderr=subprocess.PIPE, 
                              check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def main():
    """Main entry point for the fallback container manager"""
    if len(sys.argv) < 3:
        print("Usage: container_fallback.py <action> <user_id> [additional_args]")
        print("")
        print("Actions:")
        print("  create     - Create a workspace for user")
        print("  start      - Start user's workspace")
        print("  stop       - Stop user's workspace")
        print("  restart    - Restart user's workspace")
        print("  remove     - Remove user's workspace")
        print("  status     - Check workspace status")
        print("  snapshot   - Create snapshot (requires snapshot_id)")
        print("  restore    - Restore from snapshot (requires snapshot_id)")
        print("")
        print("Example: container_fallback.py create u_123")
        sys.exit(1)
    
    action = sys.argv[1]
    user_id = sys.argv[2]
    
    # Initialize fallback container manager
    container_manager = ContainerFallback()
    
    # Validate user_id format
    if not container_manager._validate_user_id(user_id):
        print(f"Error: Invalid user_id format. Only alphanumeric characters, underscores, and hyphens allowed.")
        sys.exit(1)
    
    if action == "create":
        success = container_manager.create_container(user_id)
        sys.exit(0 if success else 1)
    
    elif action == "start":
        success = container_manager.start_container(user_id)
        sys.exit(0 if success else 1)
    
    elif action == "stop":
        success = container_manager.stop_container(user_id)
        sys.exit(0 if success else 1)
    
    elif action == "restart":
        success = container_manager.restart_container(user_id)
        sys.exit(0 if success else 1)
    
    elif action == "remove":
        success = container_manager.remove_container(user_id)
        sys.exit(0 if success else 1)
    
    elif action == "status":
        status = container_manager.container_status(user_id)
        print(f"Container status for {user_id}: {status}")
        sys.exit(0)
    
    elif action == "snapshot":
        if len(sys.argv) < 4:
            print("Usage: container_fallback.py snapshot <user_id> <snapshot_id>")
            sys.exit(1)
        snapshot_id = sys.argv[3]
        success = container_manager.create_snapshot(user_id, snapshot_id)
        sys.exit(0 if success else 1)
    
    elif action == "restore":
        if len(sys.argv) < 4:
            print("Usage: container_fallback.py restore <user_id> <snapshot_id>")
            sys.exit(1)
        snapshot_id = sys.argv[3]
        success = container_manager.restore_snapshot(user_id, snapshot_id)
        sys.exit(0 if success else 1)
    
    else:
        print(f"Error: Unknown action '{action}'")
        sys.exit(1)


if __name__ == "__main__":
    main()