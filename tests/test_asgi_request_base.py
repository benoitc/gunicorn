#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""What the per-request fast paths of the ASGI worker must keep: the
keep-alive decision follows the worker and the hooks, hooks that do
nothing are skipped and others are not, and response bodies are sent as
the app gave them."""

import asyncio

import pytest

from gunicorn.asgi.protocol import ASGIProtocol, _post_request_hook
from gunicorn.config import Config
from test_asgi_keepalive_smuggling import (
    _FakeTransport, _build_worker, http_parser,  # noqa: F401 (fixture)
)

REQUEST = b"GET / HTTP/1.1\r\nHost: a\r\n\r\n"


def _ok(body=b"ok"):
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
    return app


async def _connection(http_parser, app, transport_class=_FakeTransport, **settings):
    loop = asyncio.get_event_loop()
    worker = _build_worker(loop, app, http_parser)
    for name, value in settings.items():
        worker.cfg.set(name, value)
    protocol = ASGIProtocol(worker)
    transport = transport_class()
    protocol.connection_made(transport)
    return worker, protocol, transport


async def _settle():
    for _ in range(50):
        await asyncio.sleep(0)


async def _done(protocol):
    if protocol._task and not protocol._task.done():
        protocol._task.cancel()
        try:
            await protocol._task
        except (asyncio.CancelledError, Exception):
            pass


@pytest.mark.asyncio
async def test_keepalive_after_a_normal_response(http_parser):
    _, protocol, transport = await _connection(http_parser, _ok())
    protocol.data_received(REQUEST)
    await _settle()
    protocol.data_received(REQUEST)
    await _settle()
    await _done(protocol)
    assert transport.written.count(b"HTTP/1.1 200 OK") == 2
    assert b"Connection: close" not in transport.written


@pytest.mark.asyncio
async def test_worker_stopping_mid_request_closes(http_parser):
    worker = None

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-length", b"2")]})
        worker.alive = False  # e.g. a graceful shutdown started
        await send({"type": "http.response.body", "body": b"ok"})

    worker, protocol, transport = await _connection(http_parser, app)
    protocol.data_received(REQUEST)
    await _settle()
    assert transport.closed or protocol._task.done()
    await _done(protocol)


@pytest.mark.asyncio
async def test_max_requests_reached_by_another_connection_closes(http_parser):
    worker = None

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-length", b"2")]})
        worker.nr = worker.max_requests - 1  # other connections served
        await send({"type": "http.response.body", "body": b"ok"})

    worker, protocol, transport = await _connection(http_parser, app)
    protocol.data_received(REQUEST)
    await _settle()
    assert protocol._task.done()
    await _done(protocol)


@pytest.mark.asyncio
async def test_hook_editing_connection_header_is_seen(http_parser):
    def post_request(worker, req, environ, resp):
        req.headers.append(("CONNECTION", "close"))

    _, protocol, transport = await _connection(
        http_parser, _ok(), post_request=post_request)
    protocol.data_received(REQUEST)
    await _settle()
    assert protocol._task.done()
    await _done(protocol)


@pytest.mark.asyncio
async def test_custom_hooks_called_default_post_request_skipped(http_parser):
    calls = []

    def post_request(worker, req, environ, resp):
        calls.append(req.path)

    _, protocol, _ = await _connection(http_parser, _ok(), post_request=post_request)
    assert protocol._post_request is post_request
    protocol.data_received(REQUEST)
    await _settle()
    await _done(protocol)
    assert calls == ["/"]

    assert _post_request_hook(Config()) is None


@pytest.mark.asyncio
async def test_access_log_still_gets_the_request_time(http_parser):
    seen = []

    _, protocol, _ = await _connection(http_parser, _ok())

    class _AccessLog:
        access_log_enabled = True

        def access(self, resp, req, environ, request_time):
            seen.append(request_time)

        def __getattr__(self, name):
            return lambda *a, **k: None

    protocol.log = _AccessLog()
    protocol.data_received(REQUEST)
    await _settle()
    await _done(protocol)
    assert len(seen) == 1
    assert seen[0].seconds >= 0 and seen[0].microseconds >= 0


@pytest.mark.asyncio
async def test_body_longer_than_content_length_is_cut(http_parser):
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-length", b"3")]})
        await send({"type": "http.response.body", "body": b"ab", "more_body": True})
        await send({"type": "http.response.body", "body": b"cdef"})

    _, protocol, transport = await _connection(http_parser, app)
    protocol.data_received(REQUEST)
    await _settle()
    await _done(protocol)
    assert transport.written.endswith(b"\r\n\r\nabc")
