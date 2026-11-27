#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""RFC 6455 section 4.2.1/4.2.2: the ASGI worker only upgrades a handshake
with version 13 and a key that decodes to 16 bytes."""

import asyncio

import pytest

from gunicorn.asgi.protocol import ASGIProtocol
from test_asgi_keepalive_smuggling import (
    _FakeTransport, _build_worker, http_parser,  # noqa: F401 (fixture)
)

KEY = b"dGhlIHNhbXBsZSBub25jZQ=="


async def _handshake(http_parser, version=b"13", key=KEY):
    accepted = []

    async def app(scope, receive, send):
        if scope["type"] == "websocket":
            await receive()
            accepted.append(True)
            await send({"type": "websocket.accept"})
            await send({"type": "websocket.close", "code": 1000})

    loop = asyncio.get_event_loop()
    protocol = ASGIProtocol(_build_worker(loop, app, http_parser))
    transport = _FakeTransport()
    protocol.connection_made(transport)
    headers = b"GET /ws HTTP/1.1\r\nHost: a\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
    if version is not None:
        headers += b"Sec-WebSocket-Version: " + version + b"\r\n"
    if key is not None:
        headers += b"Sec-WebSocket-Key: " + key + b"\r\n"
    protocol.data_received(headers + b"\r\n")
    for _ in range(40):
        await asyncio.sleep(0)
    if protocol._task and not protocol._task.done():
        protocol._task.cancel()
        try:
            await protocol._task
        except (asyncio.CancelledError, Exception):
            pass
    return transport, accepted


@pytest.mark.asyncio
async def test_valid_handshake_is_upgraded(http_parser):
    transport, accepted = await _handshake(http_parser)
    assert transport.written.startswith(b"HTTP/1.1 101"), transport.written[:80]
    assert accepted == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [None, b"8", b"14"], ids=["missing", "8", "14"])
async def test_other_version_gets_426(http_parser, version):
    transport, accepted = await _handshake(http_parser, version=version)
    assert transport.written.startswith(b"HTTP/1.1 426"), transport.written[:80]
    assert b"Sec-WebSocket-Version: 13\r\n" in transport.written
    assert accepted == []
    assert transport.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("key", [None, b"short", b"!!!notbase64!!!", b"YWJj"],
                         ids=["missing", "short", "not-base64", "3-bytes"])
async def test_bad_key_gets_400(http_parser, key):
    transport, accepted = await _handshake(http_parser, key=key)
    assert transport.written.startswith(b"HTTP/1.1 400"), transport.written[:80]
    assert accepted == []
