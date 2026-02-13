"""Comprehensive tests for sandbox_api.py module."""

import pytest
from unittest import mock
from fastapi.testclient import TestClient

from sandbox_api import app


class TestSandboxAPI:
    """Test suite for Sandbox API endpoints."""

    @pytest.fixture
    def client(self):
        """Create a test client."""
        return TestClient(app)

    @pytest.fixture
    def mock_manager(self):
        """Mock the SandboxManager."""
        with mock.patch('sandbox_api.manager') as mock_mgr:
            yield mock_mgr

    @pytest.fixture
    def mock_preview(self):
        """Mock the PreviewRegistrar."""
        @pytest.fixture
        def mock_preview(self):
            """Mock the PreviewRegistrar."""
            with mock.patch('sandbox_api.preview') as mock_prev:
                yield mock_prev

        @pytest.fixture
        def mock_backgrounds(self):
            """Mock the BackgroundExecutor."""
            with mock.patch('sandbox_api.backgrounds') as mock_bg:
                yield mock_bg

        def test_create_sandbox_success(self, client, mock_manager):
            """Test successful sandbox creation."""
            mock_sandbox = mock.Mock()
            mock_sandbox.sandbox_id = "sandbox123"
            mock_sandbox.workspace = "/tmp/workspaces/sandbox123"

            async def mock_create_sandbox(sandbox_id=None):
                return mock_sandbox

            mock_manager.create_sandbox = mock_create_sandbox

            response = client.post("/sandboxes", json={})
            assert response.status_code == 200
            assert response.json() == {
                "sandbox_id": "sandbox123",
                "workspace": "/tmp/workspaces/sandbox123"
            }

        def test_create_sandbox_with_id(self, client, mock_manager):
            """Test sandbox creation with specified ID."""
        mock_sandbox = mock.Mock()
        mock_sandbox.sandbox_id = "custom_sandbox_456"
        mock_sandbox.workspace = "/tmp/workspaces/custom_sandbox_456"

        async def mock_create_sandbox(sandbox_id=None):
            mock_sandbox.sandbox_id = sandbox_id
            return mock_sandbox

        mock_manager.create_sandbox = mock_create_sandbox

        response = client.post(
            "/sandboxes",
            json={"sandbox_id": "custom_sandbox_456"}
        )

    def test_exec_command_success(self, client, mock_manager):
        """Test successful command execution."""
        mock_result = {
            "stdout": "Hello, World!",
            "stderr": "",
            "exit_code": 0
        }

        async def mock_exec_command(*args, **kwargs):
            return mock_result

        mock_manager.exec_command = mock_exec_command

        response = client.post(
            "/sandboxes/sandbox123/exec",
            json={
                "command": "echo",
                "args": ["Hello, World!"]
            }
        )

    def test_exec_command_sandbox_not_found(self, client, mock_manager):
        """Test command execution on non-existent sandbox."""
        async def mock_exec_command(*args, **kwargs):
            raise KeyError("Sandbox not found")

        mock_manager.exec_command = mock_exec_command

        response = client.post(
            "/sandboxes/nonexistent/exec",
            json={
                "command": "ls"
            }
        )

    def test_exec_command_with_code(self, client, mock_manager):
        """Test command execution with inline code."""
        mock_result = {
            "stdout": "Test output",
            "stderr": "",
            "exit_code": 0
        }

        async def mock_exec_command(*args, **kwargs):
            return mock_result

        mock_manager.exec_command = mock_exec_command

        response = client.post(
            "/sandboxes/sandbox123/exec",
            json={
                "command": "python",
                "code": "print('Test output')",
                "timeout": 30,
                "requires_native": False
            }
        )

    def test_write_file_success(self, client, mock_manager):
        """Test successful file write."""
        mock_sandbox = mock.Mock()
        mock_sandbox.fs = mock.Mock()
        mock_sandbox.fs.write = mock.Mock()

        async def mock_get_sandbox(sandbox_id):
            return mock_sandbox

        mock_manager.get_sandbox = mock_get_sandbox

        response = client.post(
            "/sandboxes/sandbox123/files",
            json={
                "path": "/workspace/test.txt",
                "data": "Test content"
            }
        )

    def test_write_file_sandbox_not_found(self, client, mock_manager):
        """Test file write on non-existent sandbox."""
        async def mock_get_sandbox(sandbox_id):
            raise KeyError("Sandbox not found")

        mock_manager.get_sandbox = mock_get_sandbox

        response = client.post(
            "/sandboxes/nonexistent/files",
            json={
                "path": "/workspace/test.txt",
                "data": "Test content"
            }
        )

    def test_write_file_invalid_path(self, client, mock_manager):
        """Test file write with invalid path."""
        mock_sandbox = mock.Mock()
        mock_sandbox.fs = mock.Mock()
        mock_sandbox.fs.write = mock.Mock(side_effect=ValueError("Invalid path"))

        async def mock_get_sandbox(sandbox_id):
            return mock_sandbox

        mock_manager.get_sandbox = mock_get_sandbox

        response = client.post(
            "/sandboxes/sandbox123/files",
            json={
                "path": "/../etc/passwd",
                "data": "malicious"
            }
        )

    def test_list_files_success(self, client, mock_manager):
        """Test successful file listing."""
        mock_sandbox = mock.Mock()
        mock_sandbox.fs = mock.Mock()
        mock_sandbox.fs.list_dir = mock.Mock(return_value=[
            {"name": "file1.txt", "type": "file"},
            {"name": "dir1", "type": "directory"}
        ])

        async def mock_get_sandbox(sandbox_id):
            return mock_sandbox

        mock_manager.get_sandbox = mock_get_sandbox

        response = client.get("/sandboxes/sandbox123/files")

    def test_list_files_with_path(self, client, mock_manager):
        """Test file listing with specific path."""
        mock_sandbox = mock.Mock()
        mock_sandbox.fs = mock.Mock()
        mock_sandbox.fs.list_dir = mock.Mock(return_value=[])

        async def mock_get_sandbox(sandbox_id):
            return mock_sandbox

        mock_manager.get_sandbox = mock_get_sandbox

        response = client.get("/sandboxes/sandbox123/files?path=/workspace/subdir")

    def test_list_files_sandbox_not_found(self, client, mock_manager):
        """Test file listing on non-existent sandbox."""
        async def mock_get_sandbox(sandbox_id):
            raise KeyError("Sandbox not found")

        mock_manager.get_sandbox = mock_get_sandbox

        response = client.get("/sandboxes/nonexistent/files")

    def test_read_file_success(self, client, mock_manager):
        """Test successful file read."""
        mock_sandbox = mock.Mock()
        mock_sandbox.fs = mock.Mock()
        mock_sandbox.fs.read = mock.Mock(return_value=b"File content")

        async def mock_get_sandbox(sandbox_id):
            return mock_sandbox

        mock_manager.get_sandbox = mock_get_sandbox

        response = client.get("/sandboxes/sandbox123/files/test.txt")

    def test_read_file_not_found(self, client, mock_manager):
        """Test reading non-existent file."""
        mock_sandbox = mock.Mock()
        mock_sandbox.fs = mock.Mock()
        mock_sandbox.fs.read = mock.Mock(side_effect=FileNotFoundError())

        async def mock_get_sandbox(sandbox_id):
            return mock_sandbox

        mock_manager.get_sandbox = mock_get_sandbox

        response = client.get("/sandboxes/sandbox123/files/nonexistent.txt")

    def test_read_file_sandbox_not_found(self, client, mock_manager):
        """Test file read on non-existent sandbox."""
        async def mock_get_sandbox(sandbox_id):
            raise KeyError("Sandbox not found")

        mock_manager.get_sandbox = mock_get_sandbox

        response = client.get("/sandboxes/nonexistent/files/test.txt")

    def test_register_preview_success(self, client, mock_manager, mock_preview):
        """Test successful preview registration."""
        mock_sandbox = mock.Mock()

        async def mock_get_sandbox(sandbox_id):
            return mock_sandbox

        async def mock_register(sandbox_id, port, backend):
            return f"http://preview.example.com/{sandbox_id}/{port}"

        async def mock_register_preview(sandbox_id, port, url):
            pass

        mock_manager.get_sandbox = mock_get_sandbox
        mock_preview.register = mock_register
        mock_manager.register_preview = mock_register_preview

        response = client.post(
            "/sandboxes/sandbox123/preview",
            json={"port": 8080}
        )

    def test_register_preview_sandbox_not_found(self, client, mock_manager):
        """Test preview registration on non-existent sandbox."""
        async def mock_get_sandbox(sandbox_id):
            raise KeyError("Sandbox not found")

        mock_manager.get_sandbox = mock_get_sandbox

        response = client.post(
            "/sandboxes/nonexistent/preview",
            json={"port": 8080}
        )

    def test_keep_alive_success(self, client, mock_manager):
        """Test successful keepalive."""
        async def mock_keep_alive(sandbox_id):
            pass

        mock_manager.keep_alive = mock_keep_alive

        response = client.post("/sandboxes/sandbox123/keepalive")

    def test_keep_alive_sandbox_not_found(self, client, mock_manager):
        """Test keepalive on non-existent sandbox."""
        async def mock_keep_alive(sandbox_id):
            raise KeyError("Sandbox not found")

        mock_manager.keep_alive = mock_keep_alive

        response = client.post("/sandboxes/nonexistent/keepalive")

    def test_mount_path_success(self, client, mock_manager):
        """Test successful path mounting."""
        from pathlib import Path

        async def mock_mount(sandbox_id, alias, target):
            pass

        mock_manager.mount = mock_mount

        response = client.post(
            "/sandboxes/sandbox123/mount",
            json={
                "alias": "shared",
                "target": "/tmp/shared"
            }
        )

    def test_mount_path_sandbox_not_found(self, client, mock_manager):
        """Test mount on non-existent sandbox."""
        from pathlib import Path

        async def mock_mount(sandbox_id, alias, target):
            raise KeyError("Sandbox not found")

        mock_manager.mount = mock_mount

        response = client.post(
            "/sandboxes/nonexistent/mount",
            json={
                "alias": "shared",
                "target": "/tmp/shared"
            }
        )

    def test_mount_path_target_not_found(self, client, mock_manager):
        """Test mount with non-existent target."""
        from pathlib import Path

        async def mock_mount(sandbox_id, alias, target):
            raise FileNotFoundError("Mount target missing")

        mock_manager.mount = mock_mount

        response = client.post(
            "/sandboxes/sandbox123/mount",
            json={
                "alias": "shared",
                "target": "/nonexistent/path"
            }
        )

    def test_start_background_job_success(self, client, mock_backgrounds):
        """Test successful background job start."""
        mock_job = mock.Mock()
        mock_job.job_id = "job123"

        async def mock_start_job(*args, **kwargs):
            return mock_job

        mock_backgrounds.start_job = mock_start_job

        response = client.post(
            "/sandboxes/sandbox123/background",
            json={
                "command": "watch",
                "args": ["-n", "5", "ls"],
                "interval": 5
            }
        )

    def test_start_background_job_sandbox_not_found(self, client, mock_backgrounds):
        """Test background job start on non-existent sandbox."""
        async def mock_start_job(*args, **kwargs):
            raise KeyError("Sandbox not found")

        mock_backgrounds.start_job = mock_start_job

        response = client.post(
            "/sandboxes/nonexistent/background",
            json={
                "command": "ls",
                "interval": 5
            }
        )

    def test_stop_background_job_success(self, client, mock_backgrounds):
        """Test successful background job stop."""
        async def mock_stop_job(sandbox_id, job_id):
            return True

        mock_backgrounds.stop_job = mock_stop_job

        response = client.delete("/sandboxes/sandbox123/background/job123")

    def test_stop_background_job_not_found(self, client, mock_backgrounds):
        """Test stopping non-existent background job."""
        async def mock_stop_job(sandbox_id, job_id):
            return False

        mock_backgrounds.stop_job = mock_stop_job

        response = client.delete("/sandboxes/sandbox123/background/nonexistent")


