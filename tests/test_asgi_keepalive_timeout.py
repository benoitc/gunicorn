#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Keepalive timeout on the ASGI worker, against a live gunicorn.

Regression for the bug where the ASGI worker never enforced ``keepalive``: the
timer was armed at the end of one iteration of the connection loop and cancelled
at the start of the next one without ever suspending in between, so an idle
kept-alive connection stayed open until the client closed it.
"""

import socket
import subprocess
import sys
import time
from pathlib import Path

APPS = Path(__file__).parent / "support"

REQ = b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n"
KEEPALIVE = 1


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self, tmp_path):
        self.port = _free_port()
        self.log = tmp_path / f"gunicorn-keepalive-{self.port}.log"
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "gunicorn", "http2_live_app:asgi",
             "--bind", f"127.0.0.1:{self.port}", "--workers", "1",
             "--worker-class", "asgi",
             "--keep-alive", str(KEEPALIVE), "--graceful-timeout", "2",
             "--log-level", "info"],
            cwd=str(APPS), stdout=self.log.open("w"), stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port), 0.3):
                    return
            except OSError:
                if self.proc.poll() is not None:
                    break
                time.sleep(0.05)
        self.stop()
        raise RuntimeError(f"gunicorn did not start:\n{self.log.read_text()}")

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()


def _read_response(sock):
    """Read one complete chunked response and return its raw bytes."""
    data = b""
    while b"\r\n\r\n" not in data or b"0\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    return data


def _wait_for_close(sock, timeout):
    """Return how long the server took to close the idle connection, or None."""
    sock.settimeout(timeout)
    start = time.monotonic()
    try:
        data = sock.recv(1)
    except socket.timeout:
        return None
    assert data == b"", f"unexpected data on idle connection: {data!r}"
    return time.monotonic() - start


def test_idle_keepalive_connection_is_closed(tmp_path):
    srv = Server(tmp_path)
    try:
        sock = socket.create_connection(("127.0.0.1", srv.port), 5)
        sock.settimeout(5)
        sock.sendall(REQ)
        assert _read_response(sock).startswith(b"HTTP/1.1 200")

        closed_after = _wait_for_close(sock, KEEPALIVE * 4)
        sock.close()
        assert closed_after is not None, "idle connection was not closed by the server"
        assert closed_after >= KEEPALIVE * 0.5, closed_after
    finally:
        srv.stop()


def test_request_within_keepalive_window_is_served(tmp_path):
    srv = Server(tmp_path)
    try:
        sock = socket.create_connection(("127.0.0.1", srv.port), 5)
        sock.settimeout(5)
        sock.sendall(REQ)
        assert _read_response(sock).startswith(b"HTTP/1.1 200")

        time.sleep(KEEPALIVE * 0.3)
        sock.sendall(REQ)
        assert _read_response(sock).startswith(b"HTTP/1.1 200")
        sock.close()
    finally:
        srv.stop()
