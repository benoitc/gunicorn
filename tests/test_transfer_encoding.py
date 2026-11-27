#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Request framing by Transfer-Encoding, the same with every parser:
RFC 9112 section 6.3 (chunked must be the final coding, else 400) and
section 6.1 (a coding the server does not understand: 501)."""

import asyncio

import pytest

from gunicorn.asgi.parser import InvalidHeader as AsgiInvalidHeader
from gunicorn.asgi.parser import PythonProtocol
from gunicorn.asgi.protocol import ASGIProtocol
from gunicorn.config import Config
from gunicorn.http.errors import InvalidHeader
from gunicorn.http.parser import RequestParser
from test_asgi_keepalive_smuggling import (
    _FakeTransport, _build_worker, http_parser,  # noqa: F401 (fixture)
)


def _post(*te_lines, extra=b"", body=b""):
    head = b"POST / HTTP/1.1\r\nHost: a\r\n"
    for te in te_lines:
        head += b"Transfer-Encoding: " + te + b"\r\n"
    return head + extra + b"\r\n" + body


NOT_ENDING_WITH_CHUNKED = {
    "gzip": _post(b"gzip"),
    "deflate": _post(b"deflate"),
    "compress": _post(b"compress"),
    "identity": _post(b"identity"),
    "gzip, identity": _post(b"gzip, identity"),
    "gzip with Content-Length": _post(b"gzip", extra=b"Content-Length: 3\r\n", body=b"abc"),
}

ENDING_WITH_CHUNKED = {
    "chunked": _post(b"chunked", body=b"1\r\nx\r\n0\r\n\r\n"),
    "gzip, chunked": _post(b"gzip, chunked", body=b"1\r\nx\r\n0\r\n\r\n"),
    "identity, chunked": _post(b"identity, chunked", body=b"1\r\nx\r\n0\r\n\r\n"),
    "gzip then chunked on two lines": _post(b"gzip", b"chunked", body=b"1\r\nx\r\n0\r\n\r\n"),
}


def _wsgi(raw, parser="python"):
    cfg = Config()
    cfg.set("http_parser", parser)
    req = next(RequestParser(cfg, [raw], None))
    return req.body.read()


async def _asgi_response(http_parser, raw):
    async def app(scope, receive, send):
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

    loop = asyncio.get_event_loop()
    protocol = ASGIProtocol(_build_worker(loop, app, http_parser))
    transport = _FakeTransport()
    protocol.connection_made(transport)
    protocol.data_received(raw)
    for _ in range(30):
        await asyncio.sleep(0)
    if protocol._task and not protocol._task.done():
        protocol._task.cancel()
        try:
            await protocol._task
        except (asyncio.CancelledError, Exception):
            pass
    return transport


@pytest.mark.parametrize("wsgi_parser", ["python", "fast"])
@pytest.mark.parametrize("raw", list(NOT_ENDING_WITH_CHUNKED.values()),
                         ids=list(NOT_ENDING_WITH_CHUNKED))
def test_wsgi_rejects_transfer_encoding_not_ending_with_chunked(wsgi_parser, raw):
    if wsgi_parser == "fast":
        pytest.importorskip("gunicorn_h1c")
    with pytest.raises(InvalidHeader):
        _wsgi(raw, wsgi_parser)


@pytest.mark.parametrize("raw", list(NOT_ENDING_WITH_CHUNKED.values()),
                         ids=list(NOT_ENDING_WITH_CHUNKED))
def test_asgi_python_rejects_transfer_encoding_not_ending_with_chunked(raw):
    with pytest.raises(AsgiInvalidHeader):
        PythonProtocol().feed(raw)


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", list(NOT_ENDING_WITH_CHUNKED.values()),
                         ids=list(NOT_ENDING_WITH_CHUNKED))
async def test_asgi_worker_answers_400(http_parser, raw):
    transport = await _asgi_response(http_parser, raw)
    assert transport.written.startswith(b"HTTP/1.1 400 Bad Request\r\n")
    assert transport.closed


@pytest.mark.parametrize("wsgi_parser", ["python", "fast"])
@pytest.mark.parametrize("raw", list(ENDING_WITH_CHUNKED.values()),
                         ids=list(ENDING_WITH_CHUNKED))
def test_wsgi_accepts_chunked_as_final_coding(wsgi_parser, raw):
    if wsgi_parser == "fast":
        pytest.importorskip("gunicorn_h1c")
    assert _wsgi(raw, wsgi_parser) == b"x"


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", list(ENDING_WITH_CHUNKED.values()),
                         ids=list(ENDING_WITH_CHUNKED))
async def test_asgi_worker_accepts_chunked_as_final_coding(http_parser, raw):
    transport = await _asgi_response(http_parser, raw)
    assert transport.written.startswith(b"HTTP/1.1 200 OK\r\n")
    assert transport.written.endswith(b"\r\n\r\nx")


UNKNOWN_CODINGS = {
    "foo, chunked": _post(b"foo, chunked", body=b"1\r\nx\r\n0\r\n\r\n"),
    "x-gzip, chunked": _post(b"x-gzip, chunked", body=b"1\r\nx\r\n0\r\n\r\n"),
}


@pytest.mark.parametrize("raw", list(UNKNOWN_CODINGS.values()), ids=list(UNKNOWN_CODINGS))
def test_unknown_coding_wsgi_python_is_501(raw):
    from gunicorn.http.errors import UnsupportedTransferCoding
    with pytest.raises(UnsupportedTransferCoding) as excinfo:
        _wsgi(raw, "python")
    assert excinfo.value.code == 501


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", list(UNKNOWN_CODINGS.values()), ids=list(UNKNOWN_CODINGS))
async def test_unknown_coding_asgi_worker_is_501(http_parser, raw):
    transport = await _asgi_response(http_parser, raw)
    assert transport.written.startswith(b"HTTP/1.1 501 Not Implemented\r\n")
    assert transport.closed


def test_gunicorn_h1c_unsupported_coding_class_gets_501_on_asgi(monkeypatch):
    """Once gunicorn_h1c raises its own UnsupportedTransferCoding, the
    ASGI worker answers 501 instead of 400."""
    class UnsupportedTransferCoding(ValueError):
        pass

    monkeypatch.setattr(ASGIProtocol, "_h1c_unsupported_transfer_coding",
                        UnsupportedTransferCoding)
    protocol = ASGIProtocol.__new__(ASGIProtocol)
    transport = _FakeTransport()
    protocol.transport = transport
    protocol._closed = False
    protocol.log = None
    assert protocol._handle_h1c_exception(UnsupportedTransferCoding("foo"))
    assert transport.written.startswith(b"HTTP/1.1 501 Not Implemented\r\n")


def test_gunicorn_h1c_unsupported_coding_class_gets_501_on_wsgi(monkeypatch):
    gunicorn_h1c = pytest.importorskip("gunicorn_h1c")
    from gunicorn.http.errors import UnsupportedTransferCoding

    class H1cUnsupportedTransferCoding(gunicorn_h1c.InvalidHeader):
        pass

    def parse_request(*args, **kwargs):
        raise H1cUnsupportedTransferCoding("Unsupported Transfer-Encoding")

    monkeypatch.setattr(gunicorn_h1c, "UnsupportedTransferCoding",
                        H1cUnsupportedTransferCoding, raising=False)
    monkeypatch.setattr(gunicorn_h1c, "parse_request", parse_request)
    with pytest.raises(UnsupportedTransferCoding):
        _wsgi(UNKNOWN_CODINGS["foo, chunked"], "fast")