class TestRequestModels:
    """Test request model validations."""

    def test_exec_request_minimal(self):
        """Test ExecRequest with minimal fields."""
        from sandbox_api import ExecRequest

        request = ExecRequest(command="ls")
        assert request.command == "ls"
        assert request.args is None
        assert request.code is None
        assert request.timeout is None
        assert request.requires_native is False

    def test_exec_request_full(self):
        """Test ExecRequest with all fields."""
        from sandbox_api import ExecRequest

        request = ExecRequest(
            command="python",
            args=["-c"],
            code="print('hello')",
            timeout=60,
            requires_native=True
        )
        assert request.command == "python"
        assert request.args == ["-c"]
        assert request.code == "print('hello')"
        assert request.timeout == 60
        assert request.requires_native is True

    def test_file_write_request(self):
        """Test FileWriteRequest model."""
        from sandbox_api import FileWriteRequest

        request = FileWriteRequest(
            path="/workspace/test.txt",
            data="content"
        )
        assert request.path == "/workspace/test.txt"
        assert request.data == "content"

    def test_preview_request(self):
        """Test PreviewRequest model."""
        from sandbox_api import PreviewRequest

        request = PreviewRequest(port=8080)
        assert request.port == 8080

    def test_mount_request(self):
        """Test MountRequest model."""
        from sandbox_api import MountRequest

        request = MountRequest(alias="shared", target="/tmp/shared")
        assert request.alias == "shared"
        assert request.target == "/tmp/shared"

    def test_background_request_minimal(self):
        """Test BackgroundRequest with minimal fields."""
        from sandbox_api import BackgroundRequest

        request = BackgroundRequest(command="ls")
        assert request.command == "ls"
        assert request.args is None
        assert request.interval == 5

    def test_background_request_full(self):
        """Test BackgroundRequest with all fields."""
        from sandbox_api import BackgroundRequest

        request = BackgroundRequest(
            command="watch",
            args=["-n", "10", "ls"],
            interval=10
        )
        assert request.command == "watch"
        assert request.args == ["-n", "10", "ls"]
        assert request.interval == 10


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.fixture
    def client(self):
        """Create a test client."""
        return TestClient(app)

    @pytest.fixture
    def mock_manager(self):
        """Mock the SandboxManager."""
        with mock.patch('sandbox_api.manager') as mock_mgr:
            yield mock_mgr

    def test_exec_command_with_empty_args(self, client, mock_manager):
        """Test command execution with empty args list."""
        mock_result = {"stdout": "", "stderr": "", "exit_code": 0}

        async def mock_exec_command(*args, **kwargs):
            return mock_result

        mock_manager.exec_command = mock_exec_command

        response = client.post(
            "/sandboxes/sandbox123/exec",
            json={
                "command": "ls",
                "args": []
            }
        )

    def test_write_file_with_unicode_content(self, client, mock_manager):
        """Test file write with Unicode content."""
        mock_sandbox = mock.Mock()
        mock_sandbox.fs = mock.Mock()
        mock_sandbox.fs.write = mock.Mock()

        async def mock_get_sandbox(sandbox_id):
            return mock_sandbox

        mock_manager.get_sandbox = mock_get_sandbox

        response = client.post(
            "/sandboxes/sandbox123/files",
            json={
                "path": "/workspace/unicode.txt",
                "data": "Hello 世界 🌍"
            }
        )

    def test_list_files_root_path(self, client, mock_manager):
        """Test file listing at root."""
        mock_sandbox = mock.Mock()
        mock_sandbox.fs = mock.Mock()
        mock_sandbox.fs.list_dir = mock.Mock(return_value=[])

        async def mock_get_sandbox(sandbox_id):
            return mock_sandbox

        mock_manager.get_sandbox = mock_get_sandbox

        response = client.get("/sandboxes/sandbox123/files?path=")

    def test_read_file_with_binary_content(self, client, mock_manager):
        """Test reading file with binary content."""
        mock_sandbox = mock.Mock()
        mock_sandbox.fs = mock.Mock()
        # Binary content that can't be decoded as UTF-8
        mock_sandbox.fs.read = mock.Mock(return_value=b'\x80\x81\x82')

        async def mock_get_sandbox(sandbox_id):
            return mock_sandbox

        mock_manager.get_sandbox = mock_get_sandbox

        response = client.get("/sandboxes/sandbox123/files/binary.dat")

    def test_register_preview_high_port(self, client, mock_manager, mock_preview):
        """Test preview registration with high port number."""
        mock_sandbox = mock.Mock()

        async def mock_get_sandbox(sandbox_id):
            return mock_sandbox

        async def mock_register(sandbox_id, port, backend):
            return f"http://preview.example.com/{sandbox_id}/{port}"

        async def mock_register_preview(sandbox_id, port, url):
            pass

        mock_manager.get_sandbox = mock_get_sandbox
        with mock.patch('sandbox_api.preview') as mock_prev:
            mock_prev.register = mock_register
            mock_manager.register_preview = mock_register_preview

            response = client.post(
                "/sandboxes/sandbox123/preview",
                json={"port": 65535}
            )

    def test_background_job_with_zero_interval(self, client):
        """Test background job with zero interval."""
        with mock.patch('sandbox_api.backgrounds') as mock_backgrounds:
            mock_job = mock.Mock()
            mock_job.job_id = "job_zero_interval"

            async def mock_start_job(*args, **kwargs):
                return mock_job

            mock_backgrounds.start_job = mock_start_job

            response = client.post(
                "/sandboxes/sandbox123/background",
                json={
                    "command": "echo",
                    "interval": 0
                }
            )