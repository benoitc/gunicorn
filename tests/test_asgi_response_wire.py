#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""The bytes the ASGI worker writes for a range of responses, recorded
before the response path was optimized; both parsers must still write
exactly these (only the Date value is masked)."""

import asyncio
import re

import pytest

from gunicorn.asgi.protocol import ASGIProtocol
from test_asgi_keepalive_smuggling import (
    _FakeTransport, _build_worker, http_parser,  # noqa: F401 (fixture)
)

CASES = [
    ('GET', '1.1', 200, [
        (b'content-type', b'text/plain'),
        (b'content-length', b'5'),
    ], [b'hello']),
    ('GET', '1.1', 404, [
        ('Content-Type', 'text/html'),
        ('Content-Length', '3'),
    ], [b'nop']),
    ('GET', '1.1', 599, [
        (b'content-length', b'1'),
    ], [b'x']),
    ('GET', '1.1', 204, [
        (b'content-length', b'0'),
        (b'x-a', b'1'),
    ], [b'']),
    ('GET', '1.1', 304, [
        (b'content-length', b'9'),
        (b'etag', b'"e"'),
    ], [b'']),
    ('GET', '1.1', 200, [
        (b'content-type', b'text/plain'),
    ], [b'ab', b'cd']),
    ('GET', '1.1', 200, [
        (b'transfer-encoding', b'chunked'),
    ], [b'ab', b'cd']),
    ('HEAD', '1.1', 200, [
        (b'content-length', b'5'),
    ], [b'hello']),
    ('GET', '1.0', 200, [
        (b'content-length', b'2'),
    ], [b'ok']),
    ('GET', '1.1', 200, [
        (b'server', b'custom'),
        (b'date', b'Mon, 01 Jan 2024 00:00:00 GMT'),
        (b'content-length', b'1'),
    ], [b'z']),
    ('GET', '1.1', 200, [
        (b'x-bad', b'a\r\nb'),
        (b'content-length', b'1'),
    ], [b'z']),
]

EXPECTED = [
    (
        b'HTTP/1.1 200 OK\r\n'
        b'content-type: text/plain\r\n'
        b'content-length: 5\r\n'
        b'Server: gunicorn/asgi\r\n'
        b'Date: X\r\n'
        b'\r\n'
        b'hello'
    ),
    (
        b'HTTP/1.1 404 Not Found\r\n'
        b'Content-Type: text/html\r\n'
        b'Content-Length: 3\r\n'
        b'Server: gunicorn/asgi\r\n'
        b'Date: X\r\n'
        b'\r\n'
        b'nop'
    ),
    (
        b'HTTP/1.1 599 Unknown\r\n'
        b'content-length: 1\r\n'
        b'Server: gunicorn/asgi\r\n'
        b'Date: X\r\n'
        b'\r\n'
        b'x'
    ),
    (
        b'HTTP/1.1 204 No Content\r\n'
        b'x-a: 1\r\n'
        b'Server: gunicorn/asgi\r\n'
        b'Date: X\r\n'
        b'\r\n'
    ),
    (
        b'HTTP/1.1 304 Not Modified\r\n'
        b'content-length: 9\r\n'
        b'etag: "e"\r\n'
        b'Server: gunicorn/asgi\r\n'
        b'Date: X\r\n'
        b'\r\n'
    ),
    (
        b'HTTP/1.1 200 OK\r\n'
        b'content-type: text/plain\r\n'
        b'transfer-encoding: chunked\r\n'
        b'Server: gunicorn/asgi\r\n'
        b'Date: X\r\n'
        b'\r\n'
        b'2\r\n'
        b'ab\r\n'
        b'2\r\n'
        b'cd\r\n'
        b'0\r\n'
        b'\r\n'
    ),
    (
        b'HTTP/1.1 200 OK\r\n'
        b'transfer-encoding: chunked\r\n'
        b'Server: gunicorn/asgi\r\n'
        b'Date: X\r\n'
        b'\r\n'
        b'2\r\n'
        b'ab\r\n'
        b'2\r\n'
        b'cd\r\n'
        b'0\r\n'
        b'\r\n'
    ),
    (
        b'HTTP/1.1 200 OK\r\n'
        b'content-length: 5\r\n'
        b'Server: gunicorn/asgi\r\n'
        b'Date: X\r\n'
        b'\r\n'
    ),
    (
        b'HTTP/1.0 200 OK\r\n'
        b'content-length: 2\r\n'
        b'Server: gunicorn/asgi\r\n'
        b'Date: X\r\n'
        b'Connection: close\r\n'
        b'\r\n'
        b'ok'
    ),
    (
        b'HTTP/1.1 200 OK\r\n'
        b'server: custom\r\n'
        b'date: Mon, 01 Jan 2024 00:00:00 GMT\r\n'
        b'content-length: 1\r\n'
        b'\r\n'
        b'z'
    ),
    (
        b'HTTP/1.1 500 Internal Server Error\r\n'
        b'Content-Type: text/plain\r\n'
        b'Content-Length: 21\r\n'
        b'Connection: close\r\n'
        b'\r\n'
        b'Internal Server Error'
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("index", range(len(CASES)))
async def test_response_bytes_unchanged(http_parser, index):
    method, version, status, headers, bodies = CASES[index]

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": status, "headers": headers})
        for i, body in enumerate(bodies):
            await send({"type": "http.response.body", "body": body,
                        "more_body": i < len(bodies) - 1})

    loop = asyncio.get_event_loop()
    protocol = ASGIProtocol(_build_worker(loop, app, http_parser))
    transport = _FakeTransport()
    protocol.connection_made(transport)
    protocol.data_received(("%s / HTTP/%s\r\nHost: a\r\n\r\n" % (method, version)).encode())
    for _ in range(40):
        await asyncio.sleep(0)
    if protocol._task and not protocol._task.done():
        protocol._task.cancel()
        try:
            await protocol._task
        except (asyncio.CancelledError, Exception):
            pass
    assert re.sub(rb"Date: [^\r]*", b"Date: X", transport.written) == EXPECTED[index]
