#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""RFC 9112 section 2.2: lines end with CRLF. A bare LF is rejected at once
by the three HTTP/1 parsers (WSGI, ASGI Python, gunicorn_h1c) instead of
one of them waiting for a CRLF that never comes."""

import pytest

from gunicorn.asgi.parser import ParseError, PythonProtocol
from gunicorn.config import Config
from gunicorn.http.errors import NoMoreData
from gunicorn.http.parser import RequestParser

CHUNKED = b"POST / HTTP/1.1\r\nHost: a\r\nTransfer-Encoding: chunked\r\n\r\n"

BARE_LF = {
    "request line": b"GET / HTTP/1.1\nHost: a\r\n\r\n",
    "header line": b"GET / HTTP/1.1\r\nHost: a\nX: 1\r\n\r\n",
    "end of head": b"GET / HTTP/1.1\r\nHost: a\r\n\n",
    "every line": b"GET / HTTP/1.1\nHost: a\n\n",
    "chunk size line": CHUNKED + b"1\nx\r\n0\r\n\r\n",
    "last chunk": CHUNKED + b"1\r\nx\r\n0\n\r\n",
    "trailer": CHUNKED + b"0\r\nX-T: 1\n\r\n",
}


class _NoMoreReads:
    """Hands out the request, then fails the test if the parser asks for
    more: a parser that waits for a CRLF would."""

    def __init__(self, data):
        self.data = [data]

    def __iter__(self):
        return self

    def __next__(self):
        if self.data:
            return self.data.pop()
        raise AssertionError("the parser waited for more data")


@pytest.mark.parametrize("raw", list(BARE_LF.values()), ids=list(BARE_LF))
def test_wsgi_rejects_bare_lf(raw):
    cfg = Config()
    cfg.set("http_parser", "python")
    with pytest.raises(Exception) as excinfo:
        req = next(RequestParser(cfg, _NoMoreReads(raw), None))
        req.body.read()
    assert not isinstance(excinfo.value, (NoMoreData, AssertionError)), excinfo.value


@pytest.mark.parametrize("raw", list(BARE_LF.values()), ids=list(BARE_LF))
def test_asgi_python_rejects_bare_lf(raw):
    with pytest.raises(ParseError):
        PythonProtocol().feed(raw)


@pytest.mark.parametrize("raw", list(BARE_LF.values()), ids=list(BARE_LF))
def test_gunicorn_h1c_rejects_bare_lf(raw):
    gunicorn_h1c = pytest.importorskip("gunicorn_h1c")
    with pytest.raises(Exception):
        gunicorn_h1c.H1CProtocol().feed(raw)


def test_crlf_request_still_parses():
    p = PythonProtocol()
    p.feed(b"GET / HTTP/1.1\r\nHost: a\r\nX: 1\r\n\r\n")
    assert p.is_complete

    cfg = Config()
    cfg.set("http_parser", "python")
    req = next(RequestParser(cfg, [b"GET /x HTTP/1.1\r\nHost: a\r\n\r\n"], None))
    assert req.path == "/x"
