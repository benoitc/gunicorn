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


CONNECTION_CASES = [
    (b"GET / HTTP/1.1\r\nHost: a\r\n\r\n", False),
    (b"GET / HTTP/1.1\r\nHost: a\r\nConnection: close\r\n\r\n", True),
    (b"GET / HTTP/1.1\r\nHost: a\r\nConnection: Close \r\n\r\n", True),
    (b"GET / HTTP/1.1\r\nHost: a\r\nConnection: keep-alive\r\n"
     b"Connection: close\r\n\r\n", True),
    (b"GET / HTTP/1.0\r\nHost: a\r\n\r\n", True),
    (b"GET / HTTP/1.0\r\nHost: a\r\nConnection: Keep-Alive\r\n\r\n", False),
    (b"GET / HTTP/1.1\r\nHost: a\r\nConnection: upgrade\r\n\r\n", False),
]


def _build(kind, raw):
    parser = _parser(kind)
    parser.feed(raw)
    return CallbackRequest.from_parser(parser)


@pytest.mark.parametrize("kind", PARSERS)
def test_str_headers_built_only_when_read(kind):
    req = _build(kind, REQUESTS[4])
    assert req._headers is None
    assert req.headers == [
        ("HOST", "a"), ("CONTENT-TYPE", "text/plain"),
        ("EXPECT", "100-Continue"), ("CONTENT-LENGTH", "0"),
        ("X-DUP", "1"), ("X-DUP", "2"), ("X_UNDER", "v"),
        ("COOKIE", "a=1"), ("COOKIE", "b=2")]
    assert req.headers is req.headers


@pytest.mark.parametrize("kind", PARSERS)
@pytest.mark.parametrize("raw,closes", CONNECTION_CASES)
def test_should_close_without_and_with_str_headers(kind, raw, closes):
    req = _build(kind, raw)
    assert req.should_close() is closes
    req.headers  # pylint: disable=pointless-statement
    assert req.should_close() is closes


@pytest.mark.parametrize("kind", PARSERS)
def test_should_close_sees_headers_changed_after_reading(kind):
    req = _build(kind, CONNECTION_CASES[0][0])
    req.headers.append(("CONNECTION", "close"))
    assert req.should_close() is True


@pytest.mark.parametrize("kind", PARSERS)
def test_may_upgrade(kind):
    assert _build(kind, CONNECTION_CASES[0][0]).may_upgrade() is False
    assert _build(kind, (b"GET / HTTP/1.1\r\nHost: a\r\nUpgrade: websocket\r\n"
                         b"Connection: Upgrade\r\n\r\n")).may_upgrade() is True
    req = _build(kind, CONNECTION_CASES[0][0])
    req.headers.append(("UPGRADE", "websocket"))
    assert req.may_upgrade() is True


def test_request_built_by_hand_reads_its_str_headers():
    req = CallbackRequest()
    req.version = (1, 1)
    req.headers = [("CONNECTION", "close"), ("UPGRADE", "websocket")]
    assert req.should_close() is True
    assert req.may_upgrade() is True


def _old_apply(policy, request, trust):
    """_RequestHeaderPolicy.apply() as it was, on the str headers."""
    secure_scheme_headers, forwarder_headers = trust
    scheme_state = [False]
    seen = set()
    keep = []
    for name, value in request.headers:
        if '_' in name or name in secure_scheme_headers:
            keep.append(policy._apply_header_policy(
                name, value, scheme_state, seen,
                secure_scheme_headers, forwarder_headers) is not None)
        else:
            keep.append(True)
    if not all(keep):
        request.headers = [h for h, k in zip(request.headers, keep) if k]
        request.headers_bytes = [
            h for h, k in zip(request.headers_bytes, keep) if k]
    request.scheme = policy.scheme


POLICY_REQUESTS = [
    REQUESTS[4],
    (b"GET / HTTP/1.1\r\nHost: a\r\nX-Forwarded-Proto: https\r\n"
     b"X_Forwarded_For: 1.2.3.4\r\nAccept: */*\r\n\r\n"),
    (b"GET / HTTP/1.1\r\nHost: a\r\nX-Forwarded-Proto: http\r\n"
     b"X-Forwarded-Ssl: on\r\n\r\n"),
    (b"GET / HTTP/1.1\r\nHost: a\r\nX-FORWARDED-PROTOCOL: ssl\r\n\r\n"),
]


def _outcome(fn):
    try:
        return fn()
    except Exception as exc:  # pylint: disable=broad-except
        return type(exc)


@pytest.mark.parametrize("kind", PARSERS)
@pytest.mark.parametrize("raw", POLICY_REQUESTS)
@pytest.mark.parametrize("header_map", ["drop", "refuse", "dangerous"])
@pytest.mark.parametrize("peer", ["127.0.0.1", "10.9.9.9"])
@pytest.mark.parametrize("read_first", [False, True])
def test_header_policy_same_as_before(kind, raw, header_map, peer, read_first):
    from gunicorn.asgi.protocol import _RequestHeaderPolicy
    from gunicorn.config import Config

    cfg = Config()
    cfg.set("header_map", header_map)

    def run(apply):
        req = _build(kind, raw)
        if read_first:
            req.headers  # pylint: disable=pointless-statement
        policy = _RequestHeaderPolicy(cfg, (peer, 1234), req.scheme, req.version)
        trust = policy._peer_trusted_for_forwarded()
        outcome = _outcome(lambda: apply(policy, req, trust))
        return outcome, req.scheme, req.headers_bytes, req.headers

    assert run(lambda p, r, t: p.apply(r, t)) == run(_old_apply)
