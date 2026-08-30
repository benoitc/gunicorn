# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Adversarial HTTP/2 checks against a live gunicorn, per worker class.

The docker suites drive cooperative clients on happy paths. These tests
spawn gunicorn on a loopback port with cleartext prior-knowledge HTTP/2
(no TLS needed) and speak raw frames through the h2 library: peers that
reset, stall, flood, or send GOAWAY mid-request. Each case asserts on
the wire and that the worker logged no traceback.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

h2 = pytest.importorskip("h2")
import h2.config  # noqa: E402
import h2.connection  # noqa: E402
import h2.errors  # noqa: E402
import h2.events  # noqa: E402
import h2.settings  # noqa: E402
from hyperframe.frame import DataFrame, GoAwayFrame  # noqa: E402

APPS = Path(__file__).parent / "support"

WORKERS = ["gthread", "asgi"]
try:
    import gevent  # noqa: F401
    WORKERS.append("gevent")
except ImportError:
    pass


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    """One gunicorn process serving the live app over h2c prior knowledge."""

    def __init__(self, worker, timeout=2, keepalive=1):
        self.worker = worker
        self.port = _free_port()
        app = "http2_live_app:asgi" if worker == "asgi" else "http2_live_app:wsgi"
        self.log = Path(os.environ.get("PYTEST_TMP", "/tmp")) / f"gunicorn-h2-{worker}-{self.port}.log"
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "gunicorn", app,
             "--bind", f"127.0.0.1:{self.port}", "--workers", "1",
             "--worker-class", worker, "--threads", "1",
             "--http-protocols", "h2,h1", "--http2-cleartext", "prior-knowledge",
             "--forwarded-allow-ips", "127.0.0.1",
             "--timeout", str(timeout), "--keep-alive", str(keepalive),
             "--graceful-timeout", "1", "--log-level", "info"],
            cwd=str(APPS), stdout=self.log.open("w"), stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
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

    baseline = 0

    def mark(self):
        """Tracebacks logged before this test do not count against it."""
        self.baseline = self.log.read_text().count("Traceback")

    def tracebacks(self):
        return self.log.read_text().count("Traceback") - self.baseline


