#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Serving on Windows.

The master forks workers and steers them with POSIX signals; Windows has
neither, so a run there serves from one process (gunicorn.single).
"""

import contextlib
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from unittest import mock

import pytest

from gunicorn import compat
from gunicorn.config import Config
from gunicorn.workers.gthread import ThreadWorker
from gunicorn.workers.sync import SyncWorker

pytestmark = pytest.mark.skipif(not compat.WINDOWS, reason="Windows only")

APP = '''\
def application(environ, start_response):
    body = environ["PATH_INFO"].encode()
    start_response("200 OK", [("Content-Length", str(len(body)))])
    return [body]
'''

SLOW_APP = '''\
import time

def application(environ, start_response):
    time.sleep(30)
    start_response("200 OK", [("Content-Length", "4")])
    return [b"slow"]
'''

# A slow path for one generation to be busy with while another recycles.
BUSY_APP = '''\
import time

def application(environ, start_response):
    if environ["PATH_INFO"] == "/slow":
        time.sleep(3)
    body = environ["PATH_INFO"].encode()
    start_response("200 OK", [("Content-Length", str(len(body)))])
    return [body]
'''

# A new process group is what lets the test send Ctrl+Break to the server
# without stopping itself (GenerateConsoleCtrlEvent takes a group id). Both
# are Windows-only, hence the getattr for collection on other platforms.
NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
CTRL_BREAK = getattr(signal, "CTRL_BREAK_EVENT", None)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def get(port, path="/"):
    url = "http://127.0.0.1:%d%s" % (port, path)
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.status, response.read()


def wait_until_serving(proc, port, log):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            break
        try:
            with socket.create_connection(("127.0.0.1", port), 0.3):
                return
        except OSError:
            time.sleep(0.05)
    pytest.fail("gunicorn did not start:\n%s" % log.read_text())


@contextlib.contextmanager
def running(tmp_path, *options, app=APP):
    (tmp_path / "app.py").write_text(app)
    port = free_port()
    log = tmp_path / "server.log"
    with log.open("w") as out:
        proc = subprocess.Popen(
            [sys.executable, "-m", "gunicorn", "app:application",
             "--bind", "127.0.0.1:%d" % port, *options],
            cwd=str(tmp_path), stdout=out, stderr=subprocess.STDOUT,
            creationflags=NEW_PROCESS_GROUP)
    try:
        wait_until_serving(proc, port, log)
        yield proc, port
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def read_response(conn, path):
    conn.sendall(b"GET " + path.encode() + b" HTTP/1.1\r\nHost: localhost\r\n\r\n")
    data = b""
    while b"\r\n\r\n" not in data:
        data += conn.recv(4096)
    head, _, body = data.partition(b"\r\n\r\n")
    length = 0
    for line in head.split(b"\r\n")[1:]:
        name, _, value = line.partition(b":")
        if name.strip().lower() == b"content-length":
            length = int(value)
    while len(body) < length:
        body += conn.recv(4096)
    return body


def test_config_loads():
    cfg = Config()

    # Windows has no user or group ids; both read as 0 and the code that
    # compares them against the running process stays a no-op.
    assert cfg.user == 0
    assert cfg.group == 0


def test_check_config_accepts_defaults(tmp_path):
    (tmp_path / "app.py").write_text(APP)

    result = subprocess.run(
        [sys.executable, "-m", "gunicorn", "app:application", "--check-config"],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=60, check=False)

    assert result.returncode == 0, result.stderr


def test_sync_worker_serves(tmp_path):
    with running(tmp_path) as (_, port):
        assert get(port, "/hello") == (200, b"/hello")


def test_gthread_worker_serves(tmp_path):
    with running(tmp_path, "--worker-class", "gthread", "--threads", "2") as (_, port):
        assert get(port, "/threaded") == (200, b"/threaded")


def test_gthread_keeps_the_connection_open(tmp_path):
    """Two requests on one connection: the second goes through the thread
    pool again, which is woken by the socketpair because Windows select()
    cannot watch a pipe."""
    with running(tmp_path, "--worker-class", "gthread", "--threads", "2") as (_, port):
        with socket.create_connection(("127.0.0.1", port), 10) as conn:
            assert read_response(conn, "/one") == b"/one"
            assert read_response(conn, "/two") == b"/two"


def test_ctrl_break_stops_the_process(tmp_path):
    pidfile = tmp_path / "server.pid"

    with running(tmp_path, "--pid", str(pidfile)) as (proc, port):
        assert int(pidfile.read_text()) > 0
        assert get(port, "/before") == (200, b"/before")

        proc.send_signal(CTRL_BREAK)
        assert proc.wait(15) == 0

    assert not pidfile.exists()


def test_gthread_serves_concurrent_requests(tmp_path):
    with running(tmp_path, "--worker-class", "gthread", "--threads", "4") as (_, port):
        results = []

        def hit(path):
            results.append(get(port, path))

        threads = [threading.Thread(target=hit, args=("/n%d" % i,))
                   for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)

        assert len(results) == 8
        for status, body in results:
            assert status == 200
            assert body.startswith(b"/n")


ABORTED = ConnectionAbortedError(10053, "An established connection was aborted")


class AbortedSocket:
    """A client socket whose next read finds the connection aborted."""

    def recv(self, size):
        raise ABORTED

    def shutdown(self, how):
        raise OSError("already closed")

    def close(self):
        pass


class AbortedParser:
    def __next__(self):
        raise ABORTED


def test_sync_aborted_connection_is_not_an_error():
    """Chrome cancels connections it opened; Windows reports that as
    WSAECONNABORTED where POSIX reports ECONNRESET, which is not an error."""
    worker = object.__new__(SyncWorker)
    worker.cfg = Config()
    worker.log = mock.Mock()
    worker.ppid = 0

    worker.handle(None, AbortedSocket(), ("127.0.0.1", 5000))

    worker.log.exception.assert_not_called()
    worker.log.debug.assert_called()


def test_gthread_aborted_connection_is_not_an_error():
    worker = object.__new__(ThreadWorker)
    worker.cfg = Config()
    worker.log = mock.Mock()
    worker.ppid = 0
    conn = mock.Mock()
    conn.initialized = True
    conn.data_ready = True
    conn.is_http2 = False
    conn.parser = AbortedParser()

    worker.handle(conn)

    worker.log.exception.assert_not_called()
    worker.log.debug.assert_called()


def test_max_requests_starts_a_new_worker(tmp_path):
    """The master starts a new worker when max_requests is reached; without
    one, the same process starts a new worker instead of exiting."""
    with running(tmp_path, "--max-requests", "2") as (proc, port):
        for _ in range(5):
            assert get(port, "/still-up") == (200, b"/still-up")

        assert proc.poll() is None


def test_gthread_restarts_after_max_requests(tmp_path):
    """Each worker generation must leave the listeners it shares with the
    process alone; closing them stops the server."""
    with running(tmp_path, "--worker-class", "gthread", "--threads", "2",
                 "--max-requests", "2") as (proc, port):
        for _ in range(5):
            assert get(port, "/again") == (200, b"/again")

        assert proc.poll() is None


def test_stalled_client_does_not_block_the_worker(tmp_path):
    """Without a master to murder a worker stuck on a silent peer, the read
    itself has to time out so the next request is served."""
    with running(tmp_path, "--timeout", "2") as (_, port):
        stalled = socket.create_connection(("127.0.0.1", port), 10)
        stalled.sendall(b"GET /stall HTTP/1.1\r\nHost: localhost\r\n")
        time.sleep(0.3)

        started = time.monotonic()
        assert get(port, "/next") == (200, b"/next")
        assert time.monotonic() - started < 6

        stalled.close()


def test_stalled_clients_do_not_exhaust_the_thread_pool(tmp_path):
    """The same for gthread: a peer that stops mid-request must not hold its
    thread for ever, or a few of them take the whole pool."""
    with running(tmp_path, "--worker-class", "gthread", "--threads", "2",
                 "--timeout", "2") as (_, port):
        stalled = []
        for _ in range(2):
            conn = socket.create_connection(("127.0.0.1", port), 10)
            conn.sendall(b"GET /stall HTTP/1.1\r\nHost: localhost\r\n")
            stalled.append(conn)

        time.sleep(0.3)
        started = time.monotonic()
        assert get(port, "/next") == (200, b"/next")
        assert time.monotonic() - started < 8

        for conn in stalled:
            conn.close()


def test_shutdown_is_bounded_by_graceful_timeout(tmp_path):
    """With no master to SIGKILL the worker, the process ends itself when an
    application call overruns the graceful timeout."""
    with running(tmp_path, "--worker-class", "gthread", "--threads", "2",
                 "--graceful-timeout", "1", app=SLOW_APP) as (proc, port):
        slow = socket.create_connection(("127.0.0.1", port), 10)
        slow.sendall(b"GET /slow HTTP/1.1\r\nHost: localhost\r\n\r\n")
        time.sleep(0.5)

        started = time.monotonic()
        proc.send_signal(CTRL_BREAK)

        assert proc.wait(8) == 0
        assert time.monotonic() - started < 4

        slow.close()


def test_sync_shutdown_is_bounded_by_graceful_timeout(tmp_path):
    """The sync worker cannot leave its loop while the application call is
    running, so the deadline must be armed when the signal arrives."""
    with running(tmp_path, "--graceful-timeout", "1", app=SLOW_APP) as (proc, port):
        slow = socket.create_connection(("127.0.0.1", port), 10)
        slow.sendall(b"GET /slow HTTP/1.1\r\nHost: localhost\r\n\r\n")
        time.sleep(0.5)

        started = time.monotonic()
        proc.send_signal(CTRL_BREAK)

        assert proc.wait(8) == 0
        assert time.monotonic() - started < 4

        slow.close()


def test_gthread_stop_is_recorded_while_recycling():
    """max_requests stops the loop before the stop signal arrives; the stop
    still has to be recorded or the runner starts another worker."""
    worker = object.__new__(ThreadWorker)
    worker.log = mock.Mock()
    worker.alive = False
    worker.stopping = False

    worker.handle_exit(signal.SIGTERM, None)

    assert worker.stopping is True


def test_pidfile_is_removed_on_shutdown(tmp_path):
    """A pid file left behind makes the next start think a server is running."""
    pidfile = tmp_path / "server.pid"

    with running(tmp_path, "--pid", str(pidfile)) as (proc, _):
        assert pidfile.exists()

        proc.send_signal(CTRL_BREAK)
        assert proc.wait(15) == 0

    assert not pidfile.exists()


def test_system_exit_status_is_preserved(tmp_path):
    """An application that exits during startup must not look like a clean
    stop: a supervisor restarts on failure, not on success."""
    (tmp_path / "app.py").write_text("raise SystemExit(23)\n")

    result = subprocess.run(
        [sys.executable, "-m", "gunicorn", "app:application",
         "--bind", "127.0.0.1:0"],
        cwd=str(tmp_path), capture_output=True, text=True,
        timeout=30, check=False)

    assert result.returncode == 23


def test_gthread_caps_connections_for_the_windows_selector():
    """select() on Windows waits on at most 512 sockets, so the default of
    1000 connections would make the only serving process exit."""
    cfg = Config()
    cfg.set("worker_connections", 1000)
    log = mock.Mock()

    ThreadWorker.check_config(cfg, log)
    assert "capping" in log.warning.call_args[0][0]

    worker = ThreadWorker(age=0, ppid=None, sockets=[], app=mock.Mock(),
                          timeout=1, cfg=cfg, log=log)
    try:
        assert worker.worker_connections == compat.SELECT_MAX_CONNECTIONS
    finally:
        worker.tmp.close()


def test_recycle_does_not_stack_worker_generations(tmp_path):
    """When a recycled generation still has a request running, the next one
    must wait for it instead of stacking another thread pool on top."""
    options = ("--worker-class", "gthread", "--threads", "2",
               "--max-requests", "1", "--graceful-timeout", "1",
               "--timeout", "5", "--worker-connections", "10")

    with running(tmp_path, *options, app=BUSY_APP) as (proc, port):
        slow = socket.create_connection(("127.0.0.1", port), 10)
        slow.sendall(b"GET /slow HTTP/1.1\r\nHost: localhost\r\n\r\n")
        time.sleep(0.2)

        # This one reaches max_requests, so the generation starts retiring
        # while /slow is still running.
        assert get(port, "/fast") == (200, b"/fast")

        started = time.monotonic()
        assert get(port, "/next") == (200, b"/next")
        assert time.monotonic() - started > 1.5

        assert proc.poll() is None
        slow.close()


def test_second_server_on_a_busy_port_fails(tmp_path):
    """Windows gives SO_REUSEADDR the opposite meaning, so a second server
    could bind an address that is already listening. POSIX refuses it."""
    with running(tmp_path) as (_, port):
        result = subprocess.run(
            [sys.executable, "-m", "gunicorn", "app:application",
             "--bind", "127.0.0.1:%d" % port],
            cwd=str(tmp_path), capture_output=True, text=True,
            timeout=30, check=False)

    assert result.returncode != 0
    assert "connection in use" in (result.stdout + result.stderr).lower()


@pytest.mark.parametrize("options", [
    ("--daemon",),
    ("--worker-class", "asgi"),
    ("--bind", "unix:/tmp/gunicorn.sock"),
    ("--user", "1000"),
    ("--reload",),
])
def test_settings_that_need_a_master_are_rejected(tmp_path, options):
    (tmp_path / "app.py").write_text(APP)

    result = subprocess.run(
        [sys.executable, "-m", "gunicorn", "app:application", *options],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=60, check=False)

    assert result.returncode == 1
    assert "not supported on windows" in result.stderr.lower(), result.stderr
