"""Comprehensive tests for serverless_workers_router/orchestrator.py module."""

import asyncio
import os
import subprocess
import tempfile
import shutil
from pathlib import Path
from unittest import mock
import pytest

from serverless_workers_router.orchestrator import (
    FallbackProcess,
    PortAllocator,
    FallbackOrchestrator
)


class TestFallbackProcess:
    """Test suite for FallbackProcess dataclass."""

    def test_fallback_process_creation(self):
        """Test FallbackProcess dataclass creation."""
        mock_process = mock.Mock()
        mock_workspace = Path("/tmp/workspace")

        fp = FallbackProcess(
            sandbox_id="sandbox123",
            port=33000,
            process=mock_process,
            workspace=mock_workspace,
            stdout=None,
            stderr=None
        )

        assert fp.sandbox_id == "sandbox123"
        assert fp.port == 33000
        assert fp.process == mock_process
        assert fp.workspace == mock_workspace
        assert fp.stdout is None
        assert fp.stderr is None
        assert isinstance(fp.started_at, float)


class TestPortAllocator:
    """Test suite for PortAllocator class."""

    @pytest.mark.asyncio
    async def test_port_allocator_initialization(self):
        """Test PortAllocator initialization."""
        allocator = PortAllocator(start=33000, end=33999)
        assert allocator._start == 33000
        assert allocator._end == 33999
        assert allocator._current == 33000

    @pytest.mark.asyncio
    async def test_port_allocator_default_initialization(self):
        """Test PortAllocator with default values."""
        allocator = PortAllocator()
        assert allocator._start == 33000
        assert allocator._end == 33999

    @pytest.mark.asyncio
    async def test_allocate_port(self):
        """Test port allocation."""
        allocator = PortAllocator(start=40000, end=40010)

        port1 = await allocator.allocate()
        assert port1 == 40000

        port2 = await allocator.allocate()
        assert port2 == 40001

        port3 = await allocator.allocate()
        assert port3 == 40002

    @pytest.mark.asyncio
    async def test_allocate_port_wraps_around(self):
        """Test port allocation wraps around when end is reached."""
        allocator = PortAllocator(start=45000, end=45002)

        # Allocate ports until we reach the end
        port1 = await allocator.allocate()
        assert port1 == 45000

        port2 = await allocator.allocate()
        assert port2 == 45001

        port3 = await allocator.allocate()
        assert port3 == 45002

        # Next allocation should wrap around
        port4 = await allocator.allocate()
        assert port4 == 45000

    @pytest.mark.asyncio
    async def test_allocate_port_thread_safe(self):
        """Test that port allocation is thread-safe."""
        allocator = PortAllocator(start=50000, end=50100)

        # Allocate ports concurrently
        ports = await asyncio.gather(*[allocator.allocate() for _ in range(10)])

        # All ports should be unique
        assert len(ports) == len(set(ports))


