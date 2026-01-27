#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for dirty arbiter module."""

import asyncio
import os
import signal
import struct
import tempfile
import pytest

from gunicorn.config import Config
from gunicorn.dirty.arbiter import DirtyArbiter
from gunicorn.dirty.errors import DirtyError
from gunicorn.dirty.protocol import DirtyProtocol, make_request


class MockStreamWriter:
    """Mock StreamWriter that captures written messages."""

    def __init__(self):
        self.messages = []
        self._buffer = b""
        self.closed = False

    def write(self, data):
        self._buffer += data

    async def drain(self):
        while len(self._buffer) >= DirtyProtocol.HEADER_SIZE:
            length = struct.unpack(
                DirtyProtocol.HEADER_FORMAT,
                self._buffer[:DirtyProtocol.HEADER_SIZE]
            )[0]
            total_size = DirtyProtocol.HEADER_SIZE + length
            if len(self._buffer) >= total_size:
                msg_data = self._buffer[DirtyProtocol.HEADER_SIZE:total_size]
                self._buffer = self._buffer[total_size:]
                self.messages.append(DirtyProtocol.decode(msg_data))
            else:
                break

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass

    def get_extra_info(self, name):
        return None


class MockLog:
    """Mock logger for testing."""

    def __init__(self):
        self.messages = []

    def debug(self, msg, *args):
        self.messages.append(("debug", msg % args if args else msg))

    def info(self, msg, *args):
        self.messages.append(("info", msg % args if args else msg))

    def warning(self, msg, *args):
        self.messages.append(("warning", msg % args if args else msg))

    def error(self, msg, *args):
        self.messages.append(("error", msg % args if args else msg))

    def critical(self, msg, *args):
        self.messages.append(("critical", msg % args if args else msg))

    def exception(self, msg, *args):
        self.messages.append(("exception", msg % args if args else msg))

    def close_on_exec(self):
        pass

    def reopen_files(self):
        pass


class TestDirtyArbiterInit:
    """Tests for DirtyArbiter initialization."""

    def test_init_attributes(self):
        """Test that arbiter is initialized with correct attributes."""
        cfg = Config()
        cfg.set("dirty_workers", 2)
        cfg.set("dirty_apps", ["tests.support_dirty_app:TestDirtyApp"])
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)

        assert arbiter.cfg == cfg
        assert arbiter.log == log
        assert arbiter.workers == {}
        assert arbiter.alive is True
        assert arbiter.worker_age == 0
        assert arbiter.tmpdir is not None
        assert os.path.isdir(arbiter.tmpdir)

        # Cleanup
        arbiter._cleanup_sync()

    def test_init_with_custom_socket_path(self):
        """Test initialization with custom socket path."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "custom.sock")
            arbiter = DirtyArbiter(cfg=cfg, log=log, socket_path=socket_path)

            assert arbiter.socket_path == socket_path

            # Cleanup
            arbiter._cleanup_sync()

    def test_init_with_pidfile(self):
        """Test initialization with pidfile parameter."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            pidfile = os.path.join(tmpdir, "dirty.pid")
            arbiter = DirtyArbiter(cfg=cfg, log=log, pidfile=pidfile)

            assert arbiter.pidfile == pidfile

            # Cleanup
            arbiter._cleanup_sync()

    def test_init_without_pidfile(self):
        """Test initialization without pidfile parameter defaults to None."""
        cfg = Config()
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)

        assert arbiter.pidfile is None

        # Cleanup
        arbiter._cleanup_sync()


