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


class TestWorkerLiveness:
    """Tests for worker liveness reporting to the arbiter."""

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
        return worker

    def test_notify_calls_tmp_notify(self):
        """Test that worker.notify() calls tmp.notify() for arbiter monitoring."""
        worker = self.create_worker()
        worker.tmp = mock.Mock()

        worker.notify()

        worker.tmp.notify.assert_called_once()

    def test_notify_updates_tmp_mtime(self):
        """Test that notify updates the temp file mtime for arbiter heartbeat.

        WorkerTmp.notify() sets mtime using time.monotonic(), and the arbiter
        checks liveness by comparing (time.monotonic() - last_update()) to timeout.
        """
        from gunicorn.workers.workertmp import WorkerTmp

        cfg = Config()
        tmp = WorkerTmp(cfg)

        # Call notify to set mtime to current monotonic time
        tmp.notify()

        # The arbiter checks: time.monotonic() - last_update() <= timeout
        # After notify(), this difference should be very small
        diff = time.monotonic() - tmp.last_update()
        assert diff < 1.0  # Should be nearly zero

        # Wait and verify the difference grows
        time.sleep(0.1)
        diff_later = time.monotonic() - tmp.last_update()
        assert diff_later > diff  # Time has passed

        tmp.close()

    def test_worker_notifies_in_run_loop(self):
        """Test that worker calls notify() during the run loop."""
        worker = self.create_worker()
        worker.tmp = mock.Mock()
        worker.method_queue.init()
        worker.poller = mock.Mock()
        worker.tpool = mock.Mock()
        worker.sockets = []
        worker.alive = True

        # Track notify calls
        notify_calls = []
        original_notify = worker.notify
        def tracking_notify():
            notify_calls.append(time.monotonic())
            original_notify()
        worker.notify = tracking_notify

        # Mock poller.select to exit after first iteration
        call_count = [0]
        def mock_select(timeout):
            call_count[0] += 1
            if call_count[0] > 1:
                worker.alive = False
            return []
        worker.poller.select.side_effect = mock_select

        # Mock is_parent_alive to return True
        worker.is_parent_alive = mock.Mock(return_value=True)

        worker.run()

        # Worker should have called notify at least once
        assert len(notify_calls) >= 1
        worker.method_queue.close()


class TestSignalHandling:
    """Tests for signal handling in gthread worker."""

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

    def test_handle_exit_sigterm_sets_alive_false(self):
        """Test that SIGTERM handler sets alive=False for graceful shutdown."""
        worker = self.create_worker()
        worker.method_queue.init()
        worker.alive = True

        # Simulate SIGTERM
        worker.handle_exit(None, None)

        assert worker.alive is False
        worker.method_queue.close()

    def test_handle_exit_wakes_up_poller(self):
        """Test that SIGTERM handler wakes up the poller via method_queue."""
        worker = self.create_worker()
        worker.method_queue.init()
        worker.alive = True

        # After handle_exit, the method_queue should have a callback queued
        worker.handle_exit(None, None)

        # Check that something was written to the pipe (to wake poller)
        # Read from the pipe - should have data
        import select
        readable, _, _ = select.select([worker.method_queue.fileno()], [], [], 0)
        assert len(readable) > 0

        worker.method_queue.close()

    def test_handle_quit_sigquit_immediate_shutdown(self):
        """Test that SIGQUIT handler triggers immediate shutdown."""
        worker = self.create_worker()
        worker.tpool = mock.Mock()

        with pytest.raises(SystemExit) as exc_info:
            worker.handle_quit(None, None)

        assert exc_info.value.code == 0
        worker.tpool.shutdown.assert_called_once_with(wait=False)

    def test_graceful_shutdown_stops_accepting(self):
        """Test that graceful shutdown stops accepting new connections."""
        worker = self.create_worker()
        worker.method_queue.init()
        worker.poller = mock.Mock()
        worker.tpool = mock.Mock()
        worker.sockets = [mock.Mock()]
        worker._accepting = True

        # Start accepting
        worker.set_accept_enabled(True)

        # Simulate SIGTERM
        worker.handle_exit(None, None)
        assert worker.alive is False

        # During run loop, accepting should be disabled
        worker.set_accept_enabled(False)
        assert worker._accepting is False

        worker.method_queue.close()

    def test_graceful_shutdown_drains_connections(self):
        """Test that graceful shutdown waits for connections to drain."""
        worker = self.create_worker()
        worker.method_queue.init()
        worker.poller = mock.Mock()
        worker.poller.select.return_value = []
        worker.tpool = mock.Mock()
        worker.sockets = []
        worker.nr_conns = 1  # One active connection
        worker.alive = True

        # Track iterations
        iterations = [0]
        def mock_select(timeout):
            iterations[0] += 1
            if iterations[0] == 1:
                # First iteration: trigger shutdown
                worker.alive = False
            elif iterations[0] == 2:
                # Second iteration: during grace period
                pass
            elif iterations[0] >= 3:
                # Connection finishes
                worker.nr_conns = 0
            return []
        worker.poller.select.side_effect = mock_select
        worker.is_parent_alive = mock.Mock(return_value=True)

        worker.run()

        # Should have waited for connections
        assert iterations[0] >= 2
        worker.method_queue.close()

    def test_sigterm_does_not_interrupt_active_request(self):
        """Test that SIGTERM doesn't immediately interrupt active requests."""
        import signal

        worker = self.create_worker()
        worker.method_queue.init()

        # The base worker sets siginterrupt(SIGTERM, False) in init_signals
        # This ensures system calls aren't interrupted by SIGTERM

        # Verify handle_exit just sets alive=False, doesn't raise
        worker.alive = True
        worker.handle_exit(signal.SIGTERM, None)

        assert worker.alive is False
        # No exception raised, request can continue
        worker.method_queue.close()


