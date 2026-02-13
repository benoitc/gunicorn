#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for control socket command handlers."""

import signal
import time
from unittest.mock import MagicMock, patch

import pytest

from gunicorn.ctl.handlers import CommandHandlers


class MockWorker:
    """Mock worker for testing."""

    def __init__(self, pid, age, booted=True, aborted=False):
        self.pid = pid
        self.age = age
        self.booted = booted
        self.aborted = aborted
        self.tmp = MagicMock()
        self.tmp.last_update.return_value = time.monotonic()


class MockListener:
    """Mock listener for testing."""

    def __init__(self, address, fd=3):
        self._address = address
        self._fd = fd
        self.sock = MagicMock()
        self.sock.family = 2  # AF_INET

    def __str__(self):
        return self._address

    def fileno(self):
        return self._fd


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


class MockArbiter:
    """Mock arbiter for testing."""

    def __init__(self):
        self.cfg = MockConfig()
        self.pid = 12345
        self.WORKERS = {}
        self.LISTENERS = []
        self.dirty_arbiter_pid = 0
        self.dirty_arbiter = None
        self.num_workers = 4
        self._stats = {
            'start_time': time.time() - 3600,  # 1 hour ago
            'workers_spawned': 10,
            'workers_killed': 5,
            'reloads': 2,
        }

    def wakeup(self):
        pass


class TestShowWorkers:
    """Tests for show workers command."""

    def test_show_workers_empty(self):
        """Test showing workers when none exist."""
        arbiter = MockArbiter()
        handlers = CommandHandlers(arbiter)

        result = handlers.show_workers()

        assert result["workers"] == []
        assert result["count"] == 0

    def test_show_workers_with_workers(self):
        """Test showing workers."""
        arbiter = MockArbiter()
        arbiter.WORKERS = {
            1001: MockWorker(1001, 1),
            1002: MockWorker(1002, 2),
            1003: MockWorker(1003, 3),
        }
        handlers = CommandHandlers(arbiter)

        result = handlers.show_workers()

        assert result["count"] == 3
        assert len(result["workers"]) == 3

        # Verify sorted by age
        ages = [w["age"] for w in result["workers"]]
        assert ages == sorted(ages)

        # Verify worker data
        worker = result["workers"][0]
        assert "pid" in worker
        assert "age" in worker
        assert "booted" in worker
        assert "last_heartbeat" in worker


class TestShowStats:
    """Tests for show stats command."""

    def test_show_stats(self):
        """Test showing stats."""
        arbiter = MockArbiter()
        arbiter.WORKERS = {
            1001: MockWorker(1001, 1),
            1002: MockWorker(1002, 2),
        }
        handlers = CommandHandlers(arbiter)

        result = handlers.show_stats()

        assert result["pid"] == 12345
        assert result["workers_current"] == 2
        assert result["workers_target"] == 4
        assert result["workers_spawned"] == 10
        assert result["workers_killed"] == 5
        assert result["reloads"] == 2
        assert result["uptime"] is not None
        assert result["uptime"] > 0


class TestShowConfig:
    """Tests for show config command."""

    def test_show_config(self):
        """Test showing config."""
        arbiter = MockArbiter()
        handlers = CommandHandlers(arbiter)

        result = handlers.show_config()

        assert result["workers"] == 4
        assert result["timeout"] == 30
        assert result["bind"] == ['127.0.0.1:8000']


class TestShowListeners:
    """Tests for show listeners command."""

    def test_show_listeners_empty(self):
        """Test showing listeners when none exist."""
        arbiter = MockArbiter()
        handlers = CommandHandlers(arbiter)

        result = handlers.show_listeners()

        assert result["listeners"] == []
        assert result["count"] == 0

    def test_show_listeners(self):
        """Test showing listeners."""
        arbiter = MockArbiter()
        arbiter.LISTENERS = [
            MockListener("127.0.0.1:8000", fd=3),
            MockListener("127.0.0.1:8001", fd=4),
        ]
        handlers = CommandHandlers(arbiter)

        result = handlers.show_listeners()

        assert result["count"] == 2
        assert len(result["listeners"]) == 2
        assert result["listeners"][0]["address"] == "127.0.0.1:8000"


class TestWorkerAdd:
    """Tests for worker add command."""

    def test_worker_add_default(self):
        """Test adding one worker (default)."""
        arbiter = MockArbiter()
        arbiter.wakeup = MagicMock()
        handlers = CommandHandlers(arbiter)

        result = handlers.worker_add()

        assert result["added"] == 1
        assert result["previous"] == 4
        assert result["total"] == 5
        assert arbiter.num_workers == 5
        arbiter.wakeup.assert_called_once()

    def test_worker_add_multiple(self):
        """Test adding multiple workers."""
        arbiter = MockArbiter()
        arbiter.wakeup = MagicMock()
        handlers = CommandHandlers(arbiter)

        result = handlers.worker_add(3)

        assert result["added"] == 3
        assert result["total"] == 7