class TestDirtyArbiterCleanup:
    """Tests for arbiter cleanup."""

    def test_cleanup_removes_socket(self):
        """Test that cleanup removes the socket file."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "test.sock")
            arbiter = DirtyArbiter(cfg=cfg, log=log, socket_path=socket_path)

            # Create socket file
            with open(socket_path, 'w') as f:
                f.write('')

            assert os.path.exists(socket_path)

            arbiter._cleanup_sync()

            assert not os.path.exists(socket_path)

    def test_cleanup_removes_tmpdir(self):
        """Test that cleanup removes the temp directory."""
        cfg = Config()
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        tmpdir = arbiter.tmpdir

        assert os.path.isdir(tmpdir)

        arbiter._cleanup_sync()

        assert not os.path.exists(tmpdir)

    def test_cleanup_removes_pidfile(self):
        """Test that cleanup removes the PID file."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            pidfile = os.path.join(tmpdir, "dirty.pid")
            arbiter = DirtyArbiter(cfg=cfg, log=log, pidfile=pidfile)

            # Create pidfile
            with open(pidfile, 'w') as f:
                f.write('12345')

            assert os.path.exists(pidfile)

            arbiter._cleanup_sync()

            assert not os.path.exists(pidfile)

    def test_cleanup_handles_missing_pidfile(self):
        """Test that cleanup handles non-existent pidfile gracefully."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            pidfile = os.path.join(tmpdir, "nonexistent.pid")
            arbiter = DirtyArbiter(cfg=cfg, log=log, pidfile=pidfile)

            # Don't create the file
            assert not os.path.exists(pidfile)

            # Should not raise
            arbiter._cleanup_sync()

    def test_cleanup_without_pidfile(self):
        """Test that cleanup works when no pidfile configured."""
        cfg = Config()
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        assert arbiter.pidfile is None

        # Should not raise
        arbiter._cleanup_sync()


class TestDirtyArbiterPidfileWrite:
    """Tests for PID file writing during run()."""

    def test_run_writes_pidfile(self):
        """Test that run() writes the PID to the pidfile."""
        from unittest import mock

        cfg = Config()
        cfg.set("dirty_workers", 0)
        cfg.set("dirty_apps", ["tests.support_dirty_app:TestDirtyApp"])
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            pidfile = os.path.join(tmpdir, "dirty.pid")
            arbiter = DirtyArbiter(cfg=cfg, log=log, pidfile=pidfile)

            # Track if PID file was written correctly
            pid_written = None

            def mock_asyncio_run(coro):
                nonlocal pid_written
                # At this point, PID file should have been written
                if os.path.exists(pidfile):
                    with open(pidfile) as f:
                        pid_written = int(f.read().strip())
                # Close coroutine to avoid "never awaited" warning
                coro.close()

            # Mock asyncio.run to check PID file before cleanup runs
            with mock.patch.object(asyncio, 'run', side_effect=mock_asyncio_run):
                arbiter.run()

            # Check PID was written correctly
            assert pid_written == os.getpid()

    def test_run_without_pidfile_does_not_fail(self):
        """Test that run() works when no pidfile configured."""
        from unittest import mock

        cfg = Config()
        cfg.set("dirty_workers", 0)
        cfg.set("dirty_apps", ["tests.support_dirty_app:TestDirtyApp"])
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)

        def mock_asyncio_run(coro):
            # Close coroutine to avoid "never awaited" warning
            coro.close()

        with mock.patch.object(asyncio, 'run', side_effect=mock_asyncio_run):
            # Should not raise
            arbiter.run()


class TestDirtyArbiterRouteRequest:
    """Tests for request routing."""

    @pytest.mark.asyncio
    async def test_route_request_no_workers(self):
        """Test routing request when no workers available."""
        cfg = Config()
        cfg.set("dirty_workers", 0)
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.pid = os.getpid()

        request = make_request(
            request_id="test-123",
            app_path="test:App",
            action="test"
        )

        writer = MockStreamWriter()
        await arbiter.route_request(request, writer)

        assert len(writer.messages) == 1
        response = writer.messages[0]
        assert response["type"] == DirtyProtocol.MSG_TYPE_ERROR
        assert "No dirty workers available" in response["error"]["message"]

        arbiter._cleanup_sync()


class TestDirtyArbiterWorkerManagement:
    """Tests for worker management (without actually forking)."""

    def test_cleanup_worker(self):
        """Test worker cleanup method."""
        cfg = Config()
        cfg.set("dirty_workers", 2)
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)

        # Simulate a worker being registered
        fake_pid = 99999
        arbiter.workers[fake_pid] = "fake_worker"
        arbiter.worker_sockets[fake_pid] = "/tmp/fake.sock"

        arbiter._cleanup_worker(fake_pid)

        assert fake_pid not in arbiter.workers
        assert fake_pid not in arbiter.worker_sockets

        arbiter._cleanup_sync()

    @pytest.mark.asyncio
    async def test_cleanup_worker_cancels_consumer(self):
        """Test that worker cleanup cancels consumer task and removes queue."""
        cfg = Config()
        cfg.set("dirty_workers", 2)
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.alive = True

        # Simulate a worker with queue and consumer
        fake_pid = 99999
        arbiter.workers[fake_pid] = "fake_worker"
        arbiter.worker_sockets[fake_pid] = "/tmp/fake.sock"

        # Create queue and mock consumer task
        arbiter.worker_queues[fake_pid] = asyncio.Queue()

        async def mock_consumer():
            try:
                while True:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                pass

        arbiter.worker_consumers[fake_pid] = asyncio.create_task(mock_consumer())

        arbiter._cleanup_worker(fake_pid)

        assert fake_pid not in arbiter.workers
        assert fake_pid not in arbiter.worker_sockets
        assert fake_pid not in arbiter.worker_queues
        assert fake_pid not in arbiter.worker_consumers

        arbiter._cleanup_sync()

    def test_reap_workers_no_children(self):
        """Test reap_workers when no children have exited."""
        cfg = Config()
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.pid = os.getpid()

        # Should not raise even with no children
        arbiter.reap_workers()

        arbiter._cleanup_sync()

    def test_close_worker_connection(self):
        """Test _close_worker_connection method."""
        cfg = Config()
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)

        # Mock connection
        class MockWriter:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        mock_writer = MockWriter()
        mock_reader = object()
        arbiter.worker_connections[99999] = (mock_reader, mock_writer)

        arbiter._close_worker_connection(99999)

        assert 99999 not in arbiter.worker_connections
        assert mock_writer.closed is True

        arbiter._cleanup_sync()

    def test_close_worker_connection_not_exists(self):
        """Test _close_worker_connection when connection doesn't exist."""
        cfg = Config()
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)

        # Should not raise
        arbiter._close_worker_connection(99999)

        arbiter._cleanup_sync()


