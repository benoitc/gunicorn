#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Expect: 100-continue on the ASGI worker's HTTP/1 path (RFC 9110
section 10.1.1): a 100 goes out when the app first asks for a body the
client is holding back, and never when it is not needed."""

import asyncio

import pytest

from gunicorn.asgi.protocol import ASGIProtocol
from test_asgi_keepalive_smuggling import (
    _FakeTransport, _build_worker, http_parser,  # noqa: F401 (fixture)
)

CONTINUE = b"HTTP/1.1 100 Continue\r\n\r\n"


async def _echo(scope, receive, send):
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if not message.get("more_body"):
            break
    await send({"type": "http.response.start", "status": 200,
                "headers": [(b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


async def _reject(scope, receive, send):
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-length", b"0")]})
    await send({"type": "http.response.body", "body": b""})


async def _wait_for(predicate, timeout=2.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            return False
        await asyncio.sleep(0.005)
    return True


def _start(app, http_parser, head):
    loop = asyncio.get_running_loop()
    protocol = ASGIProtocol(_build_worker(loop, app, http_parser))
    transport = _FakeTransport()
    protocol.connection_made(transport)
    protocol.data_received(head)
    return protocol, transport


async def _finish(protocol):
    protocol.connection_lost(None)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_continue_sent_before_the_body(http_parser):
    protocol, transport = _start(_echo, http_parser, (
        b"POST / HTTP/1.1\r\nHost: a\r\nContent-Length: 5\r\n"
        b"Expect: 100-continue\r\n\r\n"))
    try:
        assert await _wait_for(lambda: transport.written == CONTINUE)
        protocol.data_received(b"hello")
        assert await _wait_for(lambda: transport.written.endswith(b"hello"))
        assert transport.written.startswith(CONTINUE + b"HTTP/1.1 200 OK\r\n")
        assert transport.written.count(b"100 Continue") == 1
    finally:
        await _finish(protocol)


@pytest.mark.asyncio
async def test_expect_value_is_case_insensitive(http_parser):
    protocol, transport = _start(_echo, http_parser, (
        b"POST / HTTP/1.1\r\nHost: a\r\nContent-Length: 2\r\n"
        b"Expect: 100-Continue\r\n\r\n"))
    try:
        assert await _wait_for(lambda: transport.written == CONTINUE)
        protocol.data_received(b"ok")
        assert await _wait_for(lambda: transport.written.endswith(b"ok"))
    finally:
        await _finish(protocol)


@pytest.mark.asyncio
async def test_no_continue_when_the_app_answers_first(http_parser):
    protocol, transport = _start(_reject, http_parser, (
        b"POST / HTTP/1.1\r\nHost: a\r\nContent-Length: 5\r\n"
        b"Expect: 100-continue\r\n\r\n"))
    try:
        assert await _wait_for(lambda: b"413" in transport.written)
        assert transport.written.startswith(b"HTTP/1.1 413 ")
        assert b"100 Continue" not in transport.written
    finally:
        await _finish(protocol)


@pytest.mark.asyncio
async def test_no_continue_when_the_body_came_with_the_headers(http_parser):
    protocol, transport = _start(_echo, http_parser, (
        b"POST / HTTP/1.1\r\nHost: a\r\nContent-Length: 5\r\n"
        b"Expect: 100-continue\r\n\r\nhello"))
    try:
        assert await _wait_for(lambda: transport.written.endswith(b"hello"))
        assert b"100 Continue" not in transport.written
    finally:
        await _finish(protocol)


@pytest.mark.asyncio
async def test_no_continue_without_a_body(http_parser):
    protocol, transport = _start(_echo, http_parser, (
        b"POST / HTTP/1.1\r\nHost: a\r\nContent-Length: 0\r\n"
        b"Expect: 100-continue\r\n\r\n"))
    try:
        assert await _wait_for(lambda: b"200 OK" in transport.written)
        assert b"100 Continue" not in transport.written
    finally:
        await _finish(protocol)


@pytest.mark.asyncio
async def test_http10_expectation_is_ignored(http_parser):
    protocol, transport = _start(_echo, http_parser, (
        b"POST / HTTP/1.0\r\nHost: a\r\nContent-Length: 5\r\n"
        b"Expect: 100-continue\r\n\r\n"))
    try:
        await asyncio.sleep(0.05)
        assert transport.written == b""
        protocol.data_received(b"hello")
        assert await _wait_for(lambda: transport.written.endswith(b"hello"))
        assert b"100 Continue" not in transport.written
    finally:
        await _finish(protocol)


@pytest.mark.asyncio
async def test_continue_with_chunked_body(http_parser):
    protocol, transport = _start(_echo, http_parser, (
        b"POST / HTTP/1.1\r\nHost: a\r\nTransfer-Encoding: chunked\r\n"
        b"Expect: 100-continue\r\n\r\n"))
    try:
        assert await _wait_for(lambda: transport.written == CONTINUE)
        protocol.data_received(b"5\r\nhello\r\n0\r\n\r\n")
        assert await _wait_for(lambda: transport.written.endswith(b"hello"))
    finally:
        await _finish(protocol)
