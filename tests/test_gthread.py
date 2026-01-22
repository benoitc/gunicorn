#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for the gthread worker."""

import errno
import os
import queue
import selectors
import socket
import threading
import time
from collections import deque
from concurrent import futures
from functools import partial
from unittest import mock

import pytest

from gunicorn import http
from gunicorn.config import Config
from gunicorn.workers import gthread


class FakeSocket:
    """Mock socket for testing."""

    def __init__(self, data=b''):
        self.data = data
        self.closed = False
        self.blocking = True
        self._fileno = id(self) % 65536

    def fileno(self):
        return self._fileno

    def setblocking(self, blocking):
        self.blocking = blocking

    def recv(self, size):
        if self.closed:
            raise OSError(errno.EBADF, "Bad file descriptor")
        result = self.data[:size]
        self.data = self.data[size:]
        return result

    def send(self, data):
        if self.closed:
            raise OSError(errno.EPIPE, "Broken pipe")
        return len(data)

    def close(self):
        self.closed = True

    def getsockname(self):
        return ('127.0.0.1', 8000)

    def getpeername(self):
        return ('127.0.0.1', 12345)


class TestTConn:
    """Tests for TConn connection wrapper."""

    def test_tconn_init(self):
        """Test TConn initialization."""
        cfg = Config()
        sock = FakeSocket()
        client = ('127.0.0.1', 12345)
        server = ('127.0.0.1', 8000)

        conn = gthread.TConn(cfg, sock, client, server)

        assert conn.cfg is cfg
        assert conn.sock is sock
        assert conn.client == client
        assert conn.server == server
        assert conn.timeout is None
        assert conn.parser is None
        assert conn.initialized is False

    def test_tconn_init_sets_blocking_false(self):
        """Test that TConn sets socket to non-blocking initially."""
        cfg = Config()
        sock = FakeSocket()
        sock.setblocking(True)

        conn = gthread.TConn(cfg, sock, ('127.0.0.1', 12345), ('127.0.0.1', 8000))

        # TConn sets socket to non-blocking in __init__
        assert sock.blocking is False

    def test_tconn_init_method_sets_blocking_true(self):
        """Test that conn.init() sets socket back to blocking."""
        cfg = Config()
        sock = FakeSocket()

        conn = gthread.TConn(cfg, sock, ('127.0.0.1', 12345), ('127.0.0.1', 8000))
        conn.init()

        assert sock.blocking is True
        assert conn.initialized is True
        assert conn.parser is not None

    def test_tconn_set_timeout(self):
        """Test timeout setting using monotonic clock."""
        cfg = Config()
        cfg.set('keepalive', 5)
        sock = FakeSocket()

        conn = gthread.TConn(cfg, sock, ('127.0.0.1', 12345), ('127.0.0.1', 8000))
        before = time.monotonic()
        conn.set_timeout()
        after = time.monotonic()

        assert conn.timeout is not None
        assert before + 5 <= conn.timeout <= after + 5

    def test_tconn_close(self):
        """Test connection closing."""
        cfg = Config()
        sock = FakeSocket()

        conn = gthread.TConn(cfg, sock, ('127.0.0.1', 12345), ('127.0.0.1', 8000))
        conn.close()

        assert sock.closed is True


class TestThreadWorker:
    """Tests for ThreadWorker."""

    def create_worker(self, cfg=None):
        """Create a worker instance for testing."""
        if cfg is None:
            cfg = Config()
        cfg.set('workers', 1)
        cfg.set('threads', 4)
        cfg.set('worker_connections', 1000)
        cfg.set('keepalive', 2)

        # Mock the required attributes
        worker = gthread.ThreadWorker(
            age=1,
            ppid=os.getpid(),
            sockets=[],
            app=mock.Mock(),
            timeout=30,
            cfg=cfg,
            log=mock.Mock(),
        )
        return worker

    def test_worker_init(self):
        """Test worker initialization."""
        worker = self.create_worker()

        assert worker.worker_connections == 1000
        assert worker.max_keepalived == 1000 - 4  # connections - threads
        assert worker.tpool is None
        assert worker.poller is None
        assert worker._lock is None
        assert worker.nr_conns == 0

    def test_worker_check_config_warning(self):
        """Test that check_config warns when keepalive impossible."""
        cfg = Config()
        cfg.set('worker_connections', 4)
        cfg.set('threads', 4)
        cfg.set('keepalive', 2)
        log = mock.Mock()

        gthread.ThreadWorker.check_config(cfg, log)

        log.warning.assert_called()

    def test_worker_check_config_no_warning(self):
        """Test that check_config doesn't warn with valid config."""
        cfg = Config()
        cfg.set('worker_connections', 100)
        cfg.set('threads', 4)
        cfg.set('keepalive', 2)
        log = mock.Mock()

        gthread.ThreadWorker.check_config(cfg, log)

        log.warning.assert_not_called()

    def test_worker_init_process(self):
        """Test worker process initialization."""
        worker = self.create_worker()
        worker.tmp = mock.Mock()
        worker.log = mock.Mock()

        # Mock super().init_process() to avoid full initialization
        with mock.patch.object(gthread.base.Worker, 'init_process'):
            worker.init_process()

        assert worker.tpool is not None
        assert worker.poller is not None
        assert worker._lock is not None

        # Cleanup
        worker.tpool.shutdown(wait=False)
        worker.poller.close()

    def test_worker_get_thread_pool(self):
        """Test thread pool creation."""
        worker = self.create_worker()

        pool = worker.get_thread_pool()

        assert isinstance(pool, futures.ThreadPoolExecutor)
        pool.shutdown(wait=False)

    def test_worker_murder_keepalived(self):
        """Test that expired keepalive connections are cleaned up."""
        worker = self.create_worker()
        worker.poller = selectors.DefaultSelector()
        worker._lock = threading.RLock()

        # Create an expired connection (using monotonic to match implementation)
        cfg = Config()
        sock = FakeSocket()
        conn = gthread.TConn(cfg, sock, ('127.0.0.1', 12345), ('127.0.0.1', 8000))
        conn.timeout = time.monotonic() - 10  # Expired 10 seconds ago

        worker._keep.append(conn)
        worker.nr_conns = 1

        # Register with poller (so it can be unregistered)
        try:
            # Can't register FakeSocket with real selector, mock it
            with mock.patch.object(worker.poller, 'unregister'):
                worker.murder_keepalived()
        except (OSError, ValueError):
            pass  # Expected with fake socket

        # Connection should have been removed
        assert len(worker._keep) == 0
        assert sock.closed is True

        worker.poller.close()

    def test_worker_is_parent_alive(self):
        """Test parent process check."""
        worker = self.create_worker()

        # With correct ppid
        worker.ppid = os.getppid()
        assert worker.is_parent_alive() is True

        # With wrong ppid
        worker.ppid = -1
        assert worker.is_parent_alive() is False


