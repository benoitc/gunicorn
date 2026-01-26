# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for HTTP/2 request and body classes."""

import pytest
from unittest import mock

from gunicorn.http2.request import HTTP2Request, HTTP2Body
from gunicorn.http2.stream import HTTP2Stream


class MockConnection:
    """Mock HTTP/2 connection for testing."""

    def __init__(self, initial_window_size=65535):
        self.initial_window_size = initial_window_size


class MockConfig:
    """Mock gunicorn configuration."""

    def __init__(self):
        pass


class TestHTTP2Body:
    """Test HTTP2Body class."""

    def test_init_with_data(self):
        body = HTTP2Body(b"Hello, World!")
        assert len(body) == 13

    def test_init_empty(self):
        body = HTTP2Body(b"")
        assert len(body) == 0

    def test_read_all(self):
        body = HTTP2Body(b"Test data")
        assert body.read() == b"Test data"
        assert body.read() == b""  # Already consumed

    def test_read_with_size(self):
        body = HTTP2Body(b"Hello, World!")
        assert body.read(5) == b"Hello"
        assert body.read(2) == b", "
        assert body.read(100) == b"World!"
        assert body.read(1) == b""

    def test_read_none_size(self):
        body = HTTP2Body(b"Test")
        assert body.read(None) == b"Test"

    def test_readline_basic(self):
        body = HTTP2Body(b"Line1\nLine2\nLine3")
        assert body.readline() == b"Line1\n"
        assert body.readline() == b"Line2\n"
        assert body.readline() == b"Line3"

    def test_readline_with_size(self):
        body = HTTP2Body(b"Hello\nWorld")
        assert body.readline(3) == b"Hel"
        assert body.readline(10) == b"lo\n"

    def test_readline_no_newline(self):
        body = HTTP2Body(b"No newline here")
        assert body.readline() == b"No newline here"

    def test_readline_empty(self):
        body = HTTP2Body(b"")
        assert body.readline() == b""

    def test_readline_crlf(self):
        body = HTTP2Body(b"Line1\r\nLine2")
        # BytesIO readline includes \r\n
        assert body.readline() == b"Line1\r\n"

    def test_readlines_basic(self):
        body = HTTP2Body(b"Line1\nLine2\nLine3")
        lines = body.readlines()
        assert lines == [b"Line1\n", b"Line2\n", b"Line3"]

    def test_readlines_with_hint(self):
        body = HTTP2Body(b"Line1\nLine2\nLine3\nLine4")
        # Hint affects how many lines are returned
        lines = body.readlines(hint=5)
        assert len(lines) >= 1

    def test_readlines_empty(self):
        body = HTTP2Body(b"")
        assert body.readlines() == []

    def test_iter(self):
        body = HTTP2Body(b"Line1\nLine2\nLine3")
        lines = list(body)
        assert lines == [b"Line1\n", b"Line2\n", b"Line3"]

    def test_len(self):
        body = HTTP2Body(b"12345")
        assert len(body) == 5

    def test_close(self):
        body = HTTP2Body(b"test")
        body.close()
        # Should not raise
        with pytest.raises(ValueError):
            body.read()


class TestHTTP2BodyReadStrategies:
    """Test different reading strategies matching HTTP/1.x patterns."""

    def test_read_all_at_once(self):
        data = b"A" * 1000
        body = HTTP2Body(data)
        result = body.read()
        assert result == data

    def test_read_chunked(self):
        data = b"A" * 100
        body = HTTP2Body(data)
        chunks = []
        while True:
            chunk = body.read(10)
            if not chunk:
                break
            chunks.append(chunk)
        assert b"".join(chunks) == data
        assert len(chunks) == 10

    def test_read_byte_by_byte(self):
        data = b"Hello"
        body = HTTP2Body(data)
        result = []
        for _ in range(len(data)):
            result.append(body.read(1))
        assert b"".join(result) == data

    def test_readline_all_lines(self):
        data = b"Line1\nLine2\nLine3\n"
        body = HTTP2Body(data)
        lines = []
        while True:
            line = body.readline()
            if not line:
                break
            lines.append(line)
        assert lines == [b"Line1\n", b"Line2\n", b"Line3\n"]


