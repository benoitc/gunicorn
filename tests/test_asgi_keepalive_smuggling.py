#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""End-to-end regression test for the keepalive smuggling guard.

Drives an ``ASGIProtocol`` against a fake transport with two pipelined
requests: the first POST advertises a Content-Length the client never
finishes sending; the app returns a response without consuming the body.
The protocol MUST refuse keepalive (close the transport) and MUST NOT
parse the second request from residual body bytes.

Without the fix this test surfaces, the smuggling guard added in PR #3614
is silently bypassed because ``_handle_http_request`` clears
``_body_receiver`` in its ``finally`` block before the connection loop's
gate can read it.  See the commit that added this test for the fix.
"""

import asyncio
import sys

import pytest

from gunicorn.config import Config
from gunicorn.asgi.protocol import ASGIProtocol


class _FakeTransport(asyncio.Transport):
    """Minimal asyncio.Transport stand-in that captures writes and close."""

    def __init__(self):
        super().__init__()
        self._buffer = bytearray()
        self.closed = False
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
        self.closed = True

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
    """Minimal logger compatible with what ASGIProtocol calls."""

    def debug(self, *a, **k): pass
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def exception(self, *a, **k): pass

    @property
    def access_log_enabled(self):
        return False


def _build_worker(loop, app, http_parser):
    cfg = Config()
    cfg.set('keepalive', 2)
    cfg.set('timeout', 30)
    cfg.set('http_parser', http_parser)

    class _W:
        pass
    w = _W()
    w.cfg = cfg
    w.loop = loop
    w.log = _Log()
    w.asgi = app
    w.nr_conns = 0
    w.nr = 0
    w.max_requests = 1000
    w.alive = True
    return w


@pytest.fixture(params=["python", "fast"])
def http_parser(request):
    """Parametrize the smuggling test across both parser implementations."""
    if request.param == "fast":
        if hasattr(sys, "pypy_version_info"):
            pytest.skip("gunicorn_h1c not supported on PyPy")
        gunicorn_h1c = pytest.importorskip("gunicorn_h1c")
        if not hasattr(gunicorn_h1c.H1CProtocol, "asgi_headers"):
            pytest.skip("gunicorn_h1c >= 0.6.2 required")
    return request.param


@pytest.mark.asyncio
async def test_keepalive_refused_when_first_body_is_partial(http_parser):
    """Two pipelined requests on the same connection.  The first POST
    advertises Content-Length: 100 but the client only sends 10 body
    bytes.  The app returns 200 without consuming the body.  The
    transport MUST close instead of serving a second response from the
    residual bytes (which would be the second request the attacker
    pipelined behind the short body).

    Run under both the Python parser and the C parser (gunicorn_h1c) so
    the smuggling guard is verified end-to-end on every supported path.
    """

    async def app(scope, receive, send):
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-length", b"2")],
        })
        await send({
            "type": "http.response.body",
            "body": b"ok",
            "more_body": False,
        })

    loop = asyncio.get_event_loop()
    worker = _build_worker(loop, app, http_parser)
    protocol = ASGIProtocol(worker)
    transport = _FakeTransport()

    protocol.connection_made(transport)

    first_request = (
        b"POST /first HTTP/1.1\r\n"
        b"Host: example.com\r\n"
        b"Content-Length: 100\r\n"
        b"\r\n"
        b"only-ten-b"  # 10 bytes of the promised 100
    )
    smuggled_second = (
        b"GET /smuggled HTTP/1.1\r\n"
        b"Host: example.com\r\n"
        b"\r\n"
    )

    protocol.data_received(first_request)
    # Give the loop a chance to run the app and emit the response.
    for _ in range(20):
        await asyncio.sleep(0)

    # The app has answered.  Now the attacker streams what looks like a
    # second pipelined request.  This MUST NOT be served.
    protocol.data_received(smuggled_second)
    for _ in range(20):
        await asyncio.sleep(0)

    response = transport.written
    # The first response was sent.
    assert response.startswith(b"HTTP/1.1 200"), response[:60]
    # Only one response was written; nothing for /smuggled.
    assert response.count(b"HTTP/1.1 ") == 1, response
    # The transport closed: the connection refused keepalive.
    assert transport.closed is True

    # Drain the connection task cleanly.
    if protocol._task and not protocol._task.done():
        protocol._task.cancel()
        try:
            await protocol._task
        except (asyncio.CancelledError, Exception):
            pass


async def _serve_two(http_parser, chunks):
    """Serve two pipelined GETs with an app that declares Content-Length: 5
    and sends ``chunks`` as its body.  Returns (written bytes, closed)."""

    async def app(scope, receive, send):
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-length", b"5")],
        })
        for i, chunk in enumerate(chunks):
            await send({
                "type": "http.response.body",
                "body": chunk,
                "more_body": i < len(chunks) - 1,
            })

    loop = asyncio.get_event_loop()
    worker = _build_worker(loop, app, http_parser)
    protocol = ASGIProtocol(worker)
    transport = _FakeTransport()
    protocol.connection_made(transport)

    protocol.data_received(
        b"GET /a HTTP/1.1\r\nHost: example.com\r\n\r\n"
        b"GET /b HTTP/1.1\r\nHost: example.com\r\n\r\n"
    )
    for _ in range(40):
        await asyncio.sleep(0)

    if protocol._task and not protocol._task.done():
        protocol._task.cancel()
        try:
            await protocol._task
        except (asyncio.CancelledError, Exception):
            pass
    return transport.written, transport.closed


@pytest.mark.asyncio
async def test_response_body_capped_at_content_length(http_parser):
    """Bytes past the app's Content-Length must not reach the wire, where a
    proxy reusing the connection would read them as the next response."""
    forged = b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\nevil"
    written, _ = await _serve_two(http_parser, [b"hel", b"lo" + forged])

    assert b"evil" not in written, written
    responses = written.split(b"HTTP/1.1 200")
    assert len(responses) == 3, written
    for resp in responses[1:]:
        assert resp.endswith(b"\r\n\r\nhello"), written


@pytest.mark.asyncio
async def test_short_response_body_closes_connection(http_parser):
    """A body shorter than the declared Content-Length must close the
    connection instead of keeping it alive."""
    written, closed = await _serve_two(http_parser, [b"hi"])

    assert written.count(b"HTTP/1.1 200") == 1, written
    assert written.endswith(b"\r\n\r\nhi"), written
    assert closed is True