class TestFinishRequest:
    """Tests for finish_request handling."""

    def create_worker(self):
        """Create a worker for testing."""
        cfg = Config()
        cfg.set('workers', 1)
        cfg.set('threads', 4)
        cfg.set('worker_connections', 1000)

        worker = gthread.ThreadWorker(
            age=1,
            ppid=os.getpid(),
            sockets=[],
            app=mock.Mock(),
            timeout=30,
            cfg=cfg,
            log=mock.Mock(),
        )
        worker._lock = threading.RLock()
        worker.poller = mock.Mock()
        worker.alive = True
        return worker

    def test_finish_request_cancelled(self):
        """Test handling of cancelled future."""
        worker = self.create_worker()
        worker.nr_conns = 1

        conn = mock.Mock()
        fs = mock.Mock()
        fs.cancelled.return_value = True
        fs.conn = conn

        worker.finish_request(fs)

        assert worker.nr_conns == 0
        conn.close.assert_called_once()

    def test_finish_request_keepalive(self):
        """Test handling of keepalive response."""
        worker = self.create_worker()
        worker.nr_conns = 1

        conn = mock.Mock()
        conn.sock = mock.Mock()
        fs = mock.Mock()
        fs.cancelled.return_value = False
        fs.result.return_value = (True, conn)  # keepalive=True
        fs.conn = conn

        worker.finish_request(fs)

        assert worker.nr_conns == 1  # Connection kept
        assert conn in worker._keep
        conn.set_timeout.assert_called_once()
        worker.poller.register.assert_called_once()

    def test_finish_request_close(self):
        """Test handling of non-keepalive response."""
        worker = self.create_worker()
        worker.nr_conns = 1

        conn = mock.Mock()
        fs = mock.Mock()
        fs.cancelled.return_value = False
        fs.result.return_value = (False, conn)  # keepalive=False
        fs.conn = conn

        worker.finish_request(fs)

        assert worker.nr_conns == 0
        conn.close.assert_called_once()

    def test_finish_request_exception(self):
        """Test handling of exception in request."""
        worker = self.create_worker()
        worker.nr_conns = 1

        conn = mock.Mock()
        fs = mock.Mock()
        fs.cancelled.return_value = False
        fs.result.side_effect = Exception("Test error")
        fs.conn = conn

        worker.finish_request(fs)

        assert worker.nr_conns == 0
        conn.close.assert_called_once()


class TestAccept:
    """Tests for connection acceptance."""

    def create_worker(self):
        """Create a worker for testing."""
        cfg = Config()
        cfg.set('workers', 1)
        cfg.set('threads', 4)
        cfg.set('worker_connections', 1000)

        worker = gthread.ThreadWorker(
            age=1,
            ppid=os.getpid(),
            sockets=[],
            app=mock.Mock(),
            timeout=30,
            cfg=cfg,
            log=mock.Mock(),
        )
        worker._lock = threading.RLock()
        worker.poller = mock.Mock()
        return worker

    def test_accept_success(self):
        """Test successful connection acceptance."""
        worker = self.create_worker()
        worker.nr_conns = 0

        client_sock = FakeSocket()
        client_addr = ('127.0.0.1', 12345)
        listener = mock.Mock()
        listener.accept.return_value = (client_sock, client_addr)
        server = ('127.0.0.1', 8000)

        worker.accept(server, listener)

        assert worker.nr_conns == 1
        worker.poller.register.assert_called_once()

    def test_accept_eagain(self):
        """Test handling of EAGAIN during accept."""
        worker = self.create_worker()
        worker.nr_conns = 0

        listener = mock.Mock()
        listener.accept.side_effect = OSError(errno.EAGAIN, "Try again")
        server = ('127.0.0.1', 8000)

        # Should not raise
        worker.accept(server, listener)

        assert worker.nr_conns == 0

    def test_accept_econnaborted(self):
        """Test handling of ECONNABORTED during accept."""
        worker = self.create_worker()
        worker.nr_conns = 0

        listener = mock.Mock()
        listener.accept.side_effect = OSError(errno.ECONNABORTED, "Connection aborted")
        server = ('127.0.0.1', 8000)

        # Should not raise
        worker.accept(server, listener)

        assert worker.nr_conns == 0