class TestDirtyArbiterSignals:
    """Tests for signal handling."""

    def test_signal_handler_sigterm(self):
        """Test SIGTERM handling."""
        cfg = Config()
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.pid = os.getpid()

        assert arbiter.alive is True
        arbiter._signal_handler(signal.SIGTERM, None)
        assert arbiter.alive is False

        arbiter._cleanup_sync()

    def test_signal_handler_sigquit(self):
        """Test SIGQUIT handling."""
        cfg = Config()
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.pid = os.getpid()

        assert arbiter.alive is True
        arbiter._signal_handler(signal.SIGQUIT, None)
        assert arbiter.alive is False

        arbiter._cleanup_sync()

    def test_signal_handler_sigint(self):
        """Test SIGINT handling."""
        cfg = Config()
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.pid = os.getpid()

        assert arbiter.alive is True
        arbiter._signal_handler(signal.SIGINT, None)
        assert arbiter.alive is False

        arbiter._cleanup_sync()

    def test_signal_handler_sigusr1_reopens_logs(self):
        """Test SIGUSR1 reopens log files."""
        cfg = Config()
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.pid = os.getpid()

        assert arbiter.alive is True
        arbiter._signal_handler(signal.SIGUSR1, None)
        # Should NOT set alive to False
        assert arbiter.alive is True

        arbiter._cleanup_sync()

    def test_signal_handler_with_loop(self):
        """Test signal handler calls _shutdown with loop."""
        cfg = Config()
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.pid = os.getpid()

        # Create mock loop
        loop = asyncio.new_event_loop()
        arbiter._loop = loop
        shutdown_called = []

        def mock_call_soon_threadsafe(cb):
            shutdown_called.append(cb)

        loop.call_soon_threadsafe = mock_call_soon_threadsafe

        arbiter._signal_handler(signal.SIGTERM, None)

        assert arbiter.alive is False
        assert len(shutdown_called) == 1

        loop.close()
        arbiter._cleanup_sync()


