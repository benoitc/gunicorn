#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""The ASGI worker over the uWSGI protocol, against a live gunicorn.

Spawns gunicorn with ``--worker-class asgi --protocol uwsgi`` on a loopback
port and speaks the uWSGI binary protocol directly (as nginx ``uwsgi_pass``
would), asserting the request is served and the body round-trips. Regression
for the wiring bug where the ASGI worker never fed its uWSGI reader and 502'd
every request.
"""

import os
import socket
import struct
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


def _packet(variables, body=b""):
    block = b""
    for key, value in variables:
        key, value = key.encode(), value.encode()
        block += struct.pack("<H", len(key)) + key
        block += struct.pack("<H", len(value)) + value
    return struct.pack("<BHB", 0, len(block), 0) + block + body


class Server:
    def __init__(self, tmp_path):
        self.port = _free_port()
        self.log = tmp_path / f"gunicorn-uwsgi-{self.port}.log"
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "gunicorn", "uwsgi_asgi_app:app",
             "--bind", f"127.0.0.1:{self.port}", "--workers", "1",
             "--worker-class", "asgi", "--protocol", "uwsgi",
             "--uwsgi-allow-from", "*", "--keep-alive", "2",
             "--graceful-timeout", "1", "--log-level", "info"],
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

    def request(self, variables, body=b""):
        sock = socket.create_connection(("127.0.0.1", self.port), 3)
        sock.settimeout(3)
        sock.sendall(_packet(variables, body))
        data = b""
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
        except socket.timeout:
            pass
        sock.close()
        return data

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


@pytest.fixture
def server(tmp_path):
    if not os.environ.get("GUNICORN_TESTING", "1"):
        pytest.skip("disabled")
    srv = Server(tmp_path)
    yield srv
    srv.stop()


def _base_vars(method, path, query="", length=0):
    return [
        ("REQUEST_METHOD", method), ("PATH_INFO", path),
        ("QUERY_STRING", query), ("REQUEST_URI", path + (f"?{query}" if query else "")),
        ("SERVER_PROTOCOL", "HTTP/1.1"), ("SERVER_NAME", "localhost"),
        ("SERVER_PORT", "80"), ("CONTENT_LENGTH", str(length)),
    ]


def test_get_is_served(server):
    resp = server.request(_base_vars("GET", "/hello", "a=1"))
    assert resp.startswith(b"HTTP/1.1 200"), resp
    assert b"method=GET path=/hello query=a=1 body=" in resp, resp
    assert server.tracebacks() == 0


def test_post_body_round_trips(server):
    body = b"payload-1234567890"
    resp = server.request(_base_vars("POST", "/echo", length=len(body)), body)
    assert resp.startswith(b"HTTP/1.1 200"), resp
    assert b"method=POST path=/echo query= body=" + body in resp, resp
    assert server.tracebacks() == 0


def test_keepalive_serves_multiple_on_one_worker(server):
    for i in range(5):
        resp = server.request(_base_vars("GET", f"/n{i}"))
        assert resp.startswith(b"HTTP/1.1 200"), resp
    assert server.tracebacks() == 0
