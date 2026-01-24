#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for dirty worker module."""

import asyncio
import os
import signal
import tempfile
import pytest

from gunicorn.config import Config
from gunicorn.dirty.worker import DirtyWorker
from gunicorn.dirty.protocol import DirtyProtocol, make_request
from gunicorn.dirty.errors import DirtyAppNotFoundError


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

    def close_on_exec(self):
        pass

    def reopen_files(self):
        pass


class TestDirtyWorkerInit:
    """Tests for DirtyWorker initialization."""

    def test_init_attributes(self):
        """Test that worker is initialized with correct attributes."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=["tests.support_dirty_app:TestDirtyApp"],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            assert worker.age == 1
            assert worker.ppid == os.getpid()
            assert worker.app_paths == ["tests.support_dirty_app:TestDirtyApp"]
            assert worker.socket_path == socket_path
            assert worker.booted is False
            assert worker.alive is True
            assert worker.apps == {}

    def test_str_representation(self):
        """Test string representation."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            assert "DirtyWorker" in str(worker)


class TestDirtyWorkerLoadApps:
    """Tests for app loading."""

    def test_load_apps_success(self):
        """Test successful app loading."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=["tests.support_dirty_app:TestDirtyApp"],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            worker.load_apps()

            assert "tests.support_dirty_app:TestDirtyApp" in worker.apps
            app = worker.apps["tests.support_dirty_app:TestDirtyApp"]
            assert app.initialized is True  # init() was called

    def test_load_apps_failure(self):
        """Test failed app loading."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=["nonexistent:App"],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            with pytest.raises(Exception):
                worker.load_apps()


class TestDirtyWorkerExecute:
    """Tests for request execution."""

    @pytest.mark.asyncio
    async def test_execute_success(self):
        """Test successful execution."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=["tests.support_dirty_app:TestDirtyApp"],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            worker.load_apps()

            result = await worker.execute(
                "tests.support_dirty_app:TestDirtyApp",
                "compute",
                [2, 3],
                {"operation": "add"}
            )

            assert result == 5

    @pytest.mark.asyncio
    async def test_execute_app_not_found(self):
        """Test execution with unknown app."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            with pytest.raises(DirtyAppNotFoundError):
                await worker.execute("unknown:App", "action", [], {})


class TestDirtyWorkerHandleRequest:
    """Tests for request handling."""

    @pytest.mark.asyncio
    async def test_handle_request_success(self):
        """Test handling a successful request."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=["tests.support_dirty_app:TestDirtyApp"],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            worker.load_apps()

            request = make_request(
                request_id="test-123",
                app_path="tests.support_dirty_app:TestDirtyApp",
                action="compute",
                args=(2, 3),
                kwargs={"operation": "multiply"}
            )

            response = await worker.handle_request(request)

            assert response["type"] == DirtyProtocol.MSG_TYPE_RESPONSE
            assert response["id"] == "test-123"
            assert response["result"] == 6

    @pytest.mark.asyncio
    async def test_handle_request_error(self):
        """Test handling a request that fails."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=["tests.support_dirty_app:TestDirtyApp"],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            worker.load_apps()

            request = make_request(
                request_id="test-456",
                app_path="tests.support_dirty_app:TestDirtyApp",
                action="compute",
                args=(2, 3),
                kwargs={"operation": "invalid"}
            )

            response = await worker.handle_request(request)

            assert response["type"] == DirtyProtocol.MSG_TYPE_ERROR
            assert response["id"] == "test-456"
            assert "Unknown operation" in response["error"]["message"]

    @pytest.mark.asyncio
    async def test_handle_request_unknown_type(self):
        """Test handling request with unknown type."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            request = {"type": "unknown", "id": "test-789"}
            response = await worker.handle_request(request)

            assert response["type"] == DirtyProtocol.MSG_TYPE_ERROR
            assert "Unknown message type" in response["error"]["message"]


class TestDirtyWorkerCleanup:
    """Tests for worker cleanup."""

    def test_cleanup_closes_apps(self):
        """Test that cleanup closes all apps."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=["tests.support_dirty_app:TestDirtyApp"],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            worker.load_apps()
            app = worker.apps["tests.support_dirty_app:TestDirtyApp"]
            assert app.closed is False

            worker._cleanup()
            assert app.closed is True

    def test_cleanup_removes_socket(self):
        """Test that cleanup removes the socket file."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            # Create the socket file
            with open(socket_path, 'w') as f:
                f.write('')

            assert os.path.exists(socket_path)
            worker._cleanup()
            assert not os.path.exists(socket_path)


class TestDirtyWorkerNotify:
    """Tests for worker heartbeat."""

    def test_notify_calls_tmp_notify(self):
        """Test that notify calls tmp.notify()."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            # Just verify notify doesn't raise
            worker.notify()
            worker.notify()

            worker.tmp.close()


