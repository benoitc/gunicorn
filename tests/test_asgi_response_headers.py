#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Tests for response header validation in the ASGI worker.

App-supplied header names and values are written to the HTTP/1.1 wire,
so CR/LF or other control characters must be rejected to prevent HTTP
response splitting, as the WSGI Response.process_headers already does.
"""

from unittest import mock

import pytest

from gunicorn.config import Config
from gunicorn.http.errors import InvalidHeader, InvalidHeaderName


def _create_protocol():
    from gunicorn.asgi.protocol import ASGIProtocol

    worker = mock.Mock()
    worker.cfg = Config()
    worker.log = mock.Mock()
    worker.log.access_log_enabled = False
    worker.asgi = mock.Mock()
    worker.nr = 0
    worker.max_requests = 10000
    worker.alive = True
    worker.state = {}

    protocol = ASGIProtocol(worker)
    protocol.transport = mock.Mock()
    protocol._response_buffer = None
    protocol._flow_control = mock.Mock()
    protocol._flow_control.drain = mock.AsyncMock()
    protocol._closed = False
    return protocol


def _create_mock_request():
    request = mock.Mock()
    request.method = "GET"
    request.path = "/"
    request.raw_path = b"/"
    request.query = ""
    request.version = (1, 1)
    request.scheme = "http"
    request.headers = []
    request.uri = "/"
    request.should_close = mock.Mock(return_value=False)
    request.content_length = 0
    request.chunked = False
    return request


async def _run(headers, msg_type="http.response.start"):
    from gunicorn.asgi.protocol import BodyReceiver

    protocol = _create_protocol()
    written = []
    protocol.transport.write = mock.Mock(side_effect=written.append)

    request = _create_mock_request()
    protocol._body_receiver = BodyReceiver(request, protocol)
    protocol._body_receiver.set_complete()

    async def app(scope, receive, send):
        if msg_type == "http.response.informational":
            await send({"type": msg_type, "status": 103, "headers": headers})
            headers_ok = [(b"content-type", b"text/plain")]
        else:
            headers_ok = headers
        await send({"type": "http.response.start", "status": 200,
                    "headers": headers_ok})
        await send({"type": "http.response.body", "body": b"ok"})

    protocol.app = app
    await protocol._handle_http_request(
        request, ("127.0.0.1", 8000), ("127.0.0.1", 50000)
    )
    return b"".join(written)


INVALID_HEADERS = [
    [(b"location", b"/next\r\nSet-Cookie: session=attacker")],
    [(b"x-value", b"a\nb")],
    [(b"x-value", b"a\rb")],
    [(b"x-value", b"a\x00b")],
    [("location", "/next\r\nSet-Cookie: session=attacker")],
    [(b"x-name\r\nset-cookie", b"a")],
    [(b"x name", b"a")],
    [(b"", b"a")],
]


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", INVALID_HEADERS)
async def test_response_start_rejects_invalid_headers(headers):
    response = await _run(headers)

    assert response.startswith(b"HTTP/1.1 500 ")
    assert b"session=attacker" not in response


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", INVALID_HEADERS)
async def test_informational_rejects_invalid_headers(headers):
    response = await _run(headers, msg_type="http.response.informational")

    assert b" 103 " not in response
    assert response.startswith(b"HTTP/1.1 500 ")
    assert b"session=attacker" not in response


@pytest.mark.asyncio
async def test_response_start_valid_headers_pass():
    response = await _run([
        (b"content-type", b"text/plain"),
        (b"x-value", b"tab\tand space and \xe9"),
        ("x-str", "value"),
    ])

    assert response.startswith(b"HTTP/1.1 200 OK\r\n")
    assert b"x-value: tab\tand space and \xe9\r\n" in response
    assert b"x-str: value\r\n" in response


def _create_websocket_protocol():
    from gunicorn.asgi.websocket import WebSocketProtocol

    scope = {
        "type": "websocket",
        "headers": [(b"sec-websocket-key", b"dGhlIHNhbXBsZSBub25jZQ==")],
    }
    protocol = WebSocketProtocol(
        transport=mock.Mock(),
        scope=scope,
        app=mock.AsyncMock(),
        log=mock.Mock(),
    )
    protocol.transport.write = mock.Mock()
    return protocol


@pytest.mark.asyncio
async def test_websocket_accept_rejects_crlf_in_header_value():
    protocol = _create_websocket_protocol()

    with pytest.raises(InvalidHeader):
        await protocol._send({
            "type": "websocket.accept",
            "headers": [(b"x-value", b"a\r\nSet-Cookie: session=attacker")],
        })

    protocol.transport.write.assert_not_called()
    assert protocol.accepted is False


@pytest.mark.asyncio
async def test_websocket_accept_rejects_invalid_header_name():
    protocol = _create_websocket_protocol()

    with pytest.raises(InvalidHeaderName):
        await protocol._send({
            "type": "websocket.accept",
            "headers": [(b"x-name\r\nset-cookie", b"a")],
        })

    protocol.transport.write.assert_not_called()


@pytest.mark.asyncio
async def test_websocket_accept_rejects_crlf_in_subprotocol():
    protocol = _create_websocket_protocol()

    with pytest.raises(InvalidHeader):
        await protocol._send({
            "type": "websocket.accept",
            "subprotocol": "chat\r\nSet-Cookie: session=attacker",
        })

    protocol.transport.write.assert_not_called()


@pytest.mark.asyncio
async def test_websocket_accept_valid_headers_pass():
    protocol = _create_websocket_protocol()

    await protocol._send({
        "type": "websocket.accept",
        "subprotocol": "chat",
        "headers": [(b"x-value", b"ok")],
    })

    data = protocol.transport.write.call_args[0][0]
    assert b"Sec-WebSocket-Protocol: chat\r\n" in data
    assert b"x-value: ok\r\n" in data
    assert protocol.accepted is True
