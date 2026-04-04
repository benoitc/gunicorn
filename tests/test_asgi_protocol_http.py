#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
ASGI HTTP protocol tests.

Tests for HTTP connection management, Expect: 100-continue,
body size handling, and chunked encoding per ASGI 3.0 and HTTP/1.1 specs.
"""

from unittest import mock

import pytest

from gunicorn.config import Config
from gunicorn.asgi.parser import (
    PythonProtocol,
    InvalidHeader,
    ParseError,
)


# ============================================================================
# HTTP Connection Management Tests
# ============================================================================

class TestHTTPConnectionManagement:
    """Test HTTP connection keep-alive and close handling."""

    def test_http11_keepalive_default(self):
        """HTTP/1.1 should use keep-alive by default."""
        parser = PythonProtocol()

        parser.feed(
            b"GET /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"\r\n"
        )

        assert parser.is_complete
        # HTTP/1.1 defaults to keep-alive
        # http_version is a tuple (major, minor)
        assert parser.http_version == (1, 1)

    def test_http10_version(self):
        """HTTP/1.0 should be parsed correctly."""
        parser = PythonProtocol()

        parser.feed(
            b"GET /test HTTP/1.0\r\n"
            b"Host: localhost\r\n"
            b"\r\n"
        )

        assert parser.is_complete
        assert parser.http_version == (1, 0)

    def test_connection_close_header(self):
        """Connection: close header should be recognized."""
        parser = PythonProtocol()

        parser.feed(
            b"GET /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Connection: close\r\n"
            b"\r\n"
        )

        assert parser.is_complete

    def test_connection_keepalive_header_http10(self):
        """Connection: keep-alive in HTTP/1.0 should be recognized."""
        parser = PythonProtocol()

        parser.feed(
            b"GET /test HTTP/1.0\r\n"
            b"Host: localhost\r\n"
            b"Connection: keep-alive\r\n"
            b"\r\n"
        )

        assert parser.is_complete

    def test_connection_header_case_insensitive(self):
        """Connection header value should be case-insensitive."""
        parser = PythonProtocol()

        parser.feed(
            b"GET /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Connection: CLOSE\r\n"
            b"\r\n"
        )

        assert parser.is_complete


# ============================================================================
# Expect: 100-continue Tests
# ============================================================================

class TestExpectContinue:
    """Test Expect: 100-continue handling."""

    def test_expect_continue_header_accepted(self):
        """Expect: 100-continue header should be accepted."""
        parser = PythonProtocol()

        parser.feed(
            b"POST /upload HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Length: 1000\r\n"
            b"Expect: 100-continue\r\n"
            b"\r\n"
        )

        # Parser should be waiting for body (not complete yet)
        assert not parser.is_complete

    def test_expect_header_case_insensitive(self):
        """Expect header value should be case-insensitive."""
        parser = PythonProtocol()

        parser.feed(
            b"POST /upload HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Length: 100\r\n"
            b"Expect: 100-Continue\r\n"
            b"\r\n"
        )

        # Parser should be waiting for body
        assert not parser.is_complete


# ============================================================================
# Request Body Size Tests
# ============================================================================

class TestRequestBodySize:
    """Test request body size validation."""

    def test_exact_content_length_body(self):
        """Body matching Content-Length should be accepted."""
        body_chunks = []
        parser = PythonProtocol(
            on_body=lambda chunk: body_chunks.append(chunk),
        )

        parser.feed(
            b"POST /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Length: 5\r\n"
            b"\r\n"
            b"hello"
        )

        assert parser.is_complete
        assert b"".join(body_chunks) == b"hello"

    def test_zero_content_length(self):
        """Zero Content-Length should have no body."""
        parser = PythonProtocol()

        parser.feed(
            b"POST /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Length: 0\r\n"
            b"\r\n"
        )

        assert parser.is_complete

    def test_body_in_chunks(self):
        """Body can arrive in multiple chunks."""
        body_chunks = []
        parser = PythonProtocol(
            on_body=lambda chunk: body_chunks.append(chunk),
        )

        parser.feed(
            b"POST /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Length: 10\r\n"
            b"\r\n"
        )

        # Feed body in chunks
        parser.feed(b"12345")
        parser.feed(b"67890")

        assert parser.is_complete
        assert b"".join(body_chunks) == b"1234567890"


# ============================================================================
# Chunked Encoding Tests
# ============================================================================

class TestChunkedEncoding:
    """Test chunked Transfer-Encoding handling."""

    def test_chunked_encoding_single_chunk(self):
        """Single chunk with terminator should work."""
        body_chunks = []
        parser = PythonProtocol(
            on_body=lambda chunk: body_chunks.append(chunk),
        )

        parser.feed(
            b"POST /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"5\r\n"
            b"hello\r\n"
            b"0\r\n"
            b"\r\n"
        )

        assert parser.is_complete
        assert parser.is_chunked
        assert b"".join(body_chunks) == b"hello"

    def test_chunked_encoding_multiple_chunks(self):
        """Multiple chunks should be concatenated."""
        body_chunks = []
        parser = PythonProtocol(
            on_body=lambda chunk: body_chunks.append(chunk),
        )

        parser.feed(
            b"POST /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"5\r\n"
            b"hello\r\n"
            b"6\r\n"
            b" world\r\n"
            b"0\r\n"
            b"\r\n"
        )

        assert parser.is_complete
        assert b"".join(body_chunks) == b"hello world"

    def test_chunked_encoding_empty_body(self):
        """Empty chunked body (just terminator) should work."""
        body_chunks = []
        parser = PythonProtocol(
            on_body=lambda chunk: body_chunks.append(chunk),
        )

        parser.feed(
            b"POST /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"0\r\n"
            b"\r\n"
        )

        assert parser.is_complete
        # No body chunks or empty
        assert b"".join(body_chunks) == b""

    def test_chunked_encoding_with_trailer(self):
        """Chunked encoding with trailer headers."""
        body_chunks = []
        parser = PythonProtocol(
            on_body=lambda chunk: body_chunks.append(chunk),
        )

        parser.feed(
            b"POST /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"Trailer: X-Checksum\r\n"
            b"\r\n"
            b"5\r\n"
            b"hello\r\n"
            b"0\r\n"
            b"X-Checksum: abc123\r\n"
            b"\r\n"
        )

        assert parser.is_complete
        assert b"".join(body_chunks) == b"hello"

    def test_chunked_hex_sizes(self):
        """Chunk sizes should be parsed as hex."""
        body_chunks = []
        parser = PythonProtocol(
            on_body=lambda chunk: body_chunks.append(chunk),
        )

        parser.feed(
            b"POST /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"a\r\n"  # 10 in hex
            b"0123456789\r\n"
            b"0\r\n"
            b"\r\n"
        )

        assert parser.is_complete
        assert b"".join(body_chunks) == b"0123456789"

    def test_chunked_uppercase_hex(self):
        """Uppercase hex chunk sizes should work."""
        body_chunks = []
        parser = PythonProtocol(
            on_body=lambda chunk: body_chunks.append(chunk),
        )

        parser.feed(
            b"POST /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"A\r\n"  # 10 in uppercase hex
            b"0123456789\r\n"
            b"0\r\n"
            b"\r\n"
        )

        assert parser.is_complete
        assert b"".join(body_chunks) == b"0123456789"


# ============================================================================
# HEAD Request Tests
# ============================================================================

class TestHEADRequest:
    """Test HEAD request handling."""

    def test_head_request_no_body(self):
        """HEAD request should have no body."""
        parser = PythonProtocol()

        parser.feed(
            b"HEAD /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"\r\n"
        )

        assert parser.is_complete


# ============================================================================
# HTTP Method Tests
# ============================================================================

class TestHTTPMethods:
    """Test HTTP method handling."""

    def test_get_method(self):
        """GET method should be parsed."""
        parser = PythonProtocol()

        parser.feed(
            b"GET /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"\r\n"
        )

        assert parser.is_complete
        # method is bytes in the parser
        assert parser.method == b"GET"

    def test_post_method(self):
        """POST method should be parsed."""
        parser = PythonProtocol()

        parser.feed(
            b"POST /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Length: 0\r\n"
            b"\r\n"
        )

        assert parser.is_complete
        assert parser.method == b"POST"

    def test_put_method(self):
        """PUT method should be parsed."""
        parser = PythonProtocol()

        parser.feed(
            b"PUT /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Length: 0\r\n"
            b"\r\n"
        )

        assert parser.is_complete
        assert parser.method == b"PUT"

    def test_delete_method(self):
        """DELETE method should be parsed."""
        parser = PythonProtocol()

        parser.feed(
            b"DELETE /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"\r\n"
        )

        assert parser.is_complete
        assert parser.method == b"DELETE"


# ============================================================================
# HTTP Scope Building Tests
# ============================================================================

class TestHTTPScopeBuilding:
    """Test building ASGI HTTP scope."""

    def _create_protocol(self):
        """Create an ASGIProtocol instance for testing."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()

        return ASGIProtocol(worker)

    def _create_mock_request(self, **kwargs):
        """Create a mock HTTP request."""
        request = mock.Mock()
        request.method = kwargs.get("method", "GET")
        path = kwargs.get("path", "/")
        request.path = path
        request.raw_path = kwargs.get("raw_path", path.encode("latin-1"))
        request.query = kwargs.get("query", "")
        request.version = kwargs.get("version", (1, 1))
        request.scheme = kwargs.get("scheme", "http")
        request.headers = kwargs.get("headers", [])
        return request

    def test_scope_type_is_http(self):
        """Scope type should be 'http'."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        scope = protocol._build_http_scope(request, None, None)

        assert scope["type"] == "http"

    def test_scope_method_uppercase(self):
        """Method in scope should be uppercase."""
        protocol = self._create_protocol()
        request = self._create_mock_request(method="POST")

        scope = protocol._build_http_scope(request, None, None)

        assert scope["method"] == "POST"

    def test_scope_path_percent_encoded(self):
        """Path with special characters should be handled."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            path="/api/users/john%20doe",
            raw_path=b"/api/users/john%20doe",
        )

        scope = protocol._build_http_scope(request, None, None)

        assert scope["raw_path"] == b"/api/users/john%20doe"

    def test_scope_query_string_bytes(self):
        """Query string should be bytes."""
        protocol = self._create_protocol()
        request = self._create_mock_request(query="page=1&size=10")

        scope = protocol._build_http_scope(request, None, None)

        assert scope["query_string"] == b"page=1&size=10"
        assert isinstance(scope["query_string"], bytes)

    def test_scope_server_info(self):
        """Server info should be tuple of (host, port)."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        scope = protocol._build_http_scope(
            request,
            ("127.0.0.1", 8000),
            ("192.168.1.1", 54321),
        )

        assert scope["server"] == ("127.0.0.1", 8000)
        assert scope["client"] == ("192.168.1.1", 54321)

    def test_scope_asgi_version(self):
        """ASGI version info should be present."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        scope = protocol._build_http_scope(request, None, None)

        assert "asgi" in scope
        assert scope["asgi"]["version"] == "3.0"
