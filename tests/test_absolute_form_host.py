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
