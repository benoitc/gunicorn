#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for control socket server."""

import os
import tempfile
import time
from unittest.mock import MagicMock

import pytest

from gunicorn.ctl.server import ControlSocketServer
from gunicorn.ctl.client import ControlClient


class MockWorker:
    """Mock worker for testing."""

    def __init__(self, pid, age, booted=True, aborted=False):
        self.pid = pid
        self.age = age
        self.booted = booted
        self.aborted = aborted
        self.tmp = MagicMock()
        self.tmp.last_update.return_value = time.monotonic()


class MockConfig:
    """Mock config for testing."""

    def __init__(self):
        self.bind = ['127.0.0.1:8000']
        self.workers = 4
        self.worker_class = 'sync'
        self.threads = 1
        self.timeout = 30
        self.graceful_timeout = 30
        self.keepalive = 2
        self.max_requests = 0
        self.max_requests_jitter = 0
        self.worker_connections = 1000
        self.preload_app = False
        self.daemon = False
        self.pidfile = None
        self.proc_name = 'test_app'
        self.reload = False
        self.dirty_workers = 0
        self.dirty_apps = []
        self.dirty_timeout = 30
        self.control_socket = 'gunicorn.ctl'
        self.control_socket_disable = False


class MockLog:
    """Mock logger for testing."""

    def debug(self, msg, *args):
        pass

    def info(self, msg, *args):
        pass

    def warning(self, msg, *args):
        pass

    def error(self, msg, *args):
        pass

    def exception(self, msg, *args):
        pass


class MockArbiter:
    """Mock arbiter for testing."""

    def __init__(self):
        self.cfg = MockConfig()
        self.log = MockLog()
        self.pid = 12345
        self.WORKERS = {}
        self.LISTENERS = []
        self.dirty_arbiter_pid = 0
        self.dirty_arbiter = None
        self.num_workers = 4
        self._stats = {
            'start_time': time.time() - 3600,
            'workers_spawned': 10,
            'workers_killed': 5,
            'reloads': 2,
        }

    def wakeup(self):
        pass


class TestControlSocketServerInit:
    """Tests for server initialization."""

    def test_init(self):
        """Test server initialization."""
        arbiter = MockArbiter()
        server = ControlSocketServer(arbiter, "/tmp/test.sock", 0o600)

        assert server.arbiter is arbiter
        assert server.socket_path == "/tmp/test.sock"
        assert server.socket_mode == 0o600
        assert server._running is False