class TestDirtyArbiterShutdown:
    """Tests for shutdown."""

    def test_shutdown_closes_server(self):
        """Test that _shutdown closes the server."""
        cfg = Config()
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)

        class MockServer:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        arbiter._server = MockServer()
        arbiter._shutdown()
        assert arbiter._server.closed is True

        arbiter._cleanup_sync()

    def test_shutdown_without_server(self):
        """Test _shutdown when server is None."""
        cfg = Config()
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)

        # Should not raise
        arbiter._shutdown()

        arbiter._cleanup_sync()

    def test_init_signals(self):
        """Test init_signals sets up signal handlers."""
        cfg = Config()
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)

        original = signal.getsignal(signal.SIGTERM)
        try:
            arbiter.init_signals()
            assert signal.getsignal(signal.SIGTERM) == arbiter._signal_handler
            assert signal.getsignal(signal.SIGQUIT) == arbiter._signal_handler
            assert signal.getsignal(signal.SIGINT) == arbiter._signal_handler
            assert signal.getsignal(signal.SIGHUP) == arbiter._signal_handler
            assert signal.getsignal(signal.SIGUSR1) == arbiter._signal_handler
            assert signal.getsignal(signal.SIGCHLD) == arbiter._signal_handler
        finally:
            signal.signal(signal.SIGTERM, original)

        arbiter._cleanup_sync()


class TestDirtyArbiterRouteTimeout:
    """Tests for request timeout handling."""

    @pytest.mark.asyncio
    async def test_route_request_timeout(self):
        """Test that route_request handles timeout correctly."""
        cfg = Config()
        cfg.set("dirty_workers", 0)
        cfg.set("dirty_timeout", 1)  # 1 second timeout
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.pid = os.getpid()

        # Register a fake worker
        fake_pid = 99999
        arbiter.workers[fake_pid] = "fake_worker"
        arbiter.worker_sockets[fake_pid] = "/tmp/nonexistent.sock"

        request = make_request(
            request_id="timeout-test",
            app_path="test:App",
            action="slow_action"
        )

        # This should fail because socket doesn't exist
        writer = MockStreamWriter()
        await arbiter.route_request(request, writer)

        assert len(writer.messages) == 1
        response = writer.messages[0]
        assert response["type"] == DirtyProtocol.MSG_TYPE_ERROR
        # Either "Worker communication failed" or "Worker socket not ready"
        assert "error" in response

        arbiter._cleanup_sync()

    @pytest.mark.asyncio
    async def test_get_available_worker_returns_first(self):
        """Test _get_available_worker returns first worker."""
        cfg = Config()
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)

        # No workers
        result = await arbiter._get_available_worker()
        assert result is None

        # Add workers
        arbiter.workers[1001] = "worker1"
        arbiter.workers[1002] = "worker2"

        result = await arbiter._get_available_worker()
        assert result in [1001, 1002]

        arbiter._cleanup_sync()


