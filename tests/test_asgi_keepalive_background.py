#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""The next request on a kept-alive HTTP/1.1 connection is served once the
previous response is complete, even when the application keeps running after
it (Starlette's background tasks). See issue #3819.
"""

import asyncio
import sys

import pytest

from gunicorn.config import Config
from gunicorn.asgi import protocol as protocol_mod
from gunicorn.asgi.protocol import ASGIProtocol


class _Transport(asyncio.Transport):
    """Captures writes; close() reports the loss like a real transport."""

    def __init__(self, loop):
        super().__init__()
        self._loop = loop
        self._buffer = bytearray()
        self.closed = False
        self.protocol = None
        self._extra = {
            'peername': ('127.0.0.1', 12345),
            'sockname': ('127.0.0.1', 8000),
            'ssl_object': None,
        }

    def get_extra_info(self, name, default=None):
        return self._extra.get(name, default)

    def write(self, data):
        if not self.closed:
            self._buffer.extend(data)

    def close(self):
        if not self.closed:
            self.closed = True
            self._loop.call_soon(self.protocol.connection_lost, None)

    def is_closing(self):
        return self.closed

    def can_write_eof(self):
        return False

    def set_write_buffer_limits(self, high=None, low=None):
        pass

    def get_write_buffer_size(self):
        return 0

    def pause_reading(self):
        pass

    def resume_reading(self):
        pass

    @property
    def written(self):
        return bytes(self._buffer)


class _Log:
    def debug(self, *a, **k): pass
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass
    def exception(self, *a, **k): pass

    @property
    def access_log_enabled(self):
        return False


@pytest.fixture(params=["python", "fast"])
def http_parser(request):
    if request.param == "fast":
        if hasattr(sys, "pypy_version_info"):
            pytest.skip("gunicorn_h1c not supported on PyPy")
        gunicorn_h1c = pytest.importorskip("gunicorn_h1c")
        if not hasattr(gunicorn_h1c.H1CProtocol, "asgi_headers"):
            pytest.skip("gunicorn_h1c >= 0.6.2 required")
    return request.param


def _connect(app, http_parser, keepalive=2, grace=3):
    loop = asyncio.get_event_loop()
    cfg = Config()
    cfg.set('keepalive', keepalive)
    cfg.set('timeout', 30)
    cfg.set('http_parser', http_parser)
    cfg.set('asgi_disconnect_grace_period', grace)

    class _W:
        pass
    worker = _W()
    worker.cfg = cfg
    worker.loop = loop
    worker.log = _Log()
    worker.asgi = app
    worker.nr_conns = 0
    worker.nr = 0
    worker.max_requests = 1000
    worker.alive = True

    protocol = ASGIProtocol(worker)
    transport = _Transport(loop)
    transport.protocol = protocol
    protocol.connection_made(transport)
    return protocol, transport


async def _spin(n=40):
    for _ in range(n):
        await asyncio.sleep(0)


async def _close(protocol):
    task = protocol._task
    if task and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


def _get(path, close=False):
    extra = b"Connection: close\r\n" if close else b""
    return b"GET " + path + b" HTTP/1.1\r\nHost: example.com\r\n" + extra + b"\r\n"


def _background_app(release, finished):
    """Answers, then keeps running on /slow until ``release`` is set."""

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-length", b"2")]})
        await send({"type": "http.response.body", "body": b"ok"})
        if scope["path"] == "/slow":
            await release.wait()
            finished.append(scope["path"])
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize("pipelined", [True, False])
async def test_next_request_served_while_app_still_runs(http_parser, pipelined):
    release = asyncio.Event()
    finished = []
    protocol, transport = _connect(_background_app(release, finished), http_parser)

    if pipelined:
        protocol.data_received(_get(b"/slow") + _get(b"/fast"))
    else:
        protocol.data_received(_get(b"/slow"))
        await _spin()
        assert transport.written.count(b"HTTP/1.1 200") == 1
        protocol.data_received(_get(b"/fast"))
    await _spin()

    assert transport.written.count(b"HTTP/1.1 200") == 2, transport.written
    assert finished == []
    assert not transport.closed

    release.set()
    await _spin()
    assert finished == ["/slow"]
    assert not protocol._finishing_calls
    await _close(protocol)


@pytest.mark.asyncio
async def test_connection_close_waits_for_app(http_parser):
    release = asyncio.Event()
    finished = []
    protocol, transport = _connect(_background_app(release, finished), http_parser)

    protocol.data_received(_get(b"/slow", close=True) + _get(b"/fast"))
    await _spin()
    assert transport.written.count(b"HTTP/1.1 200") == 1
    # Closed only once the application call has returned.
    assert not transport.closed

    release.set()
    await _spin()
    assert finished == ["/slow"]
    assert transport.closed
    assert transport.written.count(b"HTTP/1.1 200") == 1
    await _close(protocol)


@pytest.mark.asyncio
async def test_unread_body_waits_for_app(http_parser):
    """A request body not received in full keeps the old behaviour: the
    connection serves nothing else and closes after the call."""
    release = asyncio.Event()
    finished = []
    protocol, transport = _connect(_background_app(release, finished), http_parser)

    protocol.data_received(
        b"POST /slow HTTP/1.1\r\nHost: example.com\r\n"
        b"Content-Length: 100\r\n\r\npartial")
    await _spin()
    protocol.data_received(_get(b"/fast"))
    await _spin()
    assert transport.written.count(b"HTTP/1.1 200") == 1
    assert not protocol._finishing_calls

    release.set()
    await _spin()
    assert transport.closed
    assert transport.written.count(b"HTTP/1.1 200") == 1
    await _close(protocol)


@pytest.mark.asyncio
@pytest.mark.parametrize("read_body", [True, False])
async def test_body_not_taken_waits_for_app(http_parser, read_body):
    """A body that arrived in full but that the app left unread keeps the
    connection waiting for the call."""
    release = asyncio.Event()

    async def app(scope, receive, send):
        if read_body:
            await receive()
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-length", b"2")]})
        await send({"type": "http.response.body", "body": b"ok"})
        if scope["path"] == "/slow":
            await release.wait()

    protocol, transport = _connect(app, http_parser)
    protocol.data_received(
        b"POST /slow HTTP/1.1\r\nHost: example.com\r\n"
        b"Content-Length: 5\r\n\r\nhello" + _get(b"/fast"))
    await _spin()
    served = transport.written.count(b"HTTP/1.1 200")
    assert served == (2 if read_body else 1), transport.written

    release.set()
    await _spin()
    assert transport.written.count(b"HTTP/1.1 200") == 2
    await _close(protocol)


@pytest.mark.asyncio
async def test_finishing_calls_are_bounded(http_parser):
    release = asyncio.Event()
    finished = []
    protocol, transport = _connect(_background_app(release, finished), http_parser)
    limit = protocol_mod._MAX_FINISHING_APP_CALLS

    for _ in range(limit):
        protocol.data_received(_get(b"/slow"))
        await _spin()
    assert transport.written.count(b"HTTP/1.1 200") == limit
    assert len(protocol._finishing_calls) == limit

    protocol.data_received(_get(b"/fast"))
    await _spin()
    assert transport.written.count(b"HTTP/1.1 200") == limit

    release.set()
    await _spin()
    assert transport.written.count(b"HTTP/1.1 200") == limit + 1
    assert len(finished) == limit
    await _close(protocol)


@pytest.mark.asyncio
async def test_keepalive_timer_waits_for_app(http_parser):
    release = asyncio.Event()
    finished = []
    protocol, transport = _connect(
        _background_app(release, finished), http_parser, keepalive=1)

    protocol.data_received(_get(b"/slow"))
    await _spin()
    assert transport.written.count(b"HTTP/1.1 200") == 1
    # Not idle while the call runs: the keepalive timeout does not apply.
    await asyncio.sleep(1.2)
    assert not transport.closed

    release.set()
    await _spin()
    assert finished == ["/slow"]
    await asyncio.sleep(1.2)
    assert transport.closed
    await _close(protocol)


@pytest.mark.asyncio
async def test_disconnect_reaches_finishing_call(http_parser):
    received = []
    cancelled = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-length", b"2")]})
        await send({"type": "http.response.body", "body": b"ok"})
        if scope["path"] != "/slow":
            return
        received.append(await receive())
        received.append(await receive())
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    protocol, transport = _connect(app, http_parser, grace=0)
    protocol.data_received(_get(b"/slow") + _get(b"/fast"))
    await _spin()
    assert transport.written.count(b"HTTP/1.1 200") == 2

    protocol.connection_lost(None)
    await _spin()
    assert received == [
        {"type": "http.request", "body": b"", "more_body": False},
        {"type": "http.disconnect"},
    ]
    assert cancelled == [True]
    assert protocol._task.done()


@pytest.mark.asyncio
async def test_send_after_response_is_not_written(http_parser):
    """Nothing the call sends once its response is complete reaches the
    connection, which may already carry the next response."""
    release = asyncio.Event()

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-length", b"2")]})
        await send({"type": "http.response.body", "body": b"ok"})
        if scope["path"] == "/slow":
            await release.wait()
            await send({"type": "http.response.informational", "status": 103,
                        "headers": [(b"link", b"</a>")]})
            await send({"type": "http.response.body", "body": b"late"})

    protocol, transport = _connect(app, http_parser)
    protocol.data_received(_get(b"/slow") + _get(b"/fast"))
    await _spin()
    before = transport.written
    assert before.count(b"HTTP/1.1 200") == 2

    release.set()
    await _spin()
    assert transport.written == before
    await _close(protocol)


@pytest.mark.asyncio
async def test_post_request_hook_waits_for_app(http_parser):
    """The hook runs after the call and may close the connection, so the
    next request waits for it."""
    release = asyncio.Event()
    finished = []
    hooked = []
    protocol, transport = _connect(_background_app(release, finished), http_parser)
    protocol._post_request = lambda worker, req, environ, resp: hooked.append(req.path)

    protocol.data_received(_get(b"/slow") + _get(b"/fast"))
    await _spin()
    assert transport.written.count(b"HTTP/1.1 200") == 1
    assert not protocol._finishing_calls

    release.set()
    await _spin()
    assert transport.written.count(b"HTTP/1.1 200") == 2
    assert hooked == ["/slow", "/fast"]
    await _close(protocol)
