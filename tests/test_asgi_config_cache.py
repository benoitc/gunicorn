#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Settings the ASGI worker needs on every request are read once per
connection (a configuration reload starts new workers), and the access-log
switch once per Logger.setup() (which a reload runs)."""

import asyncio
from unittest import mock

import pytest

from gunicorn import config as gconfig
from gunicorn.asgi.protocol import ASGIProtocol
from gunicorn.config import Config
from gunicorn.glogging import Logger
from test_asgi_keepalive_smuggling import (
    _FakeTransport, _build_worker, http_parser,  # noqa: F401 (fixture)
)

REQUEST = b"GET / HTTP/1.1\r\nHost: a\r\nX-Forwarded-Proto: https\r\n\r\n"


async def _app(scope, receive, send):
    body = ("scheme=%s;" % scope["scheme"]).encode()
    await send({"type": "http.response.start", "status": 200,
                "headers": [(b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


async def _serve(protocol, transport, count):
    for _ in range(count):
        before = transport.written.count(b"HTTP/1.1 200")
        protocol.data_received(REQUEST)
        for _ in range(50):
            await asyncio.sleep(0)
            if transport.written.count(b"HTTP/1.1 200") > before:
                break


async def _connection(http_parser, peer="127.0.0.1", **settings):
    loop = asyncio.get_event_loop()
    worker = _build_worker(loop, _app, http_parser)
    for name, value in settings.items():
        worker.cfg.set(name, value)
    protocol = ASGIProtocol(worker)
    transport = _FakeTransport()
    transport._extra['peername'] = (peer, 40000)
    protocol.connection_made(transport)
    return worker, protocol, transport


async def _done(protocol):
    if protocol._task and not protocol._task.done():
        protocol._task.cancel()
        try:
            await protocol._task
        except (asyncio.CancelledError, Exception):
            pass


@pytest.mark.asyncio
async def test_no_config_reads_per_request(http_parser):
    worker, protocol, transport = await _connection(http_parser)
    await _serve(protocol, transport, 2)

    reads = []
    original = gconfig.Config.__getattr__

    def counting(self, name):
        reads.append(name)
        return original(self, name)

    with mock.patch.object(gconfig.Config, "__getattr__", counting):
        await _serve(protocol, transport, 10)
    await _done(protocol)
    assert transport.written.count(b"HTTP/1.1 200") == 12
    assert reads == []


@pytest.mark.asyncio
async def test_request_hooks_still_called_every_request(http_parser):
    calls = []

    def pre_request(worker, req):
        calls.append(("pre", worker, req.path))

    def post_request(worker, req, environ, resp):
        calls.append(("post", worker, req.path, environ, resp))

    worker, protocol, transport = await _connection(
        http_parser, pre_request=pre_request, post_request=post_request)
    await _serve(protocol, transport, 3)
    await _done(protocol)
    assert [c[0] for c in calls] == ["pre", "post"] * 3
    assert all(c[1] is worker and c[2] == "/" for c in calls)


@pytest.mark.asyncio
async def test_forwarded_trust_holds_for_every_request(http_parser):
    """Decided once per connection, applied to each of its requests."""
    _, trusted, t1 = await _connection(http_parser, peer="10.0.0.5",
                                       forwarded_allow_ips="10.0.0.5")
    await _serve(trusted, t1, 3)
    await _done(trusted)
    _, untrusted, t2 = await _connection(http_parser, peer="203.0.113.9",
                                         forwarded_allow_ips="10.0.0.5")
    await _serve(untrusted, t2, 3)
    await _done(untrusted)
    assert t1.written.count(b"scheme=https;") == 3
    assert t2.written.count(b"scheme=http;") == 3
    assert b"scheme=https;" not in t2.written


def test_access_log_switch_follows_setup():
    cfg = Config()
    logger = Logger(cfg)
    assert logger.access_log_enabled is False

    cfg.set("accesslog", "-")
    assert logger.access_log_enabled is False  # not until setup() runs
    logger.setup(cfg)
    assert logger.access_log_enabled is True
