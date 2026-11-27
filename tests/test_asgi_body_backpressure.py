#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""The ASGI worker holds at most a bounded amount of an HTTP/1 request body
the application has not received: past it, reading from the socket pauses,
and it resumes as the application catches up."""

import asyncio

import pytest

from gunicorn.asgi.protocol import ASGIProtocol, BodyReceiver
from test_asgi_keepalive_smuggling import (
    _FakeTransport, _build_worker, http_parser,  # noqa: F401 (fixture)
)


class _PausableTransport(_FakeTransport):
    def __init__(self):
        super().__init__()
        self.paused = False
        self.pauses = 0

    def pause_reading(self):
        self.paused = True
        self.pauses += 1

    def resume_reading(self):
        self.paused = False


async def _spin(n=20):
    for _ in range(n):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_unread_body_pauses_reading_and_resumes(http_parser):
    release = asyncio.Event()
    got = bytearray()

    async def app(scope, receive, send):
        await release.wait()
        while True:
            message = await receive()
            got.extend(message.get("body", b""))
            if not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-length", b"0")]})
        await send({"type": "http.response.body", "body": b""})

    size = 1024 * 1024
    loop = asyncio.get_event_loop()
    protocol = ASGIProtocol(_build_worker(loop, app, http_parser))
    transport = _PausableTransport()
    protocol.connection_made(transport)
    protocol.data_received(
        b"POST / HTTP/1.1\r\nHost: a\r\nContent-Length: %d\r\n\r\n" % size)
    await _spin()

    sent = 0
    while sent < size and not transport.paused:
        protocol.data_received(b"x" * 4096)
        sent += 4096
    assert transport.paused, "reading never paused"
    assert protocol._body_receiver.buffered <= protocol._max_buffer_size + 4096

    # The app starts reading: reading resumes, the rest of the body arrives.
    release.set()
    while sent < size:
        await _spin(5)
        if not transport.paused:
            protocol.data_received(b"x" * 4096)
            sent += 4096
    await _spin(40)

    assert bytes(got) == b"x" * size
    assert transport.written.startswith(b"HTTP/1.1 200")
    if protocol._task and not protocol._task.done():
        protocol._task.cancel()


@pytest.mark.asyncio
async def test_receiver_pulls_from_source_on_demand():
    """uWSGI bodies are read as the app asks, not all before it starts."""
    pieces = [b"ab", b"cd", b""]
    reads = []

    async def source():
        reads.append(1)
        return pieces.pop(0)

    class _Req:
        content_length = 4
        chunked = False

    class _Proto:
        _closed = False

        def _maybe_resume_reading(self):
            pass

    receiver = BodyReceiver(_Req(), _Proto())
    receiver._source = source
    assert reads == []
    first = await receiver.receive()
    assert first == {"type": "http.request", "body": b"ab", "more_body": True}
    assert len(reads) == 1
    assert (await receiver.receive())["body"] == b"cd"
    assert await receiver.receive() == {"type": "http.request", "body": b"", "more_body": False}