class TestDirtyArbiterWorkerConnection:
    """Tests for worker connection management."""

    @pytest.mark.asyncio
    async def test_get_worker_connection_cached(self):
        """Test that _get_worker_connection returns cached connection."""
        cfg = Config()
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)

        # Set up cached connection
        mock_reader = object()
        mock_writer = object()
        arbiter.worker_connections[99999] = (mock_reader, mock_writer)
        arbiter.worker_sockets[99999] = "/tmp/test.sock"

        reader, writer = await arbiter._get_worker_connection(99999)

        assert reader is mock_reader
        assert writer is mock_writer

        arbiter._cleanup_sync()

    @pytest.mark.asyncio
    async def test_get_worker_connection_no_socket(self):
        """Test _get_worker_connection fails when no socket path."""
        cfg = Config()
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.workers[99999] = "fake_worker"
        # No socket path registered

        with pytest.raises(DirtyError) as exc_info:
            await arbiter._get_worker_connection(99999)

        assert "No socket for worker" in str(exc_info.value)

        arbiter._cleanup_sync()

    @pytest.mark.asyncio
    async def test_get_worker_connection_socket_not_ready(self):
        """Test _get_worker_connection when socket file doesn't exist."""
        cfg = Config()
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.workers[99999] = "fake_worker"
        arbiter.worker_sockets[99999] = "/tmp/nonexistent_socket_12345.sock"

        with pytest.raises(DirtyError) as exc_info:
            await arbiter._get_worker_connection(99999)

        assert "Worker socket not ready" in str(exc_info.value)

        arbiter._cleanup_sync()


class TestDirtyArbiterManageWorkers:
    """Tests for worker pool management."""

    @pytest.mark.asyncio
    async def test_manage_workers_zero_target(self):
        """Test manage_workers with zero target workers."""
        cfg = Config()
        cfg.set("dirty_workers", 0)
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.pid = os.getpid()

        # Should not spawn any workers
        await arbiter.manage_workers()
        assert len(arbiter.workers) == 0

        arbiter._cleanup_sync()


class TestDirtyArbiterKillWorker:
    """Tests for killing workers."""

    def test_kill_worker_no_process(self):
        """Test kill_worker when process doesn't exist."""
        cfg = Config()
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.pid = os.getpid()

        # Register fake worker
        arbiter.workers[99999] = "fake_worker"
        arbiter.worker_sockets[99999] = "/tmp/fake.sock"

        # Kill non-existent process - should cleanup
        arbiter.kill_worker(99999, signal.SIGTERM)

        # Worker should be cleaned up
        assert 99999 not in arbiter.workers

        arbiter._cleanup_sync()


class TestDirtyArbiterMurderWorkers:
    """Tests for worker timeout detection."""

    @pytest.mark.asyncio
    async def test_murder_workers_no_timeout_config(self):
        """Test murder_workers with no timeout configured."""
        cfg = Config()
        cfg.set("dirty_timeout", 0)  # Disabled
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.pid = os.getpid()

        # Should return early without checking
        await arbiter.murder_workers()

        arbiter._cleanup_sync()


class TestDirtyArbiterStop:
    """Tests for stop functionality."""

    @pytest.mark.asyncio
    async def test_stop_graceful(self):
        """Test graceful stop with no workers."""
        cfg = Config()
        cfg.set("dirty_graceful_timeout", 1)
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.pid = os.getpid()

        # No workers - should complete quickly
        await arbiter.stop(graceful=True)

        arbiter._cleanup_sync()

    @pytest.mark.asyncio
    async def test_stop_not_graceful(self):
        """Test non-graceful stop."""
        cfg = Config()
        cfg.set("dirty_graceful_timeout", 1)
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.pid = os.getpid()

        await arbiter.stop(graceful=False)

        arbiter._cleanup_sync()


class TestDirtyArbiterReload:
    """Tests for reload functionality."""

    @pytest.mark.asyncio
    async def test_reload_with_no_workers(self):
        """Test reload when no workers exist."""
        cfg = Config()
        cfg.set("dirty_workers", 0)
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.pid = os.getpid()

        # Should complete without spawning
        await arbiter.reload()

        assert len(arbiter.workers) == 0

        arbiter._cleanup_sync()