class TestWorkerRemove:
    """Tests for worker remove command."""

    def test_worker_remove_default(self):
        """Test removing one worker (default)."""
        arbiter = MockArbiter()
        arbiter.wakeup = MagicMock()
        handlers = CommandHandlers(arbiter)

        result = handlers.worker_remove()

        assert result["removed"] == 1
        assert result["previous"] == 4
        assert result["total"] == 3
        assert arbiter.num_workers == 3
        arbiter.wakeup.assert_called_once()

    def test_worker_remove_cannot_go_below_one(self):
        """Test that worker count cannot go below 1."""
        arbiter = MockArbiter()
        arbiter.num_workers = 2
        arbiter.wakeup = MagicMock()
        handlers = CommandHandlers(arbiter)

        result = handlers.worker_remove(5)

        assert result["removed"] == 1
        assert result["total"] == 1
        assert arbiter.num_workers == 1


class TestWorkerKill:
    """Tests for worker kill command."""

    def test_worker_kill_success(self):
        """Test killing a worker."""
        arbiter = MockArbiter()
        arbiter.WORKERS = {1001: MockWorker(1001, 1)}
        handlers = CommandHandlers(arbiter)

        with patch('os.kill') as mock_kill:
            result = handlers.worker_kill(1001)

        assert result["success"] is True
        assert result["killed"] == 1001
        mock_kill.assert_called_once_with(1001, signal.SIGTERM)

    def test_worker_kill_not_found(self):
        """Test killing a non-existent worker."""
        arbiter = MockArbiter()
        handlers = CommandHandlers(arbiter)

        result = handlers.worker_kill(9999)

        assert result["success"] is False
        assert "not found" in result["error"]


class TestShowDirty:
    """Tests for show dirty command."""

    def test_show_dirty_disabled(self):
        """Test showing dirty when disabled."""
        arbiter = MockArbiter()
        handlers = CommandHandlers(arbiter)

        result = handlers.show_dirty()

        assert result["enabled"] is False
        assert result["pid"] is None


class TestReload:
    """Tests for reload command."""

    def test_reload(self):
        """Test reload command."""
        arbiter = MockArbiter()
        handlers = CommandHandlers(arbiter)

        with patch('os.kill') as mock_kill:
            result = handlers.reload()

        assert result["status"] == "reloading"
        mock_kill.assert_called_once_with(12345, signal.SIGHUP)


class TestReopen:
    """Tests for reopen command."""

    def test_reopen(self):
        """Test reopen command."""
        arbiter = MockArbiter()
        handlers = CommandHandlers(arbiter)

        with patch('os.kill') as mock_kill:
            result = handlers.reopen()

        assert result["status"] == "reopening"
        mock_kill.assert_called_once_with(12345, signal.SIGUSR1)


class TestShutdown:
    """Tests for shutdown command."""

    def test_shutdown_graceful(self):
        """Test graceful shutdown."""
        arbiter = MockArbiter()
        handlers = CommandHandlers(arbiter)

        with patch('os.kill') as mock_kill:
            result = handlers.shutdown()

        assert result["status"] == "shutting_down"
        assert result["mode"] == "graceful"
        mock_kill.assert_called_once_with(12345, signal.SIGTERM)

    def test_shutdown_quick(self):
        """Test quick shutdown."""
        arbiter = MockArbiter()
        handlers = CommandHandlers(arbiter)

        with patch('os.kill') as mock_kill:
            result = handlers.shutdown("quick")

        assert result["status"] == "shutting_down"
        assert result["mode"] == "quick"
        mock_kill.assert_called_once_with(12345, signal.SIGINT)


class TestShowAll:
    """Tests for show all command."""

    def test_show_all_basic(self):
        """Test show all command."""
        arbiter = MockArbiter()
        arbiter.WORKERS = {
            1001: MockWorker(1001, 1),
            1002: MockWorker(1002, 2),
        }
        handlers = CommandHandlers(arbiter)

        result = handlers.show_all()

        assert "arbiter" in result
        assert result["arbiter"]["pid"] == 12345
        assert result["arbiter"]["type"] == "arbiter"

        assert "web_workers" in result
        assert result["web_worker_count"] == 2
        assert len(result["web_workers"]) == 2

        assert "dirty_arbiter" in result
        assert result["dirty_arbiter"] is None

        # No dirty workers when no dirty arbiter
        assert result["dirty_worker_count"] == 0

    def test_show_all_with_dirty(self):
        """Test show all with dirty arbiter running."""
        arbiter = MockArbiter()
        arbiter.dirty_arbiter_pid = 2000
        handlers = CommandHandlers(arbiter)

        result = handlers.show_all()

        assert result["dirty_arbiter"] is not None
        assert result["dirty_arbiter"]["pid"] == 2000
        assert result["dirty_arbiter"]["type"] == "dirty_arbiter"


class TestHelp:
    """Tests for help command."""

    def test_help(self):
        """Test help command."""
        arbiter = MockArbiter()
        handlers = CommandHandlers(arbiter)

        result = handlers.help()

        assert "commands" in result
        commands = result["commands"]
        assert "show all" in commands
        assert "show workers" in commands
        assert "worker add [N]" in commands
        assert "reload" in commands
        assert "shutdown [graceful|quick]" in commands