class TestControlSocketServerLifecycle:
    """Tests for server start/stop."""

    def test_start_stop(self):
        """Test starting and stopping the server."""
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "test.sock")

            arbiter = MockArbiter()
            server = ControlSocketServer(arbiter, socket_path)

            server.start()

            # Wait for server to start
            for _ in range(50):
                if os.path.exists(socket_path):
                    break
                time.sleep(0.1)
            time.sleep(0.2)  # Extra wait for server to be fully ready

            assert os.path.exists(socket_path)

            server.stop()

            # Wait for cleanup
            time.sleep(0.2)

            # Socket should be cleaned up
            assert not os.path.exists(socket_path)

    def test_start_already_running(self):
        """Test that start is idempotent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "test.sock")

            arbiter = MockArbiter()
            server = ControlSocketServer(arbiter, socket_path)

            server.start()
            first_thread = server._thread
            server.start()

            assert server._thread is first_thread

            server.stop()

    def test_stop_not_running(self):
        """Test stopping a non-running server."""
        arbiter = MockArbiter()
        server = ControlSocketServer(arbiter, "/tmp/test.sock")

        # Should not raise
        server.stop()


class TestControlSocketServerIntegration:
    """Integration tests for server with client."""

    def test_show_workers(self):
        """Test show workers command."""
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "test.sock")

            arbiter = MockArbiter()
            arbiter.WORKERS = {
                1001: MockWorker(1001, 1),
                1002: MockWorker(1002, 2),
            }
            server = ControlSocketServer(arbiter, socket_path)

            server.start()

            # Wait for server to start
            for _ in range(50):
                if os.path.exists(socket_path):
                    break
                time.sleep(0.1)
            time.sleep(0.2)  # Extra wait for server to be fully ready

            try:
                with ControlClient(socket_path, timeout=5.0) as client:
                    result = client.send_command("show workers")

                assert result["count"] == 2
                assert len(result["workers"]) == 2
            finally:
                server.stop()

    def test_show_stats(self):
        """Test show stats command."""
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "test.sock")

            arbiter = MockArbiter()
            server = ControlSocketServer(arbiter, socket_path)

            server.start()

            for _ in range(50):
                if os.path.exists(socket_path):
                    break
                time.sleep(0.1)
            time.sleep(0.2)  # Extra wait for server to be fully ready

            try:
                with ControlClient(socket_path, timeout=5.0) as client:
                    result = client.send_command("show stats")

                assert result["pid"] == 12345
                assert result["workers_spawned"] == 10
            finally:
                server.stop()

    def test_help_command(self):
        """Test help command."""
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "test.sock")

            arbiter = MockArbiter()
            server = ControlSocketServer(arbiter, socket_path)

            server.start()

            for _ in range(50):
                if os.path.exists(socket_path):
                    break
                time.sleep(0.1)
            time.sleep(0.2)  # Extra wait for server to be fully ready

            try:
                with ControlClient(socket_path, timeout=5.0) as client:
                    result = client.send_command("help")

                assert "commands" in result
                assert "show workers" in result["commands"]
            finally:
                server.stop()

    def test_worker_add(self):
        """Test worker add command."""
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "test.sock")

            arbiter = MockArbiter()
            arbiter.wakeup = MagicMock()
            server = ControlSocketServer(arbiter, socket_path)

            server.start()

            for _ in range(50):
                if os.path.exists(socket_path):
                    break
                time.sleep(0.1)
            time.sleep(0.2)  # Extra wait for server to be fully ready

            try:
                with ControlClient(socket_path, timeout=5.0) as client:
                    result = client.send_command("worker add 2")

                assert result["added"] == 2
                assert result["total"] == 6
                assert arbiter.num_workers == 6
                arbiter.wakeup.assert_called()
            finally:
                server.stop()

    def test_invalid_command(self):
        """Test handling invalid command."""
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "test.sock")

            arbiter = MockArbiter()
            server = ControlSocketServer(arbiter, socket_path)

            server.start()

            for _ in range(50):
                if os.path.exists(socket_path):
                    break
                time.sleep(0.1)
            time.sleep(0.2)  # Extra wait for server to be fully ready

            try:
                with ControlClient(socket_path, timeout=5.0) as client:
                    with pytest.raises(Exception) as exc_info:
                        client.send_command("invalid_command")

                    assert "Unknown command" in str(exc_info.value)
            finally:
                server.stop()

    def test_multiple_commands(self):
        """Test sending multiple commands on same connection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "test.sock")

            arbiter = MockArbiter()
            arbiter.WORKERS = {1001: MockWorker(1001, 1)}
            server = ControlSocketServer(arbiter, socket_path)

            server.start()

            for _ in range(50):
                if os.path.exists(socket_path):
                    break
                time.sleep(0.1)
            time.sleep(0.2)  # Extra wait for server to be fully ready

            try:
                with ControlClient(socket_path, timeout=5.0) as client:
                    result1 = client.send_command("show workers")
                    result2 = client.send_command("show stats")
                    result3 = client.send_command("help")

                assert result1["count"] == 1
                assert result2["pid"] == 12345
                assert "commands" in result3
            finally:
                server.stop()


class TestControlSocketServerPermissions:
    """Tests for socket permissions."""

    @pytest.mark.skipif(
        os.uname().sysname == "FreeBSD",
        reason="FreeBSD socket permissions behavior differs"
    )
    def test_socket_permissions(self):
        """Test that socket is created with correct permissions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "test.sock")

            arbiter = MockArbiter()
            server = ControlSocketServer(arbiter, socket_path, 0o660)

            server.start()

            # Wait for socket to exist
            for _ in range(50):
                if os.path.exists(socket_path):
                    break
                time.sleep(0.1)

            # Extra wait for chmod to complete
            time.sleep(0.2)

            try:
                mode = os.stat(socket_path).st_mode & 0o777
                assert mode == 0o660
            finally:
                server.stop()
