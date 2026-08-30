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


class TestAbortedStream:
    """A send the connection refused stops the response instead of continuing."""

    def test_failed_send_data_raises_stream_error(self):
        from gunicorn.http2.errors import HTTP2StreamError
        resp, conn = make_response()
        conn.send_response_headers.return_value = True
        conn.send_data.return_value = False
        with pytest.raises(HTTP2StreamError):
            resp.write(b"chunk")

    def test_no_write_after_a_failed_send(self):
        from gunicorn.http2.errors import HTTP2StreamError
        resp, conn = make_response()
        conn.send_response_headers.return_value = True
        conn.send_data.return_value = False
        with pytest.raises(HTTP2StreamError):
            resp.write(b"chunk")
        resp.write(b"more")
        resp.close()
        assert resp.h2_conn.send_data.call_count == 1
        conn.end_stream.assert_not_called()

    def test_refused_headers_raise(self):
        from gunicorn.http2.errors import HTTP2StreamError
        resp, conn = make_response()
        conn.send_response_headers.return_value = False
        with pytest.raises(HTTP2StreamError):
            resp.write(b"chunk")

    def test_failed_end_stream_raises(self):
        from gunicorn.http2.errors import HTTP2StreamError
        resp, conn = make_response()
        conn.send_response_headers.return_value = True
        conn.end_stream.return_value = False
        with pytest.raises(HTTP2StreamError):
            resp.close()


class TestDefaultHeaders:
    def test_server_and_date_are_added(self):
        resp, conn = make_response()
        conn.send_response_headers.return_value = True
        resp.send_headers()
        headers = dict(conn.send_response_headers.call_args[0][2])
        assert headers.get("server") == resp.version
        assert "date" in headers

    def test_app_supplied_values_win(self):
        resp, conn = make_response(headers=[("Server", "mine"), ("Date", "then")])
        conn.send_response_headers.return_value = True
        resp.send_headers()
        names = [name.lower() for name, _ in conn.send_response_headers.call_args[0][2]]
        assert names.count("server") == 1 and names.count("date") == 1