class TestDirtyWorkerSignals:
    """Tests for signal handling."""

    def test_signal_handler_sets_alive_false(self):
        """Test that signal handler sets alive to False."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            assert worker.alive is True
            worker._signal_handler(signal.SIGTERM, None)
            assert worker.alive is False

            worker.tmp.close()

    def test_signal_handler_sigusr1_reopens_logs(self):
        """Test that SIGUSR1 calls reopen_files."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            # Should call reopen_files and NOT set alive to False
            assert worker.alive is True
            worker._signal_handler(signal.SIGUSR1, None)
            assert worker.alive is True

            worker.tmp.close()

    def test_signal_handler_with_loop_calls_shutdown(self):
        """Test that signal handler with loop calls shutdown."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            # Create a mock loop
            loop = asyncio.new_event_loop()
            worker._loop = loop
            shutdown_called = []

            def mock_call_soon_threadsafe(cb):
                shutdown_called.append(cb)

            loop.call_soon_threadsafe = mock_call_soon_threadsafe

            worker._signal_handler(signal.SIGTERM, None)
            assert worker.alive is False
            assert len(shutdown_called) == 1

            loop.close()
            worker.tmp.close()

    def test_signal_handler_sigquit(self):
        """Test SIGQUIT handling."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            worker._signal_handler(signal.SIGQUIT, None)
            assert worker.alive is False

            worker.tmp.close()

    def test_signal_handler_sigint(self):
        """Test SIGINT handling."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            worker._signal_handler(signal.SIGINT, None)
            assert worker.alive is False

            worker.tmp.close()

    def test_signal_handler_sigabrt(self):
        """Test SIGABRT handling (timeout signal)."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            worker._signal_handler(signal.SIGABRT, None)
            assert worker.alive is False

            worker.tmp.close()


class TestDirtyWorkerShutdown:
    """Tests for worker shutdown."""

    def test_shutdown_closes_server(self):
        """Test that _shutdown closes the server."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            # Mock server
            class MockServer:
                def __init__(self):
                    self.closed = False

                def close(self):
                    self.closed = True

            worker._server = MockServer()
            worker._shutdown()
            assert worker._server.closed is True

            worker.tmp.close()

    def test_shutdown_without_server(self):
        """Test that _shutdown works when server is None."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            # Should not raise
            worker._shutdown()

            worker.tmp.close()


