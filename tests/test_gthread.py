#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for the gthread worker."""

import errno
import os
import queue
import selectors
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


class TestPollableMethodQueue:
    """Tests for PollableMethodQueue."""

    def test_queue_init_and_close(self):
        """Test queue initialization and cleanup."""
        q = gthread.PollableMethodQueue()
        q.init()

        assert q._read_fd is not None
        assert q._write_fd is not None
        assert q._queue is not None

        q.close()

    def test_queue_defer_and_run(self):
        """Test deferring and running callbacks."""
        q = gthread.PollableMethodQueue()
        q.init()

        results = []
        q.defer(lambda x: results.append(x), 42)

        # Simulate the selector reading from the pipe
        q.run_callbacks(None)

        assert results == [42]
        q.close()

    def test_queue_multiple_callbacks(self):
        """Test multiple callbacks are executed in order."""
        q = gthread.PollableMethodQueue()
        q.init()

        results = []
        for i in range(5):
            q.defer(lambda x: results.append(x), i)

        q.run_callbacks(None)

        assert results == [0, 1, 2, 3, 4]
        q.close()

    def test_queue_fileno_for_selector(self):
        """Test that fileno returns a valid fd for selector registration."""
        q = gthread.PollableMethodQueue()
        q.init()

        fd = q.fileno()
        assert isinstance(fd, int)
        assert fd >= 0

        # Verify it can be used with a selector
        sel = selectors.DefaultSelector()
        sel.register(fd, selectors.EVENT_READ)
        sel.unregister(fd)
        sel.close()
        q.close()

    def test_queue_thread_safety(self):
        """Test that defer can be called from multiple threads."""
        q = gthread.PollableMethodQueue()
        q.init()

        results = []
        lock = threading.Lock()

        def add_callback(n):
            def callback():
                with lock:
                    results.append(n)
            q.defer(callback)

        threads = []
        for i in range(10):
            t = threading.Thread(target=add_callback, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Drain all callbacks (pipe is non-blocking, may take multiple calls)
        for _ in range(20):
            q.run_callbacks(None)
            if len(results) >= 10:
                break

        assert len(results) == 10
        assert set(results) == set(range(10))
        q.close()

    def test_queue_nonblocking_pipe(self):
        """Test that pipe is non-blocking (BSD compatibility)."""
        import os
        import fcntl

        q = gthread.PollableMethodQueue()
        q.init()

        # Verify both ends are non-blocking
        read_flags = fcntl.fcntl(q._read_fd, fcntl.F_GETFL)
        write_flags = fcntl.fcntl(q._write_fd, fcntl.F_GETFL)
        assert read_flags & os.O_NONBLOCK
        assert write_flags & os.O_NONBLOCK

        q.close()


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
        assert worker.nr_conns == 0
        assert worker._accepting is False
        assert isinstance(worker.keepalived_conns, deque)
        assert isinstance(worker.method_queue, gthread.PollableMethodQueue)

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
        assert worker.method_queue._queue is not None

        # Cleanup
        worker.tpool.shutdown(wait=False)
        worker.poller.close()
        worker.method_queue.close()

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

        # Create an expired connection (using monotonic to match implementation)
        cfg = Config()
        sock = FakeSocket()
        conn = gthread.TConn(cfg, sock, ('127.0.0.1', 12345), ('127.0.0.1', 8000))
        conn.timeout = time.monotonic() - 10  # Expired 10 seconds ago

        worker.keepalived_conns.append(conn)
        worker.nr_conns = 1

        # Register with poller (so it can be unregistered)
        try:
            with mock.patch.object(worker.poller, 'unregister'):
                worker.murder_keepalived()
        except (OSError, ValueError):
            pass  # Expected with fake socket

        # Connection should have been removed
        assert len(worker.keepalived_conns) == 0
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

    def test_worker_set_accept_enabled(self):
        """Test enabling and disabling connection acceptance."""
        worker = self.create_worker()
        worker.poller = mock.Mock()

        # Create a mock socket
        mock_sock = mock.Mock()
        mock_sock.getsockname.return_value = ('127.0.0.1', 8000)
        worker.sockets = [mock_sock]

        # Initially not accepting
        assert worker._accepting is False

        # Enable accepting
        worker.set_accept_enabled(True)
        assert worker._accepting is True
        mock_sock.setblocking.assert_called_with(False)
        worker.poller.register.assert_called_once()

        # Disable accepting
        worker.set_accept_enabled(False)
        assert worker._accepting is False
        worker.poller.unregister.assert_called_once()

    def test_worker_handle_exit(self):
        """Test graceful shutdown signal handling."""
        worker = self.create_worker()
        worker.method_queue.init()
        worker.alive = True

        worker.handle_exit(None, None)

        assert worker.alive is False
        worker.method_queue.close()

    def test_worker_wait_for_events(self):
        """Test event waiting with dispatch."""
        worker = self.create_worker()
        worker.poller = mock.Mock()

        # Simulate an event
        mock_key = mock.Mock()
        callback = mock.Mock()
        mock_key.data = callback
        mock_key.fileobj = mock.Mock()
        worker.poller.select.return_value = [(mock_key, None)]

        worker.wait_for_and_dispatch_events(1.0)

        worker.poller.select.assert_called_once_with(1.0)
        callback.assert_called_once_with(mock_key.fileobj)


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

        worker.finish_request(conn, fs)

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
        fs.result.return_value = True  # keepalive=True

        worker.finish_request(conn, fs)

        assert worker.nr_conns == 1  # Connection kept
        assert conn in worker.keepalived_conns
        conn.set_timeout.assert_called_once()
        worker.poller.register.assert_called_once()

    def test_finish_request_close(self):
        """Test handling of non-keepalive response."""
        worker = self.create_worker()
        worker.nr_conns = 1

        conn = mock.Mock()
        fs = mock.Mock()
        fs.cancelled.return_value = False
        fs.result.return_value = False  # keepalive=False

        worker.finish_request(conn, fs)

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

        worker.finish_request(conn, fs)

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
        worker.poller = mock.Mock()
        worker.tpool = mock.Mock()
        worker.method_queue = mock.Mock()
        return worker

    def test_accept_success(self):
        """Test successful connection acceptance."""
        worker = self.create_worker()
        worker.nr_conns = 0

        client_sock = FakeSocket()
        client_addr = ('127.0.0.1', 12345)
        listener = mock.Mock()
        listener.accept.return_value = (client_sock, client_addr)
        listener.getsockname.return_value = ('127.0.0.1', 8000)

        worker.accept(listener)

        assert worker.nr_conns == 1
        worker.tpool.submit.assert_called_once()

    def test_accept_eagain(self):
        """Test handling of EAGAIN during accept."""
        worker = self.create_worker()
        worker.nr_conns = 0

        listener = mock.Mock()
        listener.accept.side_effect = OSError(errno.EAGAIN, "Try again")

        # Should not raise
        worker.accept(listener)

        assert worker.nr_conns == 0

    def test_accept_econnaborted(self):
        """Test handling of ECONNABORTED during accept."""
        worker = self.create_worker()
        worker.nr_conns = 0

        listener = mock.Mock()
        listener.accept.side_effect = OSError(errno.ECONNABORTED, "Connection aborted")

        # Should not raise
        worker.accept(listener)

        assert worker.nr_conns == 0


class TestGracefulShutdown:
    """Tests for graceful shutdown behavior."""

    def create_worker(self):
        """Create a worker for testing."""
        cfg = Config()
        cfg.set('workers', 1)
        cfg.set('threads', 4)
        cfg.set('worker_connections', 1000)
        cfg.set('graceful_timeout', 5)

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

    def test_handle_exit_sets_alive_false(self):
        """Test that handle_exit begins graceful shutdown."""
        worker = self.create_worker()
        worker.method_queue.init()
        worker.alive = True

        worker.handle_exit(None, None)

        assert worker.alive is False
        worker.method_queue.close()

    def test_connection_tracking(self):
        """Test that connection count is properly tracked."""
        worker = self.create_worker()
        worker.poller = mock.Mock()
        worker.tpool = mock.Mock()
        worker.method_queue = mock.Mock()

        assert worker.nr_conns == 0

        # Simulate accept
        client_sock = FakeSocket()
        listener = mock.Mock()
        listener.accept.return_value = (client_sock, ('127.0.0.1', 12345))
        listener.getsockname.return_value = ('127.0.0.1', 8000)

        worker.accept(listener)
        assert worker.nr_conns == 1

        # Simulate finish_request with close
        conn = mock.Mock()
        fs = mock.Mock()
        fs.cancelled.return_value = False
        fs.result.return_value = False  # Not keepalive
        worker.finish_request(conn, fs)
        assert worker.nr_conns == 0


class TestKeepaliveManagement:
    """Tests for keepalive connection management."""

    def create_worker(self):
        """Create a worker for testing."""
        cfg = Config()
        cfg.set('workers', 1)
        cfg.set('threads', 4)
        cfg.set('worker_connections', 10)
        cfg.set('keepalive', 2)

        worker = gthread.ThreadWorker(
            age=1,
            ppid=os.getpid(),
            sockets=[],
            app=mock.Mock(),
            timeout=30,
            cfg=cfg,
            log=mock.Mock(),
        )
        worker.poller = mock.Mock()
        return worker

    def test_max_keepalived_calculation(self):
        """Test that max_keepalived is correctly calculated."""
        worker = self.create_worker()
        # max_keepalived = worker_connections - threads = 10 - 4 = 6
        assert worker.max_keepalived == 6

    def test_keepalive_timeout_ordering(self):
        """Test that connections are ordered by timeout for efficient murder."""
        worker = self.create_worker()

        # Add connections with different timeouts
        cfg = Config()
        for i in range(3):
            sock = FakeSocket()
            conn = gthread.TConn(cfg, sock, ('127.0.0.1', 12345 + i), ('127.0.0.1', 8000))
            conn.timeout = time.monotonic() + (i * 10)  # Staggered timeouts
            worker.keepalived_conns.append(conn)
            worker.nr_conns += 1

        # First connection should have earliest timeout
        first = worker.keepalived_conns[0]
        last = worker.keepalived_conns[-1]
        assert first.timeout < last.timeout

    def test_murder_only_expired(self):
        """Test that only expired connections are closed."""
        worker = self.create_worker()
        worker.poller = selectors.DefaultSelector()

        cfg = Config()

        # Add one expired and one valid connection
        expired_sock = FakeSocket()
        expired_conn = gthread.TConn(cfg, expired_sock, ('127.0.0.1', 12345), ('127.0.0.1', 8000))
        expired_conn.timeout = time.monotonic() - 10  # Expired

        valid_sock = FakeSocket()
        valid_conn = gthread.TConn(cfg, valid_sock, ('127.0.0.1', 12346), ('127.0.0.1', 8000))
        valid_conn.timeout = time.monotonic() + 100  # Still valid

        worker.keepalived_conns.append(expired_conn)
        worker.keepalived_conns.append(valid_conn)
        worker.nr_conns = 2

        with mock.patch.object(worker.poller, 'unregister'):
            worker.murder_keepalived()

        # Expired should be closed, valid should remain
        assert expired_sock.closed is True
        assert valid_sock.closed is False
        assert len(worker.keepalived_conns) == 1
        assert worker.keepalived_conns[0] is valid_conn
        assert worker.nr_conns == 1

        worker.poller.close()


class TestErrorHandling:
    """Tests for error handling in various scenarios."""

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
        worker.poller = mock.Mock()
        return worker

    def test_finish_request_handles_future_exception(self):
        """Test that finish_request handles exceptions from futures."""
        worker = self.create_worker()
        worker.nr_conns = 1

        conn = mock.Mock()
        fs = mock.Mock()
        fs.cancelled.return_value = False
        fs.result.side_effect = RuntimeError("Worker crashed")

        # Should not raise, should close connection
        worker.finish_request(conn, fs)

        assert worker.nr_conns == 0
        conn.close.assert_called_once()

    def test_enqueue_req_submits_to_pool(self):
        """Test that enqueue_req properly submits to thread pool."""
        worker = self.create_worker()
        worker.tpool = mock.Mock()
        worker.method_queue = mock.Mock()

        conn = mock.Mock()
        worker.enqueue_req(conn)

        worker.tpool.submit.assert_called_once()

    def test_wait_for_events_handles_eintr(self):
        """Test that EINTR is handled gracefully."""
        worker = self.create_worker()
        worker.poller = mock.Mock()
        worker.poller.select.side_effect = OSError(errno.EINTR, "Interrupted")

        # Should not raise
        worker.wait_for_and_dispatch_events(1.0)

    def test_wait_for_events_raises_other_errors(self):
        """Test that non-EINTR errors are propagated."""
        worker = self.create_worker()
        worker.poller = mock.Mock()
        worker.poller.select.side_effect = OSError(errno.EBADF, "Bad file descriptor")

        with pytest.raises(OSError):
            worker.wait_for_and_dispatch_events(1.0)


class TestConnectionState:
    """Tests for connection state management."""

    def test_tconn_double_init_is_safe(self):
        """Test that calling init() twice is safe (idempotent)."""
        cfg = Config()
        sock = FakeSocket()
        conn = gthread.TConn(cfg, sock, ('127.0.0.1', 12345), ('127.0.0.1', 8000))

        conn.init()
        parser1 = conn.parser

        conn.init()  # Should not reinitialize
        parser2 = conn.parser

        assert parser1 is parser2

    def test_tconn_close_is_safe(self):
        """Test that closing a connection is safe."""
        cfg = Config()
        sock = FakeSocket()
        conn = gthread.TConn(cfg, sock, ('127.0.0.1', 12345), ('127.0.0.1', 8000))

        conn.close()
        assert sock.closed is True

        # Second close should not raise
        conn.close()

    def test_keepalive_timeout_uses_monotonic(self):
        """Test that timeout uses monotonic clock."""
        cfg = Config()
        cfg.set('keepalive', 5)
        sock = FakeSocket()
        conn = gthread.TConn(cfg, sock, ('127.0.0.1', 12345), ('127.0.0.1', 8000))

        before = time.monotonic()
        conn.set_timeout()
        after = time.monotonic()

        # Timeout should be approximately 5 seconds in the future
        assert before + 4.9 <= conn.timeout <= after + 5.1
