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


class _RecordingTransport(_FakeTransport):
    """Keeps every buffer handed to write() or writelines() as it was."""

    def __init__(self):
        super().__init__()
        self.buffers = []

    def write(self, data):
        self.buffers.append(data)
        super().write(data)

    def writelines(self, list_of_data):
        for data in list_of_data:
            self.write(data)


LARGE = b"L" * (1 << 20)
SMALL_CHUNK = b"s" * 4096


async def _serve(http_parser, app):
    loop = asyncio.get_event_loop()
    protocol = ASGIProtocol(_build_worker(loop, app, http_parser))
    transport = _RecordingTransport()
    protocol.connection_made(transport)
    protocol.data_received(b"GET / HTTP/1.1\r\nHost: a\r\n\r\n")
    for _ in range(40):
        await asyncio.sleep(0)
    if protocol._task and not protocol._task.done():
        protocol._task.cancel()
        try:
            await protocol._task
        except (asyncio.CancelledError, Exception):
            pass
    head, _, body = re.sub(rb"Date: [^\r]*", b"Date: X", transport.written).partition(b"\r\n\r\n")
    return transport, head, body


@pytest.mark.asyncio
async def test_large_body_with_content_length_is_not_copied(http_parser):
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-length", str(len(LARGE)).encode())]})
        await send({"type": "http.response.body", "body": LARGE})

    transport, head, body = await _serve(http_parser, app)
    assert head == (b"HTTP/1.1 200 OK\r\ncontent-length: 1048576\r\n"
                    b"Server: gunicorn/asgi\r\nDate: X")
    assert body == LARGE
    assert any(buf is LARGE for buf in transport.buffers)


@pytest.mark.asyncio
async def test_large_chunk_is_not_copied(http_parser):
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": SMALL_CHUNK, "more_body": True})
        await send({"type": "http.response.body", "body": LARGE, "more_body": True})
        await send({"type": "http.response.body", "body": b""})

    transport, head, body = await _serve(http_parser, app)
    assert head == (b"HTTP/1.1 200 OK\r\ntransfer-encoding: chunked\r\n"
                    b"Server: gunicorn/asgi\r\nDate: X")
    assert body == (b"1000\r\n" + SMALL_CHUNK + b"\r\n"
                    b"100000\r\n" + LARGE + b"\r\n0\r\n\r\n")
    assert any(buf is LARGE for buf in transport.buffers)
    # A small chunk still goes out in one buffer with the headers.
    assert transport.buffers[0].endswith(b"\r\n\r\n1000\r\n" + SMALL_CHUNK + b"\r\n")
