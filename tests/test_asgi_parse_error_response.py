#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""A request the parser rejects gets a 400 and the connection is closed,
with gunicorn_h1c as with the Python parser (RFC 9112 sections 3 and 5.1),
instead of an exception escaping data_received()."""

import asyncio

import pytest

from gunicorn.asgi.protocol import ASGIProtocol
from test_asgi_keepalive_smuggling import (
    _FakeTransport, _build_worker, http_parser,  # noqa: F401 (fixture)
)

MALFORMED = {
    "duplicate Host": b"GET / HTTP/1.1\r\nHost: a\r\nHost: b\r\n\r\n",
    "bare LF": b"GET / HTTP/1.1\nHost: a\n\n",
    "space before colon": b"GET / HTTP/1.1\r\nHost: a\r\nX-A : 1\r\n\r\n",
    "control character in target": b"GET /a\x01b HTTP/1.1\r\nHost: a\r\n\r\n",
    "obs-fold": b"GET / HTTP/1.1\r\nHost: a\r\nX-A: 1\r\n 2\r\n\r\n",
    "Content-Length with Transfer-Encoding": (
        b"POST / HTTP/1.1\r\nHost: a\r\nContent-Length: 3\r\n"
        b"Transfer-Encoding: chunked\r\n\r\n0\r\n\r\n"),
    "signed Content-Length": (
        b"POST / HTTP/1.1\r\nHost: a\r\nContent-Length: +3\r\n\r\nabc"),
    "two Content-Length values": (
        b"POST / HTTP/1.1\r\nHost: a\r\nContent-Length: 3\r\n"
        b"Content-Length: 4\r\n\r\nabcd"),
    "invalid method": b"G@T / HTTP/1.1\r\nHost: a\r\n\r\n",
    "invalid version": b"GET / HTTP/9.1\r\nHost: a\r\n\r\n",
    "invalid chunk size": (
        b"POST / HTTP/1.1\r\nHost: a\r\nTransfer-Encoding: chunked\r\n\r\nzz\r\n"),
}


async def _app(scope, receive, send):
    if scope["type"] != "http":
        return
    await send({"type": "http.response.start", "status": 200,
                "headers": [(b"content-length", b"2")]})
    await send({"type": "http.response.body", "body": b"ok"})


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", list(MALFORMED.values()), ids=list(MALFORMED))
async def test_malformed_request_gets_400(http_parser, raw):
    loop = asyncio.get_event_loop()
    protocol = ASGIProtocol(_build_worker(loop, _app, http_parser))
    transport = _FakeTransport()
    protocol.connection_made(transport)

    protocol.data_received(raw)  # must not raise
    for _ in range(20):
        await asyncio.sleep(0)

    assert transport.written.startswith(b"HTTP/1.1 400 ")
    assert b"\r\nConnection: close\r\n" in transport.written
    assert transport.closed
    if protocol._task and not protocol._task.done():
        protocol._task.cancel()
        try:
            await protocol._task
        except (asyncio.CancelledError, Exception):
            pass


@pytest.mark.asyncio
async def test_status_line_has_the_standard_reason_phrase(http_parser):
    """The error text quotes the request, so it goes in the body, never in
    the status line (RFC 9112 section 4)."""
    loop = asyncio.get_event_loop()
    protocol = ASGIProtocol(_build_worker(loop, _app, http_parser))
    transport = _FakeTransport()
    protocol.connection_made(transport)
    protocol.data_received(MALFORMED["space before colon"])
    for _ in range(20):
        await asyncio.sleep(0)
    head, _, body = transport.written.partition(b"\r\n\r\n")
    assert head.split(b"\r\n")[0] == b"HTTP/1.1 400 Bad Request"
    assert body  # the parser's message
    assert body not in head
    if protocol._task and not protocol._task.done():
        protocol._task.cancel()
        try:
            await protocol._task
        except (asyncio.CancelledError, Exception):
            pass


@pytest.mark.parametrize("status,reason", [
    (400, b"Bad Request"), (414, b"URI Too Long"),
    (431, b"Request Header Fields Too Large"), (426, b"Upgrade Required"),
    (599, b"Error"),
])
def test_error_response_reason_and_body(status, reason):
    protocol = ASGIProtocol.__new__(ASGIProtocol)
    transport = _FakeTransport()
    protocol.transport = transport
    protocol._send_error_response(status, "bad ☃ value\r\nX-Injected: 1")
    head, _, body = transport.written.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    assert lines[0] == b"HTTP/1.1 %d %s" % (status, reason)
    assert b"X-Injected" not in head
    assert body == "bad ☃ value\r\nX-Injected: 1".encode("utf-8")
    assert b"Content-Length: %d" % len(body) in lines
