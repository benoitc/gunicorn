#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""The ASGI worker announces Connection: close, against a live gunicorn.

RFC 9112: a server that will not reuse a connection must say so. Spawns the
ASGI worker over plain HTTP/1.1 and checks, on the wire, that the header is
present exactly when the connection is closed and absent when it is kept alive.
"""

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

APPS = Path(__file__).parent / "support"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self, tmp_path, extra_args=()):
        self.port = _free_port()
        self.log = tmp_path / f"gunicorn-close-{self.port}.log"
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "gunicorn", "http2_live_app:asgi",
             "--bind", f"127.0.0.1:{self.port}", "--workers", "1",
             "--worker-class", "asgi", "--graceful-timeout", "2",
             "--log-level", "info", *extra_args],
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


def _request(port, headers=""):
    """Send one request and return the raw response bytes."""
    sock = socket.create_connection(("127.0.0.1", port), 5)
    sock.settimeout(5)
    sock.sendall(f"GET / HTTP/1.1\r\nHost: localhost\r\n{headers}\r\n".encode())
    data = b""
    try:
        while b"\r\n\r\n" not in data or b"0\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
    except socket.timeout:
        pass
    sock.close()
    return data


def test_client_connection_close_is_announced(tmp_path):
    srv = Server(tmp_path)
    try:
        resp = _request(srv.port, "Connection: close\r\n")
        assert resp.startswith(b"HTTP/1.1 200"), resp
        assert b"\r\nConnection: close\r\n" in resp, resp
    finally:
        srv.stop()


def test_keepalive_disabled_is_announced(tmp_path):
    srv = Server(tmp_path, ["--keep-alive", "0"])
    try:
        resp = _request(srv.port)
        assert resp.startswith(b"HTTP/1.1 200"), resp
        assert b"\r\nConnection: close\r\n" in resp, resp
    finally:
        srv.stop()


def test_max_requests_recycle_is_announced(tmp_path):
    srv = Server(tmp_path, ["--max-requests", "1"])
    try:
        resp = _request(srv.port)
        assert resp.startswith(b"HTTP/1.1 200"), resp
        assert b"\r\nConnection: close\r\n" in resp, resp
    finally:
        srv.stop()


def test_default_keepalive_is_not_announced(tmp_path):
    srv = Server(tmp_path)
    try:
        resp = _request(srv.port)
        assert resp.startswith(b"HTTP/1.1 200"), resp
        assert b"connection: close" not in resp.lower(), resp
    finally:
        srv.stop()