class Client:
    """A raw h2 client over one TCP connection."""

    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.conn = h2.connection.H2Connection(
            config=h2.config.H2Configuration(client_side=True, header_encoding="utf-8"))
        self.conn.initiate_connection()
        self.flush()
        self.events = []
        # Return credit for response data as a real client does; a test
        # playing a slow reader turns this off.
        self.ack = True

    def flush(self):
        data = self.conn.data_to_send()
        if data:
            self.sock.sendall(data)

    def request(self, stream_id, method="GET", path="/", end_stream=True, extra=()):
        self.conn.send_headers(stream_id, [
            (":method", method), (":path", path),
            (":scheme", "http"), (":authority", "localhost"),
        ] + list(extra), end_stream=end_stream)
        self.flush()

    def read(self, until=None, timeout=3.0):
        """Read frames until ``until(events)`` is true, EOF, or timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if until is not None and until(self.events):
                return self.events
            self.sock.settimeout(max(0.05, deadline - time.monotonic()))
            try:
                data = self.sock.recv(65535)
            except socket.timeout:
                continue
            except ConnectionResetError:
                # gevent closes with unread bytes pending; same as EOF here
                data = b""
            if not data:
                self.events.append("EOF")
                return self.events
            for event in self.conn.receive_data(data):
                self.events.append(event)
                if self.ack and isinstance(event, h2.events.DataReceived) and event.flow_controlled_length:
                    self.conn.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
            self.flush()
        return self.events

    def kinds(self):
        return [e if isinstance(e, str) else type(e).__name__ for e in self.events]

    def close(self):
        self.sock.close()


def _response_status(events, stream_id=1):
    for e in events:
        if isinstance(e, h2.events.ResponseReceived) and e.stream_id == stream_id:
            return dict(e.headers)[":status"]
    return None


def _ended(stream_id=1):
    return lambda evs: any(
        isinstance(e, (h2.events.StreamEnded, h2.events.StreamReset)) and e.stream_id == stream_id
        for e in evs) or "EOF" in evs


def _reset_code(events, stream_id=1):
    for e in events:
        if isinstance(e, h2.events.StreamReset) and e.stream_id == stream_id:
            return e.error_code
    return None


@pytest.fixture(scope="module", params=WORKERS)
def server(request, tmp_path_factory):
    os.environ["PYTEST_TMP"] = str(tmp_path_factory.mktemp("h2live"))
    srv = Server(request.param)
    yield srv
    srv.stop()


@pytest.fixture
def client(server):
    server.mark()
    c = Client(server.port)
    yield c
    c.close()


def test_plain_request(server, client):
    client.request(1)
    client.read(_ended())
    assert _response_status(client.events) == "200"
    assert server.tracebacks() == 0


def test_streamed_upload_is_echoed_in_full(server, client):
    client.request(1, "POST", "/echo", end_stream=False)
    payload = os.urandom(300_000)
    sent = 0
    while sent < len(payload):
        window = client.conn.local_flow_control_window(1)
        if window <= 0:
            client.read(lambda evs: client.conn.local_flow_control_window(1) > 0, timeout=3)
            continue
        size = min(window, client.conn.max_outbound_frame_size, len(payload) - sent)
        client.conn.send_data(1, payload[sent:sent + size], end_stream=sent + size == len(payload))
        client.flush()
        sent += size
    client.read(_ended(), timeout=10)
    body = b"".join(e.data for e in client.events if isinstance(e, h2.events.DataReceived))
    assert _response_status(client.events) == "200"
    assert len(body) == len(payload) and body == payload
    assert server.tracebacks() == 0


def test_body_never_completing_is_bounded_by_the_window(server, client):
    client.request(1, "POST", "/echo", end_stream=False)
    client.conn.send_data(1, b"x" * 16384, end_stream=False)
    client.flush()
    # Only the initial windows worth is accepted before credit is returned
    # on consumption; the app is reading, so credit does come back.
    client.read(lambda evs: any(isinstance(e, h2.events.WindowUpdated) for e in evs), timeout=3)
    assert any(isinstance(e, h2.events.WindowUpdated) for e in client.events)
    assert server.tracebacks() == 0


def test_goaway_followed_by_data_in_one_write(server, client):
    client.request(1, "POST", "/echo", end_stream=False)
    data = DataFrame(1, data=b"tail")
    data.flags.add("END_STREAM")
    client.sock.sendall(GoAwayFrame(0, last_stream_id=1, error_code=0).serialize() + data.serialize())
    client.read(lambda evs: "EOF" in evs, timeout=5)
    kinds = client.kinds()
    assert _response_status(client.events) == "200"
    assert "StreamEnded" in kinds
    assert kinds[-1] == "EOF"
    assert server.tracebacks() == 0


def test_reset_while_the_app_reads_is_quiet(server, client):
    client.request(1, "POST", "/echo", end_stream=False)
    client.conn.send_data(1, b"part", end_stream=False)
    client.conn.reset_stream(1, error_code=h2.errors.ErrorCodes.CANCEL)
    client.flush()
    client.request(3)
    client.read(_ended(3))
    assert _response_status(client.events, 3) == "200"
    assert "Error" not in server.log.read_text()
    assert server.tracebacks() == 0


def test_slow_reader_is_cancelled_after_timeout(server, client):
    client.ack = False
    client.conn.update_settings({h2.settings.SettingCodes.INITIAL_WINDOW_SIZE: 1000})
    client.flush()
    client.request(1, path="/big")
    start = time.monotonic()
    client.read(_ended(), timeout=8)   # never widens the window
    assert _reset_code(client.events) == h2.errors.ErrorCodes.CANCEL
    assert time.monotonic() - start >= 1.5
    assert server.tracebacks() == 0


def test_idle_connection_is_closed_after_keepalive(server, client):
    client.read(lambda evs: "EOF" in evs, timeout=5)
    assert "EOF" in client.events
    assert "ConnectionTerminated" in client.kinds()
    assert server.tracebacks() == 0


def test_headers_reset_flood_leaves_the_worker_serving(server, client):
    client.request(1, "POST", "/echo", end_stream=False)
    for sid in range(3, 3 + 2 * 150, 2):
        client.request(sid)
        client.conn.reset_stream(sid, error_code=h2.errors.ErrorCodes.CANCEL)
    client.flush()
    client.conn.send_data(1, b"done", end_stream=True)
    client.flush()
    client.read(_ended(1), timeout=5)
    assert _response_status(client.events) == "200"
    assert server.tracebacks() == 0


def test_control_frame_flood_does_not_wedge_the_connection(server, client):
    for _ in range(20000):
        client.conn.ping(b"12345678")
    client.flush()
    client.request(1)
    client.read(_ended(), timeout=10)
    assert _response_status(client.events) == "200"
    assert server.tracebacks() == 0


def test_bad_request_resets_only_its_stream(server, client):
    client.request(1, extra=[("x-bad", "ctl\x01char")], end_stream=True)
    client.request(3)
    client.read(_ended(3), timeout=5)
    assert _reset_code(client.events, 1) == h2.errors.ErrorCodes.PROTOCOL_ERROR
    assert _response_status(client.events, 3) == "200"
    assert server.tracebacks() == 0


def test_app_error_after_headers_does_not_poison_hpack(server, client):
    client.request(1, path="/explode")
    client.read(_ended(1), timeout=5)
    assert _reset_code(client.events, 1) == h2.errors.ErrorCodes.INTERNAL_ERROR
    client.request(3, path="/headers")
    client.read(_ended(3), timeout=5)
    resp = [e for e in client.events
            if isinstance(e, h2.events.ResponseReceived) and e.stream_id == 3][0]
    assert dict(resp.headers).get("x-marker") == "present"


def test_empty_final_chunk_ends_the_stream(server, client):
    client.request(1, path="/chunks")
    client.read(_ended(), timeout=5)
    assert "StreamEnded" in client.kinds()
    assert server.tracebacks() == 0


def test_disconnect_listener_does_not_spin(server, client):
    if server.worker != "asgi":
        pytest.skip("ASGI receive() semantics")
    client.request(1, path="/listen")
    client.read(_ended(), timeout=5)
    assert _response_status(client.events) == "200"
    # The worker is still responsive
    client.request(3)
    client.read(_ended(3), timeout=5)
    assert _response_status(client.events, 3) == "200"
    assert server.tracebacks() == 0
