#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from unittest import mock

from gunicorn.config import Config
from gunicorn.http.message import Request
from gunicorn.http.unreader import IterUnreader
from gunicorn.http.wsgi import create


def _parse(raw, http_parser):
    cfg = Config()
    cfg.set('http_parser', http_parser)
    unreader = IterUnreader([raw])
    return Request(cfg, unreader, ('203.0.113.5', 51000)), cfg


def _environ_for(req, cfg):
    sock = mock.Mock()
    sock.getsockname.return_value = ('127.0.0.1', 8000)
    _, environ = create(req, sock, ('203.0.113.5', 51000), ('127.0.0.1', 8000), cfg)
    return environ


def test_absolute_form_authority_overrides_mismatched_host(http_parser):
    # rfc9112 3.2.2: the origin server MUST ignore a Host header that
    # disagrees with an absolute-form request-target's own authority.
    raw = (b"GET http://evil.com/page HTTP/1.1\r\n"
           b"Host: victim.com\r\n"
           b"\r\n")
    req, cfg = _parse(raw, http_parser)
    assert req.authority == 'evil.com'
    environ = _environ_for(req, cfg)
    assert environ['HTTP_HOST'] == 'evil.com'


def test_origin_form_still_uses_host_header(http_parser):
    # An ordinary request (the overwhelming majority of traffic) has no
    # authority of its own, so nothing here should change its behavior.
    raw = (b"GET /page HTTP/1.1\r\n"
           b"Host: victim.com\r\n"
           b"\r\n")
    req, cfg = _parse(raw, http_parser)
    assert req.authority is None
    environ = _environ_for(req, cfg)
    assert environ['HTTP_HOST'] == 'victim.com'


def test_origin_form_query_string_containing_scheme_is_not_mistaken_for_absolute_form(http_parser):
    # A path like this has "://" sitting right there in the query string,
    # but it's still origin-form (it starts with "/"), so it must not be
    # treated as if it carried its own authority.
    raw = (b"GET /redirect?url=http://evil.com HTTP/1.1\r\n"
           b"Host: victim.com\r\n"
           b"\r\n")
    req, cfg = _parse(raw, http_parser)
    assert req.authority is None
    environ = _environ_for(req, cfg)
    assert environ['HTTP_HOST'] == 'victim.com'


def test_absolute_form_with_empty_authority_sends_empty_host(http_parser):
    # rfc9112 3.2.2 again: "if the request-target does not have an
    # authority component, an empty Host header field will be sent in
    # this case." Falling back to the client's Host header here would be
    # exactly the bug this whole PR is about, just with an edge case
    # authority instead of a missing one.
    raw = (b"GET https:// HTTP/1.1\r\n"
           b"Host: victim.com\r\n"
           b"\r\n")
    req, cfg = _parse(raw, http_parser)
    assert req.authority == ''
    environ = _environ_for(req, cfg)
    assert environ['HTTP_HOST'] == ''


def test_absolute_form_authority_strips_userinfo_before_becoming_host(http_parser):
    # netloc includes userinfo when present, but Host has no such thing,
    # so "user:pass@host:8080" needs to become "host:8080", not get
    # copied into HTTP_HOST verbatim.
    raw = (b"GET http://user:pass@host.example:8080/p HTTP/1.1\r\n"
           b"Host: victim.com\r\n"
           b"\r\n")
    req, cfg = _parse(raw, http_parser)
    assert req.authority == 'user:pass@host.example:8080'
    environ = _environ_for(req, cfg)
    assert environ['HTTP_HOST'] == 'host.example:8080'