class TestFallbackOrchestrator:
    """Test suite for FallbackOrchestrator class."""

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary directories for testing."""
        workspace_dir = tempfile.mkdtemp()
        snapshot_dir = tempfile.mkdtemp()
        yield workspace_dir, snapshot_dir
        shutil.rmtree(workspace_dir, ignore_errors=True)
        shutil.rmtree(snapshot_dir, ignore_errors=True)

    @pytest.fixture
    def orchestrator(self, temp_dirs):
        """Create a FallbackOrchestrator instance."""
        workspace_dir, snapshot_dir = temp_dirs
        return FallbackOrchestrator(
            workspace_dir=workspace_dir,
            snapshot_dir=snapshot_dir
        )

    def test_orchestrator_initialization(self, temp_dirs):
        """Test FallbackOrchestrator initialization."""
        workspace_dir, snapshot_dir = temp_dirs
        orchestrator = FallbackOrchestrator(
            workspace_dir=workspace_dir,
            snapshot_dir=snapshot_dir
        )

        assert orchestrator.container is not None
        assert orchestrator.port_allocator is not None
        assert orchestrator._processes == {}

    def test_orchestrator_with_custom_port_allocator(self, temp_dirs):
        """Test FallbackOrchestrator with custom port allocator."""
        workspace_dir, snapshot_dir = temp_dirs
        custom_allocator = PortAllocator(start=60000, end=60999)

        orchestrator = FallbackOrchestrator(
            workspace_dir=workspace_dir,
            snapshot_dir=snapshot_dir,
            port_allocator=custom_allocator
        )

        assert orchestrator.port_allocator == custom_allocator

    @pytest.mark.asyncio
    async def test_promote_to_container_new_sandbox(self, orchestrator):
        """Test promoting a new sandbox to container."""
        sandbox_id = "sandbox_new"

        with mock.patch('subprocess.Popen') as mock_popen:
            mock_process = mock.Mock()
            mock_process.poll = mock.Mock(return_value=None)
            mock_popen.return_value = mock_process

            url = await orchestrator.promote_to_container(sandbox_id)

            assert url.startswith("http://127.0.0.1:")
            assert sandbox_id in orchestrator._processes

            process_info = orchestrator._processes[sandbox_id]
            assert process_info.sandbox_id == sandbox_id
            assert process_info.process == mock_process

    @pytest.mark.asyncio
    async def test_promote_to_container_existing_sandbox(self, orchestrator):
        """Test promoting an existing sandbox returns same URL."""
        sandbox_id = "sandbox_existing"

        with mock.patch('subprocess.Popen') as mock_popen:
            mock_process = mock.Mock()
            mock_process.poll = mock.Mock(return_value=None)
            mock_popen.return_value = mock_process

            # First call
            url1 = await orchestrator.promote_to_container(sandbox_id)

            # Second call should return same URL
            url2 = await orchestrator.promote_to_container(sandbox_id)

            assert url1 == url2
            assert mock_popen.call_count == 1

    @pytest.mark.asyncio
    async def test_promote_to_container_creates_workspace(self, orchestrator):
        """Test that promote_to_container creates workspace."""
        sandbox_id = "sandbox_workspace_test"

        with mock.patch('subprocess.Popen') as mock_popen:
            mock_process = mock.Mock()
            mock_process.poll = mock.Mock(return_value=None)
            mock_popen.return_value = mock_process

            await orchestrator.promote_to_container(sandbox_id)

            # Check workspace was created
            workspace_path = orchestrator.container._get_workspace_path(sandbox_id)
            assert workspace_path.exists()
            assert (workspace_path / "code").exists()

    @pytest.mark.asyncio
    async def test_promote_to_container_creates_log_directory(self, orchestrator):
        """Test that promote_to_container creates log directory."""
        sandbox_id = "sandbox_logs_test"

        with mock.patch('subprocess.Popen') as mock_popen:
            mock_process = mock.Mock()
            mock_process.poll = mock.Mock(return_value=None)
            mock_popen.return_value = mock_process

            await orchestrator.promote_to_container(sandbox_id)

            workspace_path = orchestrator.container._get_workspace_path(sandbox_id)
            log_dir = workspace_path / "logs"
            assert log_dir.exists()

    @pytest.mark.asyncio
    async def test_promote_to_container_starts_http_server(self, orchestrator):
        """Test that promote_to_container starts HTTP server."""
        sandbox_id = "sandbox_http_test"

        with mock.patch('subprocess.Popen') as mock_popen:
            mock_process = mock.Mock()
            mock_process.poll = mock.Mock(return_value=None)
            mock_popen.return_value = mock_process

            await orchestrator.promote_to_container(sandbox_id)

            # Verify Popen was called with correct arguments
            mock_popen.assert_called_once()
            call_args = mock_popen.call_args
            cmd = call_args[0][0]

            assert "-m" in cmd
            assert "http.server" in cmd
            assert "--bind" in cmd
            assert "127.0.0.1" in cmd

    @pytest.mark.asyncio
    async def test_promote_to_container_waits_for_startup(self, orchestrator):
        """Test that promote_to_container waits for server startup."""
        sandbox_id = "sandbox_startup_test"

        with mock.patch('subprocess.Popen') as mock_popen:
            with mock.patch('asyncio.sleep') as mock_sleep:
                mock_process = mock.Mock()
                mock_process.poll = mock.Mock(return_value=None)
                mock_popen.return_value = mock_process

                await orchestrator.promote_to_container(sandbox_id)

                # Should have called sleep to wait for startup
                mock_sleep.assert_called_once_with(0.5)

    @pytest.mark.asyncio
    async def test_stop_container_success(self, orchestrator):
        """Test successfully stopping a container."""
        sandbox_id = "sandbox_stop_test"

        with mock.patch('subprocess.Popen') as mock_popen:
            mock_process = mock.Mock()
            mock_process.poll = mock.Mock(return_value=None)
            mock_process.terminate = mock.Mock()
            mock_process.wait = mock.Mock()
            mock_popen.return_value = mock_process

            # First promote to create the container
            await orchestrator.promote_to_container(sandbox_id)

            # Now stop it
            await orchestrator.stop_container(sandbox_id)

            # Should have called terminate and wait
            mock_process.terminate.assert_called_once()
            mock_process.wait.assert_called_once_with(timeout=5)

            # Should be removed from processes
            assert sandbox_id not in orchestrator._processes

    @pytest.mark.asyncio
    async def test_stop_container_nonexistent(self, orchestrator):
        """Test stopping a non-existent container."""
        sandbox_id = "sandbox_nonexistent"

        # Should not raise an error
        await orchestrator.stop_container(sandbox_id)

    @pytest.mark.asyncio
    async def test_stop_container_kills_if_terminate_fails(self, orchestrator):
        """Test that stop_container kills process if terminate times out."""
        sandbox_id = "sandbox_kill_test"

        with mock.patch('subprocess.Popen') as mock_popen:
            mock_process = mock.Mock()
            mock_process.poll = mock.Mock(return_value=None)
            mock_process.terminate = mock.Mock()
            mock_process.wait = mock.Mock(side_effect=subprocess.TimeoutExpired(cmd="test", timeout=5))
            mock_process.kill = mock.Mock()
            mock_popen.return_value = mock_process

            await orchestrator.promote_to_container(sandbox_id)
            await orchestrator.stop_container(sandbox_id)

            # Should have called kill after wait timed out
            mock_process.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_container_closes_file_handles(self, orchestrator):
        """Test that stop_container closes file handles."""
        sandbox_id = "sandbox_handles_test"

        with mock.patch('subprocess.Popen') as mock_popen:
            with mock.patch('builtins.open', mock.mock_open()) as mock_file:
                mock_process = mock.Mock()
                mock_process.poll = mock.Mock(return_value=None)
                mock_process.terminate = mock.Mock()
                mock_process.wait = mock.Mock()
                mock_popen.return_value = mock_process

                await orchestrator.promote_to_container(sandbox_id)

                # Get the process info and verify handles exist
                process_info = orchestrator._processes[sandbox_id]

                # Mock the file handles
                mock_stdout = mock.Mock()
                mock_stderr = mock.Mock()
                process_info.stdout = mock_stdout
                process_info.stderr = mock_stderr

                await orchestrator.stop_container(sandbox_id)

                # Should have closed the handles
                mock_stdout.close.assert_called_once()
                mock_stderr.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_container_stops_container_fallback(self, orchestrator):
        """Test that stop_container calls container.stop_container."""
        sandbox_id = "sandbox_fallback_stop_test"

        with mock.patch('subprocess.Popen') as mock_popen:
            with mock.patch.object(orchestrator.container, 'stop_container') as mock_stop:
                mock_process = mock.Mock()
                mock_process.poll = mock.Mock(return_value=None)
                mock_process.terminate = mock.Mock()
                mock_process.wait = mock.Mock()
                mock_popen.return_value = mock_process

                await orchestrator.promote_to_container(sandbox_id)
                await orchestrator.stop_container(sandbox_id)

                # Should have called stop_container on container fallback
                mock_stop.assert_called_once_with(sandbox_id)

    @pytest.mark.asyncio
    async def test_cleanup_stale_removes_dead_processes(self, orchestrator):
        """Test that cleanup_stale removes processes that have exited."""
        sandbox_id = "sandbox_stale_test"

        with mock.patch('subprocess.Popen') as mock_popen:
            mock_process = mock.Mock()
            # Create a counter to track poll calls
            poll_count = [0]
            def poll_side_effect():
                poll_count[0] += 1
                if poll_count[0] == 1:
                    return None  # First call: running
                else:
                    return 0  # Subsequent calls: stopped

            mock_process.poll = mock.Mock(side_effect=poll_side_effect)
            mock_popen.return_value = mock_process

            await orchestrator.promote_to_container(sandbox_id)
            assert sandbox_id in orchestrator._processes

            # Now cleanup should remove it
            await orchestrator.cleanup_stale()
            assert sandbox_id not in orchestrator._processes

    @pytest.mark.asyncio
    async def test_cleanup_stale_keeps_running_processes(self, orchestrator):
        """Test that cleanup_stale keeps running processes."""
        sandbox_id = "sandbox_running_test"

        with mock.patch('subprocess.Popen') as mock_popen:
            mock_process = mock.Mock()
            mock_process.poll = mock.Mock(return_value=None)
            mock_popen.return_value = mock_process

            await orchestrator.promote_to_container(sandbox_id)
            assert sandbox_id in orchestrator._processes

            # Cleanup should not remove it
            await orchestrator.cleanup_stale()
            assert sandbox_id in orchestrator._processes

    @pytest.mark.asyncio
    async def test_cleanup_stale_calls_container_stop(self, orchestrator):
        """Test that cleanup_stale calls container.stop_container for dead processes."""
        sandbox_id = "sandbox_cleanup_stop_test"

        with mock.patch('subprocess.Popen') as mock_popen:
            with mock.patch.object(orchestrator.container, 'stop_container') as mock_stop:
                mock_process = mock.Mock()
                # Create a counter to track poll calls
                poll_count = [0]
                def poll_side_effect():
                    poll_count[0] += 1
                    if poll_count[0] == 1:
                        return None  # First call: running
                    else:
                        return 0  # Subsequent calls: stopped

                mock_process.poll = mock.Mock(side_effect=poll_side_effect)
                mock_popen.return_value = mock_process

                await orchestrator.promote_to_container(sandbox_id)
                await orchestrator.cleanup_stale()

                mock_stop.assert_called_once_with(sandbox_id)


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary directories for testing."""
        workspace_dir = tempfile.mkdtemp()
        snapshot_dir = tempfile.mkdtemp()
        yield workspace_dir, snapshot_dir
        shutil.rmtree(workspace_dir, ignore_errors=True)
        shutil.rmtree(snapshot_dir, ignore_errors=True)

    @pytest.fixture
    def orchestrator(self, temp_dirs):
        """Create a FallbackOrchestrator instance."""
        workspace_dir, snapshot_dir = temp_dirs
        return FallbackOrchestrator(
            workspace_dir=workspace_dir,
            snapshot_dir=snapshot_dir
        )

    @pytest.mark.asyncio
    async def test_concurrent_promotions(self, orchestrator):
        """Test concurrent promotions to the same sandbox."""
        sandbox_id = "sandbox_concurrent"

        with mock.patch('subprocess.Popen') as mock_popen:
            mock_process = mock.Mock()
            mock_process.poll = mock.Mock(return_value=None)
            mock_popen.return_value = mock_process

            # Try to promote concurrently
            urls = await asyncio.gather(
                orchestrator.promote_to_container(sandbox_id),
                orchestrator.promote_to_container(sandbox_id),
                orchestrator.promote_to_container(sandbox_id)
            )

            # All should return the same URL
            assert urls[0] == urls[1] == urls[2]

            # Should only have created one process
            assert mock_popen.call_count == 1

    @pytest.mark.asyncio
    async def test_promote_after_process_died(self, orchestrator):
        """Test promoting after process has died."""
        sandbox_id = "sandbox_died_test"

        with mock.patch('subprocess.Popen') as mock_popen:
            # Track calls separately for each process
            call_count = [0]

            def create_mock_process(*args, **kwargs):
                call_count[0] += 1
                current_call = call_count[0]
                mock_process = mock.Mock()

                # First process: alive on first check, dead on second
                # Second process: alive on check
                if current_call == 1:
                    mock_process.poll = mock.Mock(return_value=0)  # Dead
                else:
                    mock_process.poll = mock.Mock(return_value=None)  # Alive

                return mock_process

            mock_popen.side_effect = create_mock_process

            # First promotion
            url1 = await orchestrator.promote_to_container(sandbox_id)

            # Second promotion should detect dead process and create new one
            url2 = await orchestrator.promote_to_container(sandbox_id)

            # Should have created a new process
            assert mock_popen.call_count == 2

    @pytest.mark.asyncio
    async def test_stop_already_stopped_process(self, orchestrator):
        """Test stopping a process that's already stopped."""
        sandbox_id = "sandbox_already_stopped"

        with mock.patch('subprocess.Popen') as mock_popen:
            mock_process = mock.Mock()
            mock_process.poll = mock.Mock(return_value=0)  # Already stopped
            mock_process.terminate = mock.Mock()
            mock_popen.return_value = mock_process

            await orchestrator.promote_to_container(sandbox_id)
            await orchestrator.stop_container(sandbox_id)

            # Should still try to stop even if already stopped
            assert sandbox_id not in orchestrator._processes

    `@pytest.mark.asyncio`
    async def test_cleanup_multiple_stale_processes(self, orchestrator):
        """Test cleanup with multiple stale processes."""
        sandbox_ids = ["sandbox1", "sandbox2", "sandbox3"]

        with mock.patch('subprocess.Popen') as mock_popen:
            # Create processes that will be dead on cleanup
            mock_processes = []
            for sandbox_id in sandbox_ids:
                mock_process = mock.Mock()
                # Create a new list for each process
                poll_results = [None, 0]  # First check: alive, second check: dead
                mock_process.poll = mock.Mock(side_effect=poll_results)
                mock_processes.append(mock_process)
            
            mock_popen.side_effect = mock_processes
            for sandbox_id in sandbox_ids:
                await orchestrator.promote_to_container(sandbox_id)

            # All should be present
            assert len(orchestrator._processes) == 3

            # Cleanup should remove all
            await orchestrator.cleanup_stale()
            assert len(orchestrator._processes) == 0

    @pytest.mark.asyncio
    async def test_port_allocation_across_promotions(self, orchestrator):
        """Test that different sandboxes get different ports."""
        sandbox_ids = ["sandbox_port1", "sandbox_port2", "sandbox_port3"]

        with mock.patch('subprocess.Popen') as mock_popen:
            mock_process = mock.Mock()
            mock_process.poll = mock.Mock(return_value=None)
            mock_popen.return_value = mock_process

            urls = []
            for sandbox_id in sandbox_ids:
                url = await orchestrator.promote_to_container(sandbox_id)
                urls.append(url)

            # All URLs should be different (different ports)
            assert len(set(urls)) == len(urls)

    @pytest.mark.asyncio
    async def test_file_handle_management(self, orchestrator):
        """Test proper file handle management."""
        sandbox_id = "sandbox_handles"

        with mock.patch('subprocess.Popen') as mock_popen:
            mock_process = mock.Mock()
            mock_process.poll = mock.Mock(return_value=None)
            mock_popen.return_value = mock_process

            await orchestrator.promote_to_container(sandbox_id)

            process_info = orchestrator._processes[sandbox_id]

            # File handles should be open
            assert process_info.stdout is not None
            assert process_info.stderr is not None
            assert not process_info.stdout.closed
            assert not process_info.stderr.closed