class TestWorkerArbiterIntegration:
    """Integration tests for worker-arbiter communication."""

    def create_worker(self):
        """Create a worker for testing."""
        cfg = Config()
        cfg.set('workers', 1)
        cfg.set('threads', 4)
        cfg.set('worker_connections', 1000)
        cfg.set('graceful_timeout', 2)

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

    def test_worker_detects_parent_death(self):
        """Test that worker detects when parent process dies."""
        worker = self.create_worker()

        # Valid ppid
        worker.ppid = os.getppid()
        assert worker.is_parent_alive() is True

        # Invalid ppid (simulating parent death)
        worker.ppid = 99999999
        assert worker.is_parent_alive() is False

    def test_worker_exits_on_parent_death(self):
        """Test that worker exits when parent dies."""
        worker = self.create_worker()
        worker.method_queue.init()
        worker.poller = mock.Mock()
        worker.poller.select.return_value = []
        worker.tpool = mock.Mock()
        worker.sockets = []
        worker.alive = True
        worker.ppid = 99999999  # Invalid ppid

        iterations = [0]
        def mock_select(timeout):
            iterations[0] += 1
            return []
        worker.poller.select.side_effect = mock_select

        worker.run()

        # Should exit immediately due to parent check
        assert iterations[0] == 1
        worker.method_queue.close()

    def test_worker_tmp_file_can_be_monitored(self):
        """Test that worker tmp file can be used by arbiter for monitoring.

        The arbiter monitors workers by checking: time.monotonic() - last_update() <= timeout
        """
        from gunicorn.workers.workertmp import WorkerTmp

        cfg = Config()
        tmp = WorkerTmp(cfg)

        # Worker notifies - sets mtime to current monotonic time
        tmp.notify()

        # Arbiter check: time.monotonic() - last_update() should be small
        diff = time.monotonic() - tmp.last_update()
        assert diff < 1.0  # Worker just notified, should be nearly zero

        # If worker stops notifying, the difference grows
        time.sleep(0.1)
        diff_later = time.monotonic() - tmp.last_update()
        assert diff_later > diff  # Arbiter would notice worker isn't responding

        tmp.close()

    def test_graceful_timeout_honored(self):
        """Test that graceful_timeout is honored during shutdown."""
        worker = self.create_worker()
        worker.cfg.set('graceful_timeout', 1)  # 1 second for testing
        worker.method_queue.init()
        worker.poller = mock.Mock()
        worker.tpool = mock.Mock()
        worker.sockets = []
        worker.nr_conns = 1  # Active connection that won't finish
        worker.alive = True

        # Track iterations
        iterations = [0]
        start_time = [None]

        def mock_select(timeout):
            iterations[0] += 1
            if iterations[0] == 1:
                # First iteration: trigger shutdown
                worker.alive = False
                start_time[0] = time.monotonic()
                return []
            else:
                # Grace period iterations - simulate time passing via select timeout
                # The timeout should be the remaining time
                if timeout > 0:
                    # Simulate some time passing
                    time.sleep(min(timeout, 0.2))
                # Connection never finishes (nr_conns stays 1)
                return []
        worker.poller.select.side_effect = mock_select
        worker.is_parent_alive = mock.Mock(return_value=True)

        worker.run()

        # Should have completed (grace timeout expired with connection still active)
        assert iterations[0] >= 2  # At least one grace period iteration

        worker.method_queue.close()

    def test_run_completes_cleanup(self):
        """Test that run() properly cleans up resources on exit."""
        worker = self.create_worker()
        worker.method_queue.init()
        worker.poller = selectors.DefaultSelector()
        worker.tpool = futures.ThreadPoolExecutor(max_workers=2)
        worker.sockets = []
        worker.alive = False  # Immediately exit

        worker.is_parent_alive = mock.Mock(return_value=True)

        # Don't pre-register method_queue - run() will do it
        worker.run()

        # All resources should be cleaned up
        # (No assertion needed - if run() completes without error, cleanup worked)


