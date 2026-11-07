#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""What the ASGI worker puts in an HTTP/1 request scope.

- The forwarded-header policy is the one WSGI and HTTP/2 use: scheme headers
  and underscore names are honored only from peers in ``forwarded_allow_ips``.
- ``scope["state"]`` is a shallow copy of the lifespan state per request.
"""

import asyncio

import pytest

from gunicorn.asgi.protocol import ASGIProtocol
from test_asgi_keepalive_smuggling import (
    _FakeTransport, _build_worker, http_parser,  # noqa: F401 (fixture)
)


async def _scope_for(http_parser, peer, headers, **settings):
    scopes = []

    async def app(scope, receive, send):
        scopes.append(scope)
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-length", b"0")]})
        await send({"type": "http.response.body", "body": b""})

    loop = asyncio.get_event_loop()
    worker = _build_worker(loop, app, http_parser)
    for name, value in settings.items():
        worker.cfg.set(name, value)
    protocol = ASGIProtocol(worker)
    transport = _FakeTransport()
    transport._extra['peername'] = (peer, 40000)
    protocol.connection_made(transport)
    protocol.data_received(b"GET / HTTP/1.1\r\nHost: a\r\n" + headers + b"\r\n")
    for _ in range(40):
        await asyncio.sleep(0)
    if protocol._task and not protocol._task.done():
        protocol._task.cancel()
        try:
            await protocol._task
        except (asyncio.CancelledError, Exception):
            pass
    return scopes, transport


@pytest.mark.asyncio
async def test_untrusted_peer_cannot_set_scheme(http_parser):
    scopes, _ = await _scope_for(
        http_parser, "203.0.113.9", b"X-Forwarded-Proto: https\r\n",
        forwarded_allow_ips="10.0.0.5")
    assert scopes[0]["scheme"] == "http"


@pytest.mark.asyncio
async def test_trusted_proxy_sets_scheme(http_parser):
    scopes, _ = await _scope_for(
        http_parser, "10.0.0.5", b"X-Forwarded-Proto: https\r\n",
        forwarded_allow_ips="10.0.0.5")
    assert scopes[0]["scheme"] == "https"


@pytest.mark.asyncio
async def test_underscore_header_dropped(http_parser):
    scopes, _ = await _scope_for(
        http_parser, "203.0.113.9", b"X_Forwarded_For: 10.0.0.1\r\n",
        forwarded_allow_ips="10.0.0.5")
    names = [n for n, _ in scopes[0]["headers"]]
    assert b"x_forwarded_for" not in names


@pytest.mark.asyncio
async def test_underscore_header_refused(http_parser):
    scopes, transport = await _scope_for(
        http_parser, "203.0.113.9", b"X_Forwarded_For: 10.0.0.1\r\n",
        forwarded_allow_ips="10.0.0.5", header_map="refuse")
    assert scopes == []
    assert transport.written.startswith(b"HTTP/1.1 400"), transport.written


@pytest.mark.asyncio
async def test_lifespan_state_is_copied_per_request(http_parser):
    """ASGI lifespan spec: each request gets a shallow copy of the state, so
    a value one request stores is not seen by the next one."""
    seen = []

    async def app(scope, receive, send):
        seen.append(dict(scope["state"]))
        scope["state"]["user"] = scope["path"]
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-length", b"0")]})
        await send({"type": "http.response.body", "body": b""})

    loop = asyncio.get_event_loop()
    worker = _build_worker(loop, app, http_parser)
    worker.state = {"db": "conn"}
    protocol = ASGIProtocol(worker)
    transport = _FakeTransport()
    protocol.connection_made(transport)
    protocol.data_received(b"GET /a HTTP/1.1\r\nHost: a\r\n\r\n"
                           b"GET /b HTTP/1.1\r\nHost: a\r\n\r\n")
    for _ in range(40):
        await asyncio.sleep(0)
    if protocol._task and not protocol._task.done():
        protocol._task.cancel()
        try:
            await protocol._task
        except (asyncio.CancelledError, Exception):
            pass

    assert seen == [{"db": "conn"}, {"db": "conn"}], seen
    assert worker.state == {"db": "conn"}