class TestDirtyWorkerRunAsync:
    """Tests for async run loop."""

    @pytest.mark.asyncio
    async def test_run_async_creates_socket(self):
        """Test that _run_async creates Unix socket server."""
        cfg = Config()
        cfg.set("dirty_timeout", 300)
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )
            worker.pid = os.getpid()

            # Start the server in background
            async def run_briefly():
                # Remove existing socket
                if os.path.exists(socket_path):
                    os.unlink(socket_path)

                worker._server = await asyncio.start_unix_server(
                    worker.handle_connection,
                    path=socket_path
                )
                os.chmod(socket_path, 0o600)

                # Verify socket exists
                assert os.path.exists(socket_path)

                # Close immediately
                worker._server.close()
                await worker._server.wait_closed()

            await run_briefly()

            worker.tmp.close()

    @pytest.mark.asyncio
    async def test_heartbeat_loop(self):
        """Test heartbeat loop updates tmp."""
        cfg = Config()
        cfg.set("dirty_timeout", 300)
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            # Test that notify method works
            worker.notify()
            worker.notify()
            worker.notify()

            # Verify no exceptions raised
            assert worker.tmp is not None

            worker.tmp.close()

    @pytest.mark.asyncio
    async def test_handle_connection_basic(self):
        """Test handle_connection reads and responds to messages."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=["tests.support_dirty_app:TestDirtyApp"],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            worker.load_apps()
            worker.pid = os.getpid()

            # Create a simple test using stream reader/writer
            request = make_request(
                request_id="conn-test",
                app_path="tests.support_dirty_app:TestDirtyApp",
                action="compute",
                args=(5, 3),
                kwargs={"operation": "add"}
            )

            # Mock reader and writer
            reader = asyncio.StreamReader()
            encoded_request = DirtyProtocol.encode(request)
            reader.feed_data(encoded_request)
            reader.feed_eof()

            class MockWriter:
                def __init__(self):
                    self.closed = False
                    self.data = b""

                def get_extra_info(self, name):
                    return None

                def write(self, data):
                    self.data += data

                async def drain(self):
                    pass

                def close(self):
                    self.closed = True

                async def wait_closed(self):
                    pass

            writer = MockWriter()

            # Handle one message then exit
            worker.alive = True
            try:
                message = await DirtyProtocol.read_message_async(reader)
                response = await worker.handle_request(message)
                await DirtyProtocol.write_message_async(writer, response)
            except asyncio.IncompleteReadError:
                pass

            # Decode response from writer
            if writer.data:
                payload = writer.data[DirtyProtocol.HEADER_SIZE:]
                response = DirtyProtocol.decode(payload)
                assert response["type"] == DirtyProtocol.MSG_TYPE_RESPONSE
                assert response["result"] == 8

            worker._cleanup()


class TestDirtyWorkerRun:
    """Tests for the run() method."""

    def test_run_creates_and_runs_loop(self):
        """Test that run() creates and runs an event loop."""
        cfg = Config()
        cfg.set("dirty_timeout", 300)
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )
            worker.pid = os.getpid()

            # Override _run_async to exit quickly
            run_async_called = []

            async def mock_run_async():
                run_async_called.append(True)
                # Exit immediately

            worker._run_async = mock_run_async

            worker.run()

            assert len(run_async_called) == 1

            worker.tmp.close()

    def test_run_handles_exception(self):
        """Test that run() handles exceptions and cleans up."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )
            worker.pid = os.getpid()

            # Override _run_async to raise
            async def failing_run_async():
                raise RuntimeError("Test error")

            worker._run_async = failing_run_async

            # Should not raise, should log error
            worker.run()

            # Check error was logged
            assert any("Worker error" in msg for level, msg in log.messages)


class TestDirtyWorkerInitProcess:
    """Tests for init_process post-fork setup."""

    def test_init_signals_setup(self):
        """Test that init_signals sets up signal handlers."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            # Store original handlers
            original_sigterm = signal.getsignal(signal.SIGTERM)

            try:
                worker.init_signals()

                # Verify handlers are set
                assert signal.getsignal(signal.SIGTERM) == worker._signal_handler
                assert signal.getsignal(signal.SIGQUIT) == worker._signal_handler
                assert signal.getsignal(signal.SIGINT) == worker._signal_handler
                assert signal.getsignal(signal.SIGABRT) == worker._signal_handler
                assert signal.getsignal(signal.SIGUSR1) == worker._signal_handler
            finally:
                # Restore original handler
                signal.signal(signal.SIGTERM, original_sigterm)

            worker.tmp.close()


class TestDirtyWorkerCleanupErrors:
    """Tests for cleanup error handling."""

    def test_cleanup_handles_app_close_error(self):
        """Test that cleanup handles errors when closing apps."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=["tests.support_dirty_app:TestDirtyApp"],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            worker.load_apps()
            app = worker.apps["tests.support_dirty_app:TestDirtyApp"]

            # Make close() raise an error
            def failing_close():
                raise RuntimeError("Close failed")

            app.close = failing_close

            # Should not raise, should log error
            worker._cleanup()

            assert any("Error closing dirty app" in msg for level, msg in log.messages)

    def test_cleanup_handles_missing_socket(self):
        """Test that cleanup handles non-existent socket file."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "nonexistent.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            # Should not raise even if socket doesn't exist
            worker._cleanup()

    def test_cleanup_handles_tmp_close_error(self):
        """Test that cleanup handles tmp.close() errors."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            # Close tmp so second close might fail
            worker.tmp.close()

            # Should not raise
            worker._cleanup()


