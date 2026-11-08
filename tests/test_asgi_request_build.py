#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""CallbackRequest.from_parser() builds the same request as before its
single-pass rewrite, for both parsers."""

from urllib.parse import unquote_to_bytes

import pytest

from gunicorn.asgi.parser import CallbackRequest, PythonProtocol

try:
    import gunicorn_h1c
except ImportError:  # pragma: no cover
    gunicorn_h1c = None

PARSERS = ["python"] + (["fast"] if gunicorn_h1c else [])

REQUESTS = [
    b"GET / HTTP/1.1\r\nHost: a\r\n\r\n",
    b"GET /a%20b/caf%C3%A9?x=1&y=%20 HTTP/1.1\r\nHost: a\r\n\r\n",
    b"GET /plain/path?q=a%2Fb HTTP/1.1\r\nHost: a\r\nAccept: */*\r\n\r\n",
    b"GET /%ZZbad HTTP/1.1\r\nHost: a\r\n\r\n",
    (b"POST /up HTTP/1.1\r\nHost: a\r\nContent-Type: text/plain\r\n"
     b"Expect: 100-Continue\r\nContent-Length: 0\r\nX-Dup: 1\r\nX-Dup: 2\r\n"
     b"X_Under: v\r\nCookie: a=1\r\nCookie: b=2\r\n\r\n"),
    b"GET / HTTP/1.0\r\nHost: a\r\nConnection: keep-alive\r\n\r\n",
]


def _parser(kind):
    return PythonProtocol() if kind == "python" else gunicorn_h1c.H1CProtocol()


def _reference(parser, is_ssl=False):
    """The request fields as from_parser() computed them before."""
    raw_url = parser.path
    if b'?' in raw_url:
        path_part, query_part = raw_url.split(b'?', 1)
        path = unquote_to_bytes(path_part).decode('utf-8', errors='replace')
        query = query_part.decode('latin-1')
    else:
        path_part = raw_url
        path = unquote_to_bytes(raw_url).decode('utf-8', errors='replace')
        query = ''
    return {
        "method": parser.method.decode('ascii'),
        "raw_path": path_part,
        "path": path,
        "query": query,
        "uri": raw_url.decode('latin-1'),
        "version": parser.http_version,
        "headers_bytes": list(getattr(parser, 'asgi_headers', None) or parser.headers),
        "headers": [(n.decode('latin-1').upper(), v.decode('latin-1'))
                    for n, v in parser.headers],
        "scheme": 'https' if is_ssl else 'http',
        "must_close": not parser.should_keep_alive,
        "chunked": parser.is_chunked,
        "content_length": parser.content_length or 0,
    }


@pytest.mark.parametrize("kind", PARSERS)
@pytest.mark.parametrize("raw", REQUESTS)
def test_same_request_as_before(kind, raw):
    parser = _parser(kind)
    parser.feed(raw)
    req = CallbackRequest.from_parser(parser)
    for field, expected in _reference(parser).items():
        assert getattr(req, field) == expected, field


@pytest.mark.parametrize("kind", PARSERS)
def test_expect_continue_detected_by_both_parsers(kind):
    parser = _parser(kind)
    parser.feed(REQUESTS[4])
    assert CallbackRequest.from_parser(parser)._expect_100_continue is True


@pytest.mark.parametrize("kind", PARSERS)
def test_parser_reset_does_not_touch_an_earlier_request(kind):
    parser = _parser(kind)
    parser.feed(REQUESTS[4])
    req = CallbackRequest.from_parser(parser)
    headers, headers_bytes = list(req.headers), list(req.headers_bytes)
    parser.reset()
    parser.feed(b"GET /other HTTP/1.1\r\nHost: b\r\n\r\n")
    CallbackRequest.from_parser(parser)
    assert req.headers == headers
    assert req.headers_bytes == headers_bytes
    assert req.path == "/up"
