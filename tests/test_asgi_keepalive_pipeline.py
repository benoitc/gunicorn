#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Keepalive pipelining on the ASGI worker, against a live gunicorn.

Regression for the bug where a request pipelined on a kept-alive HTTP/1.1
connection was dropped: the keepalive loop reset the parser between requests,
which cleared the buffered next request, and the connection then hung until the
client timed out. Covers both parser backends.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

APPS = Path(__file__).parent / "support"

PARSERS = ["python"]
try:
    import gunicorn_h1c  # noqa: F401
    PARSERS.append("fast")
except ImportError:
    pass

REQ = b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    """One gunicorn asgi process serving the live app over plain HTTP/1.1."""

    def __init__(self, parser, tmp_path):
        self.port = _free_port()
        self.log = tmp_path / f"gunicorn-ka-{parser}-{self.port}.log"
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "gunicorn", "http2_live_app:asgi",
             "--bind", f"127.0.0.1:{self.port}", "--workers", "1",
             "--worker-class", "asgi", "--http-parser", parser,
             "--keep-alive", "5", "--graceful-timeout", "2",
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

    def tracebacks(self):
        return self.log.read_text().count("Traceback")

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()


@pytest.fixture(params=PARSERS)
def server(request, tmp_path):
    srv = Server(request.param, tmp_path)
    yield srv
    srv.stop()


def _read_responses(sock, want, timeout=5.0):
    """Read until ``want`` chunked responses have arrived, EOF, or timeout."""
    sock.settimeout(timeout)
    buf = b""
    deadline = time.monotonic() + timeout
    while buf.count(b"0\r\n\r\n") < want and time.monotonic() < deadline:
        try:
            data = sock.recv(4096)
        except socket.timeout:
            break
        if not data:
            break
        buf += data
    return buf


def test_pipelined_requests_in_one_write_are_both_served(server):
    # Both requests in a single write: the second is guaranteed to sit in the
    # parser buffer when the first finishes, so this is deterministic.
    sock = socket.create_connection(("127.0.0.1", server.port), 5)
    sock.sendall(REQ + REQ)
    resp = _read_responses(sock, 2)
    sock.close()
    assert resp.count(b"HTTP/1.1 200") == 2, resp
    assert server.tracebacks() == 0


def test_second_request_on_reused_connection(server):
    # The httpx pattern: read the first response fully, then send the second on
    # the same connection. Looped to have caught the pre-fix race.
    for _ in range(30):
        sock = socket.create_connection(("127.0.0.1", server.port), 5)
        sock.sendall(REQ)
        first = _read_responses(sock, 1, timeout=5.0)
        assert first.count(b"HTTP/1.1 200") == 1, first
        sock.sendall(REQ)
        second = _read_responses(sock, 1, timeout=5.0)
        sock.close()
        assert second.count(b"HTTP/1.1 200") == 1, f"reused-conn stall: {second!r}"
    assert server.tracebacks() == 0
