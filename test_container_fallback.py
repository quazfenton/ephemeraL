"""Comprehensive tests for container_fallback.py module."""

import os
import sys
import tempfile
import shutil
from pathlib import Path
from unittest import mock
import pytest

from container_fallback import ContainerFallback, detect_docker_availability


class TestContainerFallback:
    """Test suite for ContainerFallback class."""

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary directories for testing."""
        workspace_dir = tempfile.mkdtemp()
        snapshot_dir = tempfile.mkdtemp()
        yield workspace_dir, snapshot_dir
        # Cleanup
        shutil.rmtree(workspace_dir, ignore_errors=True)
        shutil.rmtree(snapshot_dir, ignore_errors=True)

    @pytest.fixture
    def container_fallback(self, temp_dirs):
        """Create a ContainerFallback instance with temp directories."""
        workspace_dir, snapshot_dir = temp_dirs
        return ContainerFallback(
            base_workspace_dir=workspace_dir,
            base_snapshot_dir=snapshot_dir
        )

    def test_initialization(self, temp_dirs):
        """Test ContainerFallback initialization."""
        workspace_dir, snapshot_dir = temp_dirs
        cf = ContainerFallback(
            base_workspace_dir=workspace_dir,
            base_snapshot_dir=snapshot_dir
        )
        assert cf.base_workspace_dir == Path(workspace_dir)
        assert cf.base_snapshot_dir == Path(snapshot_dir)
        assert cf.base_workspace_dir.exists()
        assert cf.base_snapshot_dir.exists()

    def test_validate_user_id_valid(self, container_fallback):
        """Test user ID validation with valid IDs."""
        valid_ids = [
            "u_123",
            "user-456",
            "test_user_789",
            "abc123",
            "A1B2C3",
            "user-name-123"
        ]
        for user_id in valid_ids:
            assert container_fallback._validate_user_id(user_id) is True

    def test_validate_user_id_invalid(self, container_fallback):
        """Test user ID validation with invalid IDs."""
        invalid_ids = [
            "../malicious",
            "user/path",
            "user;rm -rf",
            "user`whoami`",
            "user$(ls)",
            "user@host",
            "user#comment",
            "user|pipe",
            ""
        ]
        for user_id in invalid_ids:
            assert container_fallback._validate_user_id(user_id) is False

    def test_get_workspace_path_valid(self, container_fallback):
        """Test getting workspace path with valid user ID."""
        user_id = "u_123"
        workspace_path = container_fallback._get_workspace_path(user_id)
        assert isinstance(workspace_path, Path)
        assert workspace_path.name == user_id

    def test_get_workspace_path_invalid(self, container_fallback):
        """Test getting workspace path with invalid user ID."""
        with pytest.raises(ValueError, match="Invalid user_id format"):
            container_fallback._get_workspace_path("../malicious")

    def test_get_snapshot_path_valid(self, container_fallback):
        """Test getting snapshot path with valid IDs."""
        user_id = "u_123"
        snapshot_id = "snap_001"
        snapshot_path = container_fallback._get_snapshot_path(user_id, snapshot_id)
        assert isinstance(snapshot_path, Path)
        assert snapshot_path.name == f"{snapshot_id}.tar.zst"
        assert snapshot_path.parent.name == user_id

    def test_get_snapshot_path_invalid(self, container_fallback):
        """Test getting snapshot path with invalid IDs."""
        with pytest.raises(ValueError, match="Invalid user_id or snapshot_id format"):
            container_fallback._get_snapshot_path("../malicious", "snap_001")
        with pytest.raises(ValueError, match="Invalid user_id or snapshot_id format"):
            container_fallback._get_snapshot_path("u_123", "../malicious")

    def test_create_container_success(self, container_fallback):
        """Test successful container creation."""
        user_id = "u_123"
        result = container_fallback.create_container(user_id)
        assert result is True

        workspace_path = container_fallback._get_workspace_path(user_id)
        assert workspace_path.exists()
        assert (workspace_path / "code").exists()
        assert (workspace_path / ".config").exists()
        assert (workspace_path / ".cache").exists()
        assert (workspace_path / ".container_running").exists()

    def test_create_container_idempotent(self, container_fallback):
        """Test creating container multiple times is idempotent."""
        user_id = "u_456"
        assert container_fallback.create_container(user_id) is True
        assert container_fallback.create_container(user_id) is True

        workspace_path = container_fallback._get_workspace_path(user_id)
        assert workspace_path.exists()

    def test_start_container_success(self, container_fallback):
        """Test successful container start."""
        user_id = "u_789"
        container_fallback.create_container(user_id)

        # Stop it first
        container_fallback.stop_container(user_id)

        # Now start it
        result = container_fallback.start_container(user_id)
        assert result is True

        workspace_path = container_fallback._get_workspace_path(user_id)
        assert (workspace_path / ".container_running").exists()

    def test_start_container_nonexistent(self, container_fallback):
        """Test starting a non-existent container."""
        user_id = "u_nonexistent"
        result = container_fallback.start_container(user_id)
        assert result is False

    def test_stop_container_success(self, container_fallback):
        """Test successful container stop."""
        user_id = "u_stop_test"
        container_fallback.create_container(user_id)

        result = container_fallback.stop_container(user_id)
        assert result is True

        workspace_path = container_fallback._get_workspace_path(user_id)
        assert not (workspace_path / ".container_running").exists()

    def test_stop_container_nonexistent(self, container_fallback):
        """Test stopping a non-existent container."""
        user_id = "u_nonexistent"
        result = container_fallback.stop_container(user_id)
        assert result is False

    def test_restart_container_success(self, container_fallback):
        """Test successful container restart."""
        user_id = "u_restart"
        container_fallback.create_container(user_id)

        result = container_fallback.restart_container(user_id)
        assert result is True

        workspace_path = container_fallback._get_workspace_path(user_id)
        assert (workspace_path / ".container_running").exists()

    def test_remove_container_success(self, container_fallback):
        """Test successful container removal."""
        user_id = "u_remove"
        container_fallback.create_container(user_id)

        result = container_fallback.remove_container(user_id)
        assert result is True

        workspace_path = container_fallback._get_workspace_path(user_id)
        assert not workspace_path.exists()

    def test_remove_container_nonexistent(self, container_fallback):
        """Test removing a non-existent container."""
        user_id = "u_nonexistent"
        result = container_fallback.remove_container(user_id)
        assert result is True  # Should succeed even if doesn't exist

    def test_container_status_not_found(self, container_fallback):
        """Test status check for non-existent container."""
        user_id = "u_not_found"
        status = container_fallback.container_status(user_id)
        assert status == "not_found"

    def test_container_status_running(self, container_fallback):
        """Test status check for running container."""
        user_id = "u_running"
        container_fallback.create_container(user_id)

        status = container_fallback.container_status(user_id)
        assert status == "running"

    def test_container_status_stopped(self, container_fallback):
        """Test status check for stopped container."""
        user_id = "u_stopped"
        container_fallback.create_container(user_id)
        container_fallback.stop_container(user_id)

        status = container_fallback.container_status(user_id)
        assert status == "stopped"

    def test_create_snapshot_success(self, container_fallback):
        """Test successful snapshot creation."""
        user_id = "u_snap"
        snapshot_id = "snap_test_001"

        # Create container and add some files
        container_fallback.create_container(user_id)
        workspace_path = container_fallback._get_workspace_path(user_id)
        (workspace_path / "code" / "test.txt").write_text("test content")

        result = container_fallback.create_snapshot(user_id, snapshot_id)
        assert result is True

        snapshot_path = container_fallback._get_snapshot_path(user_id, snapshot_id)
        assert snapshot_path.exists()
        assert snapshot_path.stat().st_size > 0

    def test_create_snapshot_stops_and_restarts_container(self, container_fallback):
        """Test that snapshot creation stops and restarts container."""
        user_id = "u_snap_restart"
        snapshot_id = "snap_restart_001"

        container_fallback.create_container(user_id)
        assert container_fallback.container_status(user_id) == "running"

        container_fallback.create_snapshot(user_id, snapshot_id)

        # Container should be running again after snapshot
        assert container_fallback.container_status(user_id) == "running"

    def test_create_snapshot_nonexistent_workspace(self, container_fallback):
        """Test snapshot creation with non-existent workspace."""
        user_id = "u_nonexistent"
        snapshot_id = "snap_fail"

        result = container_fallback.create_snapshot(user_id, snapshot_id)
        assert result is False

    def test_restore_snapshot_success(self, container_fallback):
        """Test successful snapshot restoration."""
        user_id = "u_restore"
        snapshot_id = "snap_restore_001"

        # Create container, add file, and create snapshot
        container_fallback.create_container(user_id)
        workspace_path = container_fallback._get_workspace_path(user_id)
        test_file = workspace_path / "code" / "restore_test.txt"
        test_file.write_text("restore test content")

        container_fallback.create_snapshot(user_id, snapshot_id)

        # Remove file and restore snapshot
        test_file.unlink()
        assert not test_file.exists()

        result = container_fallback.restore_snapshot(user_id, snapshot_id)
        assert result is True

        # File should be restored
        assert test_file.exists()
        assert test_file.read_text() == "restore test content"

    def test_restore_snapshot_nonexistent_snapshot(self, container_fallback):
        """Test restoration with non-existent snapshot."""
        user_id = "u_restore_fail"
        snapshot_id = "snap_nonexistent"

        result = container_fallback.restore_snapshot(user_id, snapshot_id)
        assert result is False

    def test_restore_snapshot_stops_and_restarts_container(self, container_fallback):
        """Test that snapshot restoration stops and restarts container."""
        user_id = "u_restore_restart"
        snapshot_id = "snap_restore_restart"

        container_fallback.create_container(user_id)
        container_fallback.create_snapshot(user_id, snapshot_id)

        assert container_fallback.container_status(user_id) == "running"

        container_fallback.restore_snapshot(user_id, snapshot_id)

        # Container should be running again after restore
        assert container_fallback.container_status(user_id) == "running"

    def test_list_snapshots_empty(self, container_fallback):
        """Test listing snapshots when none exist."""
        user_id = "u_no_snaps"
        snapshots = container_fallback.list_snapshots(user_id)
        assert snapshots == []

    def test_list_snapshots_success(self, container_fallback):
        """Test listing snapshots."""
        user_id = "u_list_snaps"
        snapshot_ids = ["snap_001", "snap_002", "snap_003"]

        container_fallback.create_container(user_id)

        for snapshot_id in snapshot_ids:
            container_fallback.create_snapshot(user_id, snapshot_id)

        snapshots = container_fallback.list_snapshots(user_id)
        assert len(snapshots) == 3

        # Check snapshot structure
        for snapshot in snapshots:
            assert "snapshot_id" in snapshot
            assert "size" in snapshot
            assert "path" in snapshot
            # snapshot_id is without .zst but includes .tar
            assert any(snapshot["snapshot_id"].startswith(sid) for sid in snapshot_ids)
            assert snapshot["size"] > 0

    def test_list_snapshots_sorted_by_modification_time(self, container_fallback):
        """Test that snapshots are sorted by modification time."""
        user_id = "u_sorted_snaps"

        container_fallback.create_container(user_id)

        # Create snapshots with slight delays
        import time
        container_fallback.create_snapshot(user_id, "snap_old")
        time.sleep(0.1)
        container_fallback.create_snapshot(user_id, "snap_new")

        snapshots = container_fallback.list_snapshots(user_id)
        assert len(snapshots) == 2
        # Newest should be first (snapshot_id includes .tar but not .zst)
        assert snapshots[0]["snapshot_id"].startswith("snap_new")
        assert snapshots[1]["snapshot_id"].startswith("snap_old")


class TestDetectDockerAvailability:
    """Test suite for Docker availability detection."""

    @mock.patch('subprocess.run')
    def test_docker_available(self, mock_run):
        """Test Docker is detected as available."""
        mock_run.return_value = mock.Mock(returncode=0)
        assert detect_docker_availability() is True
        mock_run.assert_called_once()

    @mock.patch('subprocess.run')
    def test_docker_not_available_command_error(self, mock_run):
        """Test Docker is detected as unavailable when command fails."""
        mock_run.side_effect = FileNotFoundError()
        assert detect_docker_availability() is False

    @mock.patch('subprocess.run')
    def test_docker_not_available_process_error(self, mock_run):
        """Test Docker is detected as unavailable when process errors."""
        import subprocess
        mock_run.side_effect = subprocess.CalledProcessError(1, 'docker')
        assert detect_docker_availability() is False


class TestMainFunction:
    """Test suite for main CLI function."""

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary directories for testing."""
        workspace_dir = tempfile.mkdtemp()
        snapshot_dir = tempfile.mkdtemp()
        yield workspace_dir, snapshot_dir
        shutil.rmtree(workspace_dir, ignore_errors=True)
        shutil.rmtree(snapshot_dir, ignore_errors=True)

    def test_main_no_args(self, capsys):
        """Test main function with no arguments."""
        from container_fallback import main

        # Mock sys.argv to have insufficient arguments
        with mock.patch('sys.argv', ['container_fallback.py']):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

            captured = capsys.readouterr()
            assert "Usage:" in captured.out

    def test_main_invalid_user_id(self, capsys):
        """Test main function with invalid user ID."""
        from container_fallback import main

        with mock.patch('sys.argv', ['container_fallback.py', 'create', '../malicious']):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

            captured = capsys.readouterr()
            assert "Invalid user_id format" in captured.out

    def test_main_unknown_action(self, capsys):
        """Test main function with unknown action."""
        from container_fallback import main

        with mock.patch('sys.argv', ['container_fallback.py', 'unknown', 'u_123']):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

            captured = capsys.readouterr()
            assert "Unknown action" in captured.out


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.fixture
    def container_fallback(self):
        """Create a ContainerFallback instance with temp directories."""
        workspace_dir = tempfile.mkdtemp()
        snapshot_dir = tempfile.mkdtemp()
        cf = ContainerFallback(
            base_workspace_dir=workspace_dir,
            base_snapshot_dir=snapshot_dir
        )
        yield cf
        shutil.rmtree(workspace_dir, ignore_errors=True)
        shutil.rmtree(snapshot_dir, ignore_errors=True)

    def test_path_traversal_prevention(self, container_fallback):
        """Test that path traversal attacks are prevented."""
        malicious_ids = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32",
            "user/../admin",
            "./../../sensitive"
        ]

        for malicious_id in malicious_ids:
            with pytest.raises(ValueError):
                container_fallback._get_workspace_path(malicious_id)

    def test_concurrent_operations(self, container_fallback):
        """Test handling of concurrent operations on same container."""
        user_id = "u_concurrent"

        # Create container
        container_fallback.create_container(user_id)

        # Multiple status checks should work
        assert container_fallback.container_status(user_id) == "running"
        assert container_fallback.container_status(user_id) == "running"

        # Stop and start multiple times
        container_fallback.stop_container(user_id)
        container_fallback.start_container(user_id)
        container_fallback.stop_container(user_id)

        assert container_fallback.container_status(user_id) == "stopped"

    def test_special_characters_in_files(self, container_fallback):
        """Test handling files with special characters in names."""
        user_id = "u_special_chars"
        snapshot_id = "snap_special"

        container_fallback.create_container(user_id)
        workspace_path = container_fallback._get_workspace_path(user_id)

        # Create files with various special characters
        special_files = [
            "file with spaces.txt",
            "file-with-dashes.txt",
            "file_with_underscores.txt",
            "file.multiple.dots.txt"
        ]

        for filename in special_files:
            (workspace_path / "code" / filename).write_text("content")

        # Should be able to create snapshot
        assert container_fallback.create_snapshot(user_id, snapshot_id) is True

        # And restore it
        assert container_fallback.restore_snapshot(user_id, snapshot_id) is True

        # All files should still exist
        for filename in special_files:
            assert (workspace_path / "code" / filename).exists()

    def test_large_workspace_snapshot(self, container_fallback):
        """Test creating snapshot of workspace with many files."""
        user_id = "u_large_workspace"
        snapshot_id = "snap_large"

        container_fallback.create_container(user_id)
        workspace_path = container_fallback._get_workspace_path(user_id)

        # Create many small files
        for i in range(100):
            (workspace_path / "code" / f"file_{i}.txt").write_text(f"content {i}")

        # Should successfully create snapshot
        assert container_fallback.create_snapshot(user_id, snapshot_id) is True

        snapshot_path = container_fallback._get_snapshot_path(user_id, snapshot_id)
        assert snapshot_path.exists()
        assert snapshot_path.stat().st_size > 0

    def test_empty_workspace_snapshot(self, container_fallback):
        """Test creating snapshot of empty workspace."""
        user_id = "u_empty"
        snapshot_id = "snap_empty"

        container_fallback.create_container(user_id)

        # Don't add any files, just create snapshot
        assert container_fallback.create_snapshot(user_id, snapshot_id) is True

        snapshot_path = container_fallback._get_snapshot_path(user_id, snapshot_id)
        assert snapshot_path.exists()