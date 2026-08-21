#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for the HTTP/2 WSGI response writer."""

from unittest import mock

import pytest

from gunicorn.config import Config
from gunicorn.http2.response import HTTP2Response


def make_response(method="GET", status="200 OK", headers=None, cfg=None):
    req = mock.Mock()
    req.method = method
    req.version = (2, 0)
    conn = mock.Mock()
    resp = HTTP2Response(req, None, cfg or Config(), conn, 1)
    resp.start_response(status, headers or [("Content-Type", "text/plain")])
    return resp, conn


def sent_data(conn):
    return [c.args[1] for c in conn.send_data.call_args_list]


class TestStreaming:
    """Bodies go out as they are produced, not collected first."""

    def test_each_write_is_its_own_frame(self):
        resp, conn = make_response()
        resp.write(b"one")
        resp.write(b"two")
        resp.write(b"three")
        assert sent_data(conn) == [b"one", b"two", b"three"]

    def test_headers_sent_once_before_the_first_frame(self):
        resp, conn = make_response()
        resp.write(b"a")
        resp.write(b"b")
        assert conn.send_response_headers.call_count == 1

    def test_close_ends_the_stream(self):
        resp, conn = make_response()
        resp.write(b"a")
        resp.close()
        assert conn.end_stream.call_count == 1

    def test_close_is_idempotent(self):
        resp, conn = make_response()
        resp.close()
        resp.close()
        assert conn.end_stream.call_count == 1

    def test_empty_writes_send_no_frame(self):
        resp, conn = make_response()
        resp.write(b"")
        assert sent_data(conn) == []


class TestNoBodyFraming:
    """HEAD, 204 and 304 carry no body over HTTP/2 either."""

    @pytest.mark.parametrize("method,status", [
        ("HEAD", "200 OK"),
        ("GET", "204 No Content"),
        ("GET", "304 Not Modified"),
    ])
    def test_body_is_dropped(self, method, status):
        resp, conn = make_response(method=method, status=status)
        resp.write(b"should not be sent")
        resp.close()
        assert sent_data(conn) == []

    def test_ordinary_response_still_sends_its_body(self):
        resp, conn = make_response()
        resp.write(b"sent")
        resp.close()
        assert sent_data(conn) == [b"sent"]


class TestFramingRules:
    def test_never_chunked(self):
        # chunked transfer coding is forbidden on HTTP/2 (RFC 9113 8.1)
        resp, _ = make_response()
        assert resp.is_chunked() is False
        assert resp.chunked is False

    def test_never_sendfile(self):
        # raw file bytes would bypass HTTP/2 framing. The base class guards
        # this with cfg.is_ssl, which does not hold for cleartext HTTP/2.
        resp, _ = make_response()
        assert resp.can_sendfile() is False

    def test_sendfile_declines_even_when_enabled(self):
        cfg = Config()
        cfg.set("sendfile", True)
        resp, _ = make_response(cfg=cfg)
        assert resp.can_sendfile() is False


class TestTrailers:
    def test_trailers_passed_to_end_stream(self):
        resp, conn = make_response()
        resp.trailers = [("x-checksum", "abc")]
        resp.write(b"body")
        resp.close()
        assert conn.end_stream.call_args.kwargs["trailers"] == [
            ("x-checksum", "abc")]

    def test_no_trailers_by_default(self):
        resp, conn = make_response()
        resp.close()
        assert conn.end_stream.call_args.kwargs["trailers"] is None