class TestDirtyArbiterRunAsync:
    """Tests for async run loop."""

    @pytest.mark.asyncio
    async def test_run_async_creates_server(self):
        """Test that _run_async creates Unix server."""
        cfg = Config()
        cfg.set("dirty_workers", 0)
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "test_arbiter.sock")
            arbiter = DirtyArbiter(cfg=cfg, log=log, socket_path=socket_path)
            arbiter.pid = os.getpid()

            # Run briefly and stop
            async def run_briefly():
                arbiter._loop = asyncio.get_running_loop()

                if os.path.exists(socket_path):
                    os.unlink(socket_path)

                arbiter._server = await asyncio.start_unix_server(
                    arbiter.handle_client,
                    path=socket_path
                )
                os.chmod(socket_path, 0o600)

                # Verify socket exists
                assert os.path.exists(socket_path)

                # Shutdown
                arbiter._server.close()
                await arbiter._server.wait_closed()

            await run_briefly()

            arbiter._cleanup_sync()


class TestDirtyArbiterHandleClient:
    """Tests for client connection handling."""

    @pytest.mark.asyncio
    async def test_handle_client_connection_close(self):
        """Test handle_client when connection closes."""
        cfg = Config()
        cfg.set("dirty_workers", 0)
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.pid = os.getpid()
        arbiter.alive = True

        # Create reader that returns EOF
        reader = asyncio.StreamReader()
        reader.feed_eof()

        class MockWriter:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

            async def wait_closed(self):
                pass

        writer = MockWriter()

        # Should exit without error when EOF is received
        await arbiter.handle_client(reader, writer)

        assert writer.closed is True

        arbiter._cleanup_sync()


class TestDirtyArbiterWorkerMonitor:
    """Tests for worker monitoring."""

    @pytest.mark.asyncio
    async def test_worker_monitor_loop(self):
        """Test worker monitor runs periodically."""
        cfg = Config()
        cfg.set("dirty_workers", 0)
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.pid = os.getpid()
        arbiter.ppid = os.getppid()  # Match actual parent for ppid check
        arbiter.alive = True

        monitor_calls = 0

        async def mock_murder_workers():
            nonlocal monitor_calls
            monitor_calls += 1
            if monitor_calls >= 2:
                arbiter.alive = False

        async def mock_manage_workers():
            pass

        arbiter.murder_workers = mock_murder_workers
        arbiter.manage_workers = mock_manage_workers

        # Run monitor briefly
        await arbiter._worker_monitor()

        assert monitor_calls >= 2

        arbiter._cleanup_sync()

    @pytest.mark.asyncio
    async def test_worker_monitor_detects_parent_death(self):
        """Test worker monitor exits when parent dies."""
        cfg = Config()
        cfg.set("dirty_workers", 0)
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.pid = os.getpid()
        arbiter.ppid = 99999  # Fake parent PID that doesn't match os.getppid()
        arbiter.alive = True

        shutdown_called = []

        def mock_shutdown():
            shutdown_called.append(True)

        arbiter._shutdown = mock_shutdown

        # Run monitor - should detect parent change and exit
        await arbiter._worker_monitor()

        # Should have detected parent death
        assert arbiter.alive is False
        assert len(shutdown_called) == 1

        # Check log message
        log_messages = [msg for level, msg in log.messages if level == "warning"]
        assert any("Parent changed" in msg for msg in log_messages)

        arbiter._cleanup_sync()


class TestDirtyArbiterHandleSigchld:
    """Tests for SIGCHLD handling."""

    @pytest.mark.asyncio
    async def test_handle_sigchld_reaps_workers(self):
        """Test _handle_sigchld calls reap_workers and manage_workers."""
        cfg = Config()
        cfg.set("dirty_workers", 0)
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.pid = os.getpid()

        reap_called = []
        manage_called = []

        def mock_reap():
            reap_called.append(True)

        async def mock_manage():
            manage_called.append(True)

        arbiter.reap_workers = mock_reap
        arbiter.manage_workers = mock_manage

        await arbiter._handle_sigchld()

        assert len(reap_called) == 1
        assert len(manage_called) == 1

        arbiter._cleanup_sync()

    def test_sigchld_handler_with_loop(self):
        """Test SIGCHLD signal creates task on loop."""
        cfg = Config()
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.pid = os.getpid()

        loop = asyncio.new_event_loop()
        arbiter._loop = loop
        tasks_scheduled = []

        def mock_call_soon_threadsafe(cb):
            tasks_scheduled.append(cb)

        loop.call_soon_threadsafe = mock_call_soon_threadsafe

        arbiter._signal_handler(signal.SIGCHLD, None)

        assert len(tasks_scheduled) == 1

        loop.close()
        arbiter._cleanup_sync()