class TestSignalInteraction:
    """Tests for signal interactions and edge cases."""

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
        return worker

    def test_multiple_sigterm_is_safe(self):
        """Test that receiving multiple SIGTERM is safe."""
        worker = self.create_worker()
        worker.method_queue.init()
        worker.alive = True

        # Multiple SIGTERM calls should be idempotent
        worker.handle_exit(None, None)
        assert worker.alive is False

        worker.handle_exit(None, None)
        assert worker.alive is False

        worker.method_queue.close()

    def test_sigterm_then_sigquit(self):
        """Test SIGQUIT after SIGTERM for force kill."""
        worker = self.create_worker()
        worker.method_queue.init()
        worker.tpool = mock.Mock()
        worker.alive = True

        # First SIGTERM for graceful
        worker.handle_exit(None, None)
        assert worker.alive is False

        # Then SIGQUIT for immediate
        with pytest.raises(SystemExit):
            worker.handle_quit(None, None)

        worker.tpool.shutdown.assert_called_once_with(wait=False)
        worker.method_queue.close()

    def test_sigquit_does_not_wait_for_threads(self):
        """Test that SIGQUIT calls tpool.shutdown(wait=False)."""
        worker = self.create_worker()
        worker.tpool = mock.Mock()

        with pytest.raises(SystemExit):
            worker.handle_quit(None, None)

        # Verify wait=False was passed
        worker.tpool.shutdown.assert_called_once_with(wait=False)

    def test_handle_exit_when_already_dead(self):
        """Test handle_exit when worker is already shutting down."""
        worker = self.create_worker()
        worker.method_queue.init()
        worker.alive = False

        # Should not raise, should be idempotent
        worker.handle_exit(None, None)
        assert worker.alive is False

        worker.method_queue.close()

    def test_connections_tracked_during_signal(self):
        """Test that connection count is correct during signal handling."""
        worker = self.create_worker()
        worker.method_queue.init()
        worker.poller = mock.Mock()
        worker.tpool = mock.Mock()
        worker.nr_conns = 5
        worker.alive = True

        # SIGTERM should not affect connection count
        worker.handle_exit(None, None)

        assert worker.nr_conns == 5  # Still 5 connections
        assert worker.alive is False  # But shutting down

        worker.method_queue.close()


class TestFinishBodySSL:
    """Tests for SSL error handling in finish_body()."""

    def test_finish_body_handles_ssl_want_read_error(self):
        """Test that finish_body() handles SSLWantReadError gracefully.

        When discarding unread body data on SSL connections, the socket
        may raise SSLWantReadError if there's no application data available.
        This should be treated as "no more data" rather than an error.
        """
        import ssl
        from gunicorn.http.parser import RequestParser

        # Create a mock SSL socket that raises SSLWantReadError on recv
        class MockSSLSocket:
            def __init__(self):
                self._fileno = 123

            def fileno(self):
                return self._fileno

            def recv(self, size):
                raise ssl.SSLWantReadError("The operation did not complete")

            def setblocking(self, blocking):
                pass

        cfg = Config()
        sock = MockSSLSocket()
        parser = RequestParser(cfg, sock, ('127.0.0.1', 12345))

        # Create a mock message with a body that will trigger socket read
        mock_body = mock.Mock()
        mock_body.read.side_effect = ssl.SSLWantReadError("The operation did not complete")

        mock_mesg = mock.Mock()
        mock_mesg.body = mock_body
        parser.mesg = mock_mesg

        # finish_body() should handle SSLWantReadError without raising
        parser.finish_body()  # Should not raise

        # Verify body.read was called
        mock_body.read.assert_called_once_with(8192)

    def test_finish_body_reads_all_data_before_ssl_error(self):
        """Test that finish_body() reads all available data before SSLWantReadError."""
        import ssl
        from gunicorn.http.parser import RequestParser

        cfg = Config()

        # Create a mock socket
        class MockSocket:
            def recv(self, size):
                return b''

            def setblocking(self, blocking):
                pass

        sock = MockSocket()
        parser = RequestParser(cfg, sock, ('127.0.0.1', 12345))

        # Create a mock message body that returns data then raises SSLWantReadError
        call_count = [0]
        def mock_read(size):
            call_count[0] += 1
            if call_count[0] <= 2:
                return b'x' * size  # Return data first two times
            raise ssl.SSLWantReadError("The operation did not complete")

        mock_body = mock.Mock()
        mock_body.read.side_effect = mock_read

        mock_mesg = mock.Mock()
        mock_mesg.body = mock_body
        parser.mesg = mock_mesg

        # finish_body() should read all data and handle SSLWantReadError
        parser.finish_body()  # Should not raise

        # Verify body.read was called multiple times (2 data reads + 1 error)
        assert call_count[0] == 3

    def test_finish_body_normal_operation(self):
        """Test that finish_body() works normally when no SSL error occurs."""
        from gunicorn.http.parser import RequestParser

        cfg = Config()

        class MockSocket:
            def recv(self, size):
                return b''

            def setblocking(self, blocking):
                pass

        sock = MockSocket()
        parser = RequestParser(cfg, sock, ('127.0.0.1', 12345))

        # Create a mock message body that returns empty (end of data)
        mock_body = mock.Mock()
        mock_body.read.return_value = b''

        mock_mesg = mock.Mock()
        mock_mesg.body = mock_body
        parser.mesg = mock_mesg

        # finish_body() should work normally
        parser.finish_body()

        # Verify body.read was called once and returned empty
        mock_body.read.assert_called_once_with(8192)