class TestHTTP2Request:
    """Test HTTP2Request class."""

    def _make_stream(self, headers, body=b""):
        """Helper to create a stream with headers and body."""
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.receive_headers(headers, end_stream=(len(body) == 0))
        if body:
            stream.request_body.write(body)
            stream.request_complete = True
        return stream

    def test_basic_get_request(self):
        stream = self._make_stream([
            (':method', 'GET'),
            (':path', '/test'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
        ])
        cfg = MockConfig()
        req = HTTP2Request(stream, cfg, ('127.0.0.1', 12345))

        assert req.method == 'GET'
        assert req.uri == '/test'
        assert req.path == '/test'
        assert req.scheme == 'https'
        assert req.version == (2, 0)

    def test_post_request_with_body(self):
        stream = self._make_stream(
            [
                (':method', 'POST'),
                (':path', '/submit'),
                (':scheme', 'https'),
                (':authority', 'api.example.com'),
                ('content-type', 'application/json'),
                ('content-length', '13'),
            ],
            body=b'{"key":"val"}'
        )
        cfg = MockConfig()
        req = HTTP2Request(stream, cfg, ('192.168.1.1', 54321))

        assert req.method == 'POST'
        assert req.body.read() == b'{"key":"val"}'
        assert req.content_type == 'application/json'
        assert req.content_length == 13

    def test_path_with_query_string(self):
        stream = self._make_stream([
            (':method', 'GET'),
            (':path', '/search?q=test&page=1'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
        ])
        cfg = MockConfig()
        req = HTTP2Request(stream, cfg, ('127.0.0.1', 12345))

        assert req.path == '/search'
        assert req.query == 'q=test&page=1'
        assert req.uri == '/search?q=test&page=1'

    def test_path_with_fragment(self):
        stream = self._make_stream([
            (':method', 'GET'),
            (':path', '/page#section'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
        ])
        cfg = MockConfig()
        req = HTTP2Request(stream, cfg, ('127.0.0.1', 12345))

        assert req.path == '/page'
        assert req.fragment == 'section'

    def test_headers_uppercase_conversion(self):
        """HTTP/2 headers are lowercase, should be converted to uppercase."""
        stream = self._make_stream([
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
            ('content-type', 'text/html'),
            ('accept-language', 'en-US'),
            ('x-custom-header', 'custom-value'),
        ])
        cfg = MockConfig()
        req = HTTP2Request(stream, cfg, ('127.0.0.1', 12345))

        header_names = [h[0] for h in req.headers]
        assert 'CONTENT-TYPE' in header_names
        assert 'ACCEPT-LANGUAGE' in header_names
        assert 'X-CUSTOM-HEADER' in header_names

    def test_host_header_from_authority(self):
        """Host header should be generated from :authority pseudo-header."""
        stream = self._make_stream([
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'test.example.com:8080'),
        ])
        cfg = MockConfig()
        req = HTTP2Request(stream, cfg, ('127.0.0.1', 12345))

        host = req.get_header('HOST')
        assert host == 'test.example.com:8080'

    def test_authority_overrides_host_header(self):
        """:authority MUST override Host header per RFC 9113 section 8.3.1."""
        stream = self._make_stream([
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'authority.example.com'),
            ('host', 'explicit.example.com'),
        ])
        cfg = MockConfig()
        req = HTTP2Request(stream, cfg, ('127.0.0.1', 12345))

        # Count HOST headers - should be exactly one, from :authority
        host_headers = [h for h in req.headers if h[0] == 'HOST']
        assert len(host_headers) == 1
        assert host_headers[0][1] == 'authority.example.com'

    def test_get_header_case_insensitive(self):
        stream = self._make_stream([
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
            ('x-test-header', 'test-value'),
        ])
        cfg = MockConfig()
        req = HTTP2Request(stream, cfg, ('127.0.0.1', 12345))

        assert req.get_header('X-TEST-HEADER') == 'test-value'
        assert req.get_header('x-test-header') == 'test-value'
        assert req.get_header('X-Test-Header') == 'test-value'

    def test_get_header_not_found(self):
        stream = self._make_stream([
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
        ])
        cfg = MockConfig()
        req = HTTP2Request(stream, cfg, ('127.0.0.1', 12345))

        assert req.get_header('X-Not-Exists') is None

    def test_content_length_property(self):
        stream = self._make_stream([
            (':method', 'POST'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
            ('content-length', '42'),
        ])
        cfg = MockConfig()
        req = HTTP2Request(stream, cfg, ('127.0.0.1', 12345))

        assert req.content_length == 42

    def test_content_length_none_when_missing(self):
        stream = self._make_stream([
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
        ])
        cfg = MockConfig()
        req = HTTP2Request(stream, cfg, ('127.0.0.1', 12345))

        assert req.content_length is None

    def test_content_length_invalid_value(self):
        stream = self._make_stream([
            (':method', 'POST'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
            ('content-length', 'not-a-number'),
        ])
        cfg = MockConfig()
        req = HTTP2Request(stream, cfg, ('127.0.0.1', 12345))

        assert req.content_length is None

    def test_content_type_property(self):
        stream = self._make_stream([
            (':method', 'POST'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
            ('content-type', 'application/json; charset=utf-8'),
        ])
        cfg = MockConfig()
        req = HTTP2Request(stream, cfg, ('127.0.0.1', 12345))

        assert req.content_type == 'application/json; charset=utf-8'

    def test_content_type_none_when_missing(self):
        stream = self._make_stream([
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
        ])
        cfg = MockConfig()
        req = HTTP2Request(stream, cfg, ('127.0.0.1', 12345))

        assert req.content_type is None


class TestHTTP2RequestConnectionState:
    """Test connection state methods."""

    def _make_stream(self, headers):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.receive_headers(headers, end_stream=True)
        return stream

    def test_should_close_default_false(self):
        """HTTP/2 connections are persistent by default."""
        stream = self._make_stream([
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
        ])
        cfg = MockConfig()
        req = HTTP2Request(stream, cfg, ('127.0.0.1', 12345))

        assert req.should_close() is False

    def test_force_close(self):
        stream = self._make_stream([
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
        ])
        cfg = MockConfig()
        req = HTTP2Request(stream, cfg, ('127.0.0.1', 12345))

        req.force_close()
        assert req.should_close() is True
        assert req.must_close is True


class TestHTTP2RequestTrailers:
    """Test request trailers handling."""

    def test_no_trailers(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.receive_headers([
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
        ], end_stream=True)

        cfg = MockConfig()
        req = HTTP2Request(stream, cfg, ('127.0.0.1', 12345))

        assert req.trailers == []

    def test_with_trailers(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.receive_headers([
            (':method', 'POST'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
        ], end_stream=False)
        stream.state = stream.state  # Keep state
        stream.trailers = [
            ('grpc-status', '0'),
            ('grpc-message', 'OK'),
        ]

        cfg = MockConfig()
        req = HTTP2Request(stream, cfg, ('127.0.0.1', 12345))

        assert len(req.trailers) == 2
        assert ('GRPC-STATUS', '0') in req.trailers
        assert ('GRPC-MESSAGE', 'OK') in req.trailers


class TestHTTP2RequestMetadata:
    """Test request metadata properties."""

    def _make_stream(self, headers, stream_id=1):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=stream_id, connection=conn)
        stream.receive_headers(headers, end_stream=True)
        return stream

    def test_version_is_http2(self):
        stream = self._make_stream([
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
        ])
        cfg = MockConfig()
        req = HTTP2Request(stream, cfg, ('127.0.0.1', 12345))

        assert req.version == (2, 0)

    def test_req_number_is_stream_id(self):
        stream = self._make_stream([
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
        ], stream_id=5)
        cfg = MockConfig()
        req = HTTP2Request(stream, cfg, ('127.0.0.1', 12345))

        assert req.req_number == 5

    def test_peer_addr(self):
        stream = self._make_stream([
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
        ])
        cfg = MockConfig()
        req = HTTP2Request(stream, cfg, ('10.0.0.1', 54321))

        assert req.peer_addr == ('10.0.0.1', 54321)
        assert req.remote_addr == ('10.0.0.1', 54321)

    def test_proxy_protocol_info_none(self):
        """HTTP/2 doesn't use proxy protocol through data stream."""
        stream = self._make_stream([
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
        ])
        cfg = MockConfig()
        req = HTTP2Request(stream, cfg, ('127.0.0.1', 12345))

        assert req.proxy_protocol_info is None


class TestHTTP2RequestRepr:
    """Test request string representation."""

    def test_repr_format(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=3, connection=conn)
        stream.receive_headers([
            (':method', 'POST'),
            (':path', '/api/users'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
        ], end_stream=True)

        cfg = MockConfig()
        req = HTTP2Request(stream, cfg, ('127.0.0.1', 12345))

        repr_str = repr(req)
        assert "HTTP2Request" in repr_str
        assert "method=POST" in repr_str
        assert "path=/api/users" in repr_str
        assert "stream_id=3" in repr_str


class TestHTTP2RequestDefaults:
    """Test default values when pseudo-headers are missing."""

    def test_default_method(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.receive_headers([
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
        ], end_stream=True)

        cfg = MockConfig()
        req = HTTP2Request(stream, cfg, ('127.0.0.1', 12345))

        assert req.method == 'GET'

    def test_default_scheme(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.receive_headers([
            (':method', 'GET'),
            (':path', '/'),
            (':authority', 'example.com'),
        ], end_stream=True)

        cfg = MockConfig()
        req = HTTP2Request(stream, cfg, ('127.0.0.1', 12345))

        assert req.scheme == 'https'

    def test_default_path(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.receive_headers([
            (':method', 'GET'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
        ], end_stream=True)

        cfg = MockConfig()
        req = HTTP2Request(stream, cfg, ('127.0.0.1', 12345))

        assert req.uri == '/'
        assert req.path == '/'