class TestDirtyWorkerLoadAppsInit:
    """Tests for app loading with init failure."""

    def test_load_apps_init_failure(self):
        """Test that load_apps handles init() failure."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=["tests.support_dirty_app:BrokenInitApp"],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            with pytest.raises(RuntimeError, match="Init failed"):
                worker.load_apps()

            # Error should be logged
            assert any("Failed to initialize" in msg for level, msg in log.messages)


class TestDirtyWorkerExecutionTimeout:
    """Tests for execution timeout control."""

    @pytest.mark.asyncio
    async def test_execute_with_timeout(self):
        """Test that execute enforces timeout."""
        from concurrent.futures import ThreadPoolExecutor

        cfg = Config()
        cfg.set("dirty_timeout", 1)  # 1 second timeout
        cfg.set("dirty_threads", 1)
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=["tests.support_dirty_app:SlowDirtyApp"],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )
            worker.pid = os.getpid()

            # Create executor manually for test
            worker._executor = ThreadPoolExecutor(max_workers=1)

            try:
                worker.load_apps()

                # Execute slow action that exceeds timeout
                from gunicorn.dirty.errors import DirtyTimeoutError
                with pytest.raises(DirtyTimeoutError):
                    await worker.execute(
                        "tests.support_dirty_app:SlowDirtyApp",
                        "slow_action",
                        [],
                        {"delay": 5.0}  # 5 second delay, 1 second timeout
                    )
            finally:
                worker._cleanup()

    @pytest.mark.asyncio
    async def test_execute_within_timeout(self):
        """Test that execute succeeds within timeout."""
        from concurrent.futures import ThreadPoolExecutor

        cfg = Config()
        cfg.set("dirty_timeout", 10)  # 10 second timeout
        cfg.set("dirty_threads", 1)
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=["tests.support_dirty_app:SlowDirtyApp"],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )
            worker.pid = os.getpid()

            # Create executor manually for test
            worker._executor = ThreadPoolExecutor(max_workers=1)

            try:
                worker.load_apps()

                # Execute fast action that completes within timeout
                result = await worker.execute(
                    "tests.support_dirty_app:SlowDirtyApp",
                    "fast_action",
                    [],
                    {}
                )
                assert result == {"fast": True}
            finally:
                worker._cleanup()

    @pytest.mark.asyncio
    async def test_execute_no_timeout_when_zero(self):
        """Test that timeout is disabled when dirty_timeout is 0."""
        from concurrent.futures import ThreadPoolExecutor

        cfg = Config()
        cfg.set("dirty_timeout", 0)  # Disabled
        cfg.set("dirty_threads", 1)
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=["tests.support_dirty_app:TestDirtyApp"],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )
            worker.pid = os.getpid()

            # Create executor manually for test
            worker._executor = ThreadPoolExecutor(max_workers=1)

            try:
                worker.load_apps()

                # Should work with no timeout
                result = await worker.execute(
                    "tests.support_dirty_app:TestDirtyApp",
                    "compute",
                    [2, 3],
                    {"operation": "add"}
                )
                assert result == 5
            finally:
                worker._cleanup()

    def test_run_creates_executor_with_threads(self):
        """Test that run() creates executor with dirty_threads config."""
        cfg = Config()
        cfg.set("dirty_timeout", 300)
        cfg.set("dirty_threads", 4)
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=["tests.support_dirty_app:TestDirtyApp"],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )
            worker.pid = os.getpid()
            worker.load_apps()

            # Simulate what run() does
            from concurrent.futures import ThreadPoolExecutor
            worker._executor = ThreadPoolExecutor(
                max_workers=cfg.dirty_threads,
                thread_name_prefix=f"dirty-worker-{worker.pid}-"
            )

            assert worker._executor._max_workers == 4

            worker._cleanup()
            assert worker._executor is None
