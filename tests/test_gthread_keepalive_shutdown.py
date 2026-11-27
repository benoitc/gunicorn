#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""A gthread worker that stops (max_requests) still serves the next request
on a connection whose last response announced keep-alive, with
"Connection: close" (RFC 9112 section 9.6). See issue #3821.
"""

import socket
import subprocess
import sys
import threading
import time

import pytest

APP = '''
import time

def application(environ, start_response):
    if environ["PATH_INFO"] == "/slow":
        time.sleep(0.5)
    body = environ["PATH_INFO"].encode()
    start_response("200 OK", [("Content-Length", str(len(body)))])
    return [body]
'''


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server(tmp_path):
    (tmp_path / "app.py").write_text(APP)
    port = _free_port()
    log = tmp_path / "gunicorn.log"
    proc = subprocess.Popen(
        [sys.executable, "-m", "gunicorn", "app:application",
         "--bind", f"127.0.0.1:{port}", "--workers", "1",
         "--worker-class", "gthread", "--threads", "2",
         "--max-requests", "2", "--keep-alive", "5",
         "--graceful-timeout", "10", "--log-level", "info"],
        cwd=str(tmp_path), stdout=log.open("w"), stderr=subprocess.STDOUT)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), 0.3):
                break
        except OSError:
            if proc.poll() is not None:
                break
            time.sleep(0.05)
    else:
        proc.kill()
        pytest.fail(f"gunicorn did not start:\n{log.read_text()}")
    yield port
    proc.terminate()
    try:
        proc.wait(15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _request(sock, path):
    sock.sendall(b"GET " + path + b" HTTP/1.1\r\nHost: localhost\r\n\r\n")
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            return data
        data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    length = 0
    for line in head.split(b"\r\n")[1:]:
        name, _, value = line.partition(b":")
        if name.strip().lower() == b"content-length":
            length = int(value)
    while len(body) < length:
        chunk = sock.recv(4096)
        if not chunk:
            break
        body += chunk
    return head + b"\r\n\r\n" + body


def test_next_request_served_after_worker_stops(server):
    port = server
    slow = socket.create_connection(("127.0.0.1", port), 10)
    first = {}

    def run_slow():
        first["response"] = _request(slow, b"/slow")

    thread = threading.Thread(target=run_slow)
    thread.start()
    time.sleep(0.1)

    # The second request reaches max_requests while /slow is running, so
    # the worker stops after /slow announced keep-alive.
    with socket.create_connection(("127.0.0.1", port), 10) as other:
        response = _request(other, b"/fast")
    assert response.startswith(b"HTTP/1.1 200"), response
    assert b"Connection: close" in response

    thread.join(10)
    assert first["response"].startswith(b"HTTP/1.1 200"), first
    assert b"Connection: close" not in first["response"]

    # The client was told the connection stays open: its next request is
    # answered, and the answer says the connection now closes.
    response = _request(slow, b"/next")
    slow.close()
    assert response.startswith(b"HTTP/1.1 200"), response
    assert response.endswith(b"/next")
    assert b"Connection: close" in response


def test_idle_connection_served_after_worker_stops(server):
    port = server
    idle = socket.create_connection(("127.0.0.1", port), 10)
    response = _request(idle, b"/first")
    assert response.startswith(b"HTTP/1.1 200"), response
    assert b"Connection: close" not in response

    # This request reaches max_requests while the first connection is idle.
    with socket.create_connection(("127.0.0.1", port), 10) as other:
        response = _request(other, b"/fast")
    assert b"Connection: close" in response

    # The idle connection was not dropped: a request sent shortly after the
    # worker stopped (well within STOP_KEEPALIVE_LINGER) is answered.
    time.sleep(0.5)
    response = _request(idle, b"/next")
    idle.close()
    assert response.startswith(b"HTTP/1.1 200"), response
    assert response.endswith(b"/next")
    assert b"Connection: close" in response