class TestDirtyArbiterSighupHandler:
    """Tests for SIGHUP (reload) handling."""

    def test_sighup_handler_with_loop(self):
        """Test SIGHUP signal schedules reload."""
        cfg = Config()
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.pid = os.getpid()

        loop = asyncio.new_event_loop()
        arbiter._loop = loop
        tasks_scheduled = []

        def mock_call_soon_threadsafe(cb):
            tasks_scheduled.append(cb)

        loop.call_soon_threadsafe = mock_call_soon_threadsafe

        arbiter._signal_handler(signal.SIGHUP, None)

        # Should still be alive (SIGHUP is reload, not shutdown)
        assert arbiter.alive is True
        assert len(tasks_scheduled) == 1

        loop.close()
        arbiter._cleanup_sync()


class TestDirtyArbiterQueueBehavior:
    """Tests for queue-based request routing."""

    @pytest.mark.asyncio
    async def test_start_worker_consumer_creates_queue_and_task(self):
        """Test _start_worker_consumer creates queue and task."""
        cfg = Config()
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.alive = True

        fake_pid = 99999

        await arbiter._start_worker_consumer(fake_pid)

        assert fake_pid in arbiter.worker_queues
        assert fake_pid in arbiter.worker_consumers
        assert isinstance(arbiter.worker_queues[fake_pid], asyncio.Queue)
        assert isinstance(arbiter.worker_consumers[fake_pid], asyncio.Task)

        # Cancel task for cleanup
        arbiter.worker_consumers[fake_pid].cancel()
        try:
            await arbiter.worker_consumers[fake_pid]
        except asyncio.CancelledError:
            pass

        arbiter._cleanup_sync()

    @pytest.mark.asyncio
    async def test_route_request_starts_consumer_on_demand(self):
        """Test route_request starts consumer if not exists."""
        cfg = Config()
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.pid = os.getpid()
        arbiter.alive = True

        # Register fake worker
        fake_pid = 99999
        arbiter.workers[fake_pid] = "fake_worker"
        arbiter.worker_sockets[fake_pid] = "/tmp/nonexistent.sock"

        assert fake_pid not in arbiter.worker_queues
        assert fake_pid not in arbiter.worker_consumers

        # Make request - should start consumer
        request = make_request(
            request_id="test-123",
            app_path="test:App",
            action="test"
        )

        # This will fail (no socket), but consumer should be started
        writer = MockStreamWriter()
        await arbiter.route_request(request, writer)

        assert fake_pid in arbiter.worker_queues
        assert fake_pid in arbiter.worker_consumers

        # Cleanup
        arbiter.alive = False
        arbiter.worker_consumers[fake_pid].cancel()
        try:
            await arbiter.worker_consumers[fake_pid]
        except asyncio.CancelledError:
            pass

        arbiter._cleanup_sync()

    @pytest.mark.asyncio
    async def test_stop_cancels_all_consumers(self):
        """Test stop() cancels all consumer tasks."""
        cfg = Config()
        cfg.set("dirty_graceful_timeout", 1)
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.pid = os.getpid()
        arbiter.alive = True

        # Create mock consumers
        async def mock_consumer():
            try:
                while True:
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                pass

        task1 = asyncio.create_task(mock_consumer())
        task2 = asyncio.create_task(mock_consumer())
        arbiter.worker_consumers[1] = task1
        arbiter.worker_consumers[2] = task2

        await arbiter.stop(graceful=True)

        # Allow cancelled tasks to complete
        await asyncio.sleep(0)

        # All consumers should be done (cancelled and caught)
        assert task1.done()
        assert task2.done()

        arbiter._cleanup_sync()
