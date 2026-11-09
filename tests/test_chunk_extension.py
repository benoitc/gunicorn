#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""RFC 9112 section 7.1.1: a chunk extension is ';' name ['=' value], with
a token name and a token or quoted-string value. Anything else is
rejected by the Python parsers."""

import pytest

from gunicorn.asgi.parser import InvalidChunkExtension as AsgiInvalidChunkExtension
from gunicorn.asgi.parser import PythonProtocol
from gunicorn.config import Config
from gunicorn.http.errors import InvalidChunkExtension
from gunicorn.http.parser import RequestParser

HEAD = b"POST / HTTP/1.1\r\nHost: a\r\nTransfer-Encoding: chunked\r\n\r\n"

VALID = {
    "name": b"1;a",
    "token value": b"1;a=b",
    "quoted value": b'1;a="b c"',
    "quoted pair": b'1;a="b\\"c"',
    "tab in quoted": b'1;a="b\tc"',
    "obs-text in quoted": b'1;a="b\xe9"',
    "several": b"1;a=b;c;d=\"e\"",
    "whitespace around = (BWS)": b"1;a = b",
}

INVALID = {
    "control character in name": b"1;a\x01",
    "control character in value": b"1;a=b\x01",
    "DEL in name": b"1;a\x7f",
    "space inside a token value": b"1;a=b c",
    "empty name": b"1;=b",
    "empty extension": b"1;",
    "unclosed quote": b'1;a="b',
    "control character in quoted": b'1;a="b\x01"',
    "separator in name": b"1;a@b",
    "value without name": b"1;a=",
}


def _request(size_line):
    return HEAD + size_line + b"\r\nx\r\n0\r\n\r\n"


def _wsgi(size_line):
    cfg = Config()
    cfg.set("http_parser", "python")
    req = next(RequestParser(cfg, [_request(size_line)], None))
    return req.body.read()


def _asgi(size_line):
    body = []
    p = PythonProtocol(on_body=body.append)
    p.feed(_request(size_line))
    assert p.is_complete
    return b"".join(body)


@pytest.mark.parametrize("size_line", list(VALID.values()), ids=list(VALID))
def test_valid_extension_accepted(size_line):
    assert _wsgi(size_line) == b"x"
    assert _asgi(size_line) == b"x"


@pytest.mark.parametrize("size_line", list(INVALID.values()), ids=list(INVALID))
def test_invalid_extension_rejected_wsgi(size_line):
    with pytest.raises(InvalidChunkExtension):
        _wsgi(size_line)


@pytest.mark.parametrize("size_line", list(INVALID.values()), ids=list(INVALID))
def test_invalid_extension_rejected_asgi(size_line):
    with pytest.raises(AsgiInvalidChunkExtension):
        _asgi(size_line)


@pytest.mark.xfail(reason="gunicorn_h1c does not check the extension grammar yet")
@pytest.mark.parametrize("size_line", list(INVALID.values()), ids=list(INVALID))
def test_invalid_extension_rejected_gunicorn_h1c(size_line):
    gunicorn_h1c = pytest.importorskip("gunicorn_h1c")
    with pytest.raises(gunicorn_h1c.ParseError):
        gunicorn_h1c.H1CProtocol().feed(_request(size_line))
