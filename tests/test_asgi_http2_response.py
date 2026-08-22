#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for the ASGI worker's HTTP/2 response path.

This path had no coverage: a change that made every HTTP/2 request return
500 still left the whole suite green.
"""

from unittest import mock

import pytest

from gunicorn.config import Config
from gunicorn.asgi.protocol import ASGIProtocol


def make_protocol(app):
    worker = mock.Mock()
    worker.cfg = Config()
    worker.log = mock.Mock()
    worker.nr_conns = 0
    # ASGIProtocol captures worker.asgi at construction, so the app has to be
    # in place first or it calls a Mock and every request 500s.
    worker.asgi = app
    proto = ASGIProtocol(worker)
    proto.transport = mock.Mock()
    return proto, worker


def make_request():
    req = mock.Mock()
    req.method = "GET"
    req.stream.stream_id = 1
    req.path = "/"
    req.query = ""
    req.headers = []
    req.version = (2, 0)
    req.raw_path = b"/"
    req.scheme = "http"
    req.body = None
    return req


async def run_app(app, method="GET"):
    """Drive _handle_http2_request and report what reached the wire."""
    proto, worker = make_protocol(app)
    h2 = mock.AsyncMock()
    h2.streams = {1: mock.Mock()}
    h2.h2_conn = mock.Mock()
    req = make_request()
    req.method = method
    await proto._handle_http2_request(
        req, h2, ("127.0.0.1", 8000), ("127.0.0.1", 1))
    assert not worker.log.exception.called, (
        "handler raised; a 500 must not be mistaken for a dropped body")
    payloads = [c.args[1] for c in h2.send_data.call_args_list]
    return payloads, worker


def responder(status):
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": b"BODY"})
    return app


class TestASGIHTTP2Response:
    @pytest.mark.asyncio
    async def test_ordinary_response_sends_its_body(self):
        payloads, _ = await run_app(responder(200))
        assert b"BODY" in payloads

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [204, 304])
    async def test_no_body_status_drops_the_body(self, status):
        payloads, _ = await run_app(responder(status))
        assert b"BODY" not in payloads

    @pytest.mark.asyncio
    async def test_head_drops_the_body(self):
        payloads, _ = await run_app(responder(200), method="HEAD")
        assert b"BODY" not in payloads

    @pytest.mark.asyncio
    async def test_dropping_the_body_is_logged_once(self):
        _, worker = await run_app(responder(204))
        warnings = [c for c in worker.log.warning.call_args_list
                    if "no-body response" in str(c)]
        assert len(warnings) == 1

    @pytest.mark.asyncio
    async def test_no_warning_for_an_ordinary_response(self):
        _, worker = await run_app(responder(200))
        assert not [c for c in worker.log.warning.call_args_list
                    if "no-body response" in str(c)]
