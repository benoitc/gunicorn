#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
ASGI header security tests.

Tests for header validation, normalization, and injection prevention
to ensure secure HTTP header handling per ASGI 3.0 and RFC 9110/9112.
"""

import pytest

from gunicorn.asgi.parser import (
    PythonProtocol,
    InvalidHeader,
    ParseError,
)


# ============================================================================
# Header Name Validation Tests
# ============================================================================

class TestHeaderNameValidation:
    """Test validation of HTTP header names."""

    def test_valid_header_name_accepted(self):
        """Valid header names should be accepted."""
        parser = PythonProtocol()

        parser.feed(
            b"GET /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"X-Custom-Header: value\r\n"
            b"Accept-Language: en-US\r\n"
            b"\r\n"
        )

        assert parser.is_complete

    def test_header_name_with_null_rejected(self):
        """Header name containing null byte must be rejected."""
        parser = PythonProtocol()

        with pytest.raises((InvalidHeader, ParseError)):
            parser.feed(
                b"GET /test HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"X-Bad\x00Header: value\r\n"
                b"\r\n"
            )

    def test_header_name_with_cr_rejected(self):
        """Header name containing CR must be rejected."""
        parser = PythonProtocol()

        with pytest.raises((InvalidHeader, ParseError)):
            parser.feed(
                b"GET /test HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"X-Bad\rHeader: value\r\n"
                b"\r\n"
            )

    def test_header_name_with_lf_rejected(self):
        """Header name containing LF must be rejected."""
        parser = PythonProtocol()

        with pytest.raises((InvalidHeader, ParseError)):
            parser.feed(
                b"GET /test HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"X-Bad\nHeader: value\r\n"
                b"\r\n"
            )

    def test_empty_header_name_rejected(self):
        """Empty header name must be rejected."""
        parser = PythonProtocol()

        with pytest.raises((InvalidHeader, ParseError)):
            parser.feed(
                b"GET /test HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b": value\r\n"
                b"\r\n"
            )


# ============================================================================
# Header Value Validation Tests
# ============================================================================

class TestHeaderValueValidation:
    """Test validation of HTTP header values."""

    def test_header_value_with_bare_cr_rejected(self):
        """Header value containing bare CR must be rejected."""
        parser = PythonProtocol()

        # Bare CR (not followed by LF) in header value should be rejected
        with pytest.raises((InvalidHeader, ParseError)):
            parser.feed(
                b"GET /test HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"X-Bad: value\rmore\r\n"
                b"\r\n"
            )

    def test_header_value_with_bare_lf_rejected(self):
        """Header value containing bare LF must be rejected."""
        parser = PythonProtocol()

        # Bare LF (not preceded by CR) in header value should be rejected
        with pytest.raises((InvalidHeader, ParseError)):
            parser.feed(
                b"GET /test HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"X-Bad: value\nmore\r\n"
                b"\r\n"
            )

    def test_header_value_special_characters_allowed(self):
        """Header values may contain special printable characters."""
        parser = PythonProtocol()

        parser.feed(
            b"GET /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Authorization: Bearer abc123!@#$%^&*()_+\r\n"
            b"Cookie: session=abc; path=/; domain=.example.com\r\n"
            b"\r\n"
        )

        assert parser.is_complete

    def test_header_value_with_tab_allowed(self):
        """Horizontal tab in header value is allowed (OWS)."""
        parser = PythonProtocol()

        parser.feed(
            b"GET /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"X-Tabs: value1\tvalue2\r\n"
            b"\r\n"
        )

        assert parser.is_complete


# ============================================================================
# Header Normalization Tests
# ============================================================================

class TestHeaderNormalization:
    """Test HTTP header normalization per ASGI spec."""

    def _create_protocol(self):
        """Create an ASGIProtocol instance for testing."""
        from gunicorn.asgi.protocol import ASGIProtocol
        from gunicorn.config import Config
        from unittest import mock

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()

        return ASGIProtocol(worker)

    def _create_mock_request(self, headers=None):
        """Create a mock HTTP request with headers."""
        from unittest import mock

        request = mock.Mock()
        request.method = "GET"
        request.path = "/"
        request.raw_path = b"/"
        request.query = ""
        request.version = (1, 1)
        request.scheme = "http"
        request.headers = headers or []
        return request

    def test_headers_lowercased_in_scope(self):
        """Header names must be lowercased in ASGI scope."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            headers=[
                ("CONTENT-TYPE", "application/json"),
                ("X-CUSTOM-HEADER", "value"),
            ]
        )

        scope = protocol._build_http_scope(request, None, None)

        for name, _ in scope["headers"]:
            assert name == name.lower(), f"Header name should be lowercase: {name}"

    def test_header_names_are_bytes(self):
        """Header names in scope must be bytes."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            headers=[
                ("Content-Type", "text/plain"),
            ]
        )

        scope = protocol._build_http_scope(request, None, None)

        for name, _ in scope["headers"]:
            assert isinstance(name, bytes), f"Header name should be bytes: {type(name)}"

    def test_header_values_are_bytes(self):
        """Header values in scope must be bytes."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            headers=[
                ("Content-Type", "text/plain"),
            ]
        )

        scope = protocol._build_http_scope(request, None, None)

        for _, value in scope["headers"]:
            assert isinstance(value, bytes), f"Header value should be bytes: {type(value)}"

    def test_header_order_preserved(self):
        """Order of headers should be preserved."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            headers=[
                ("First", "1"),
                ("Second", "2"),
                ("Third", "3"),
            ]
        )

        scope = protocol._build_http_scope(request, None, None)

        header_names = [name for name, _ in scope["headers"]]
        assert header_names == [b"first", b"second", b"third"]


# ============================================================================
# Oversized Header Tests
# ============================================================================

class TestOversizedHeaders:
    """Test rejection of oversized headers."""

    def test_oversized_header_value_handled(self):
        """Very large header values should be handled safely."""
        parser = PythonProtocol()

        # Parser should handle large headers without crashing
        # The limit is configurable - test the parser doesn't crash
        large_value = b"x" * 8192

        try:
            parser.feed(
                b"GET /test HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"X-Large: " + large_value + b"\r\n"
                b"\r\n"
            )
            # Either succeeds or raises appropriate error
        except (InvalidHeader, ParseError):
            # Rejection is acceptable for very large headers
            pass

    def test_many_headers_handled(self):
        """Request with many headers should be handled safely."""
        parser = PythonProtocol()

        # Build request with many headers
        headers = b"".join(
            f"X-Header-{i}: value{i}\r\n".encode()
            for i in range(100)
        )

        try:
            parser.feed(
                b"GET /test HTTP/1.1\r\n"
                b"Host: localhost\r\n" +
                headers +
                b"\r\n"
            )
            # May succeed if within limits
        except (InvalidHeader, ParseError):
            # Rejection is acceptable for many headers
            pass


# ============================================================================
# Host Header Validation Tests
# ============================================================================

class TestHostHeaderValidation:
    """Test Host header validation."""

    def test_valid_host_header_accepted(self):
        """Valid Host header should be accepted."""
        parser = PythonProtocol()

        parser.feed(
            b"GET /test HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"\r\n"
        )

        assert parser.is_complete

    def test_host_header_with_port_accepted(self):
        """Host header with port should be accepted."""
        parser = PythonProtocol()

        parser.feed(
            b"GET /test HTTP/1.1\r\n"
            b"Host: example.com:8080\r\n"
            b"\r\n"
        )

        assert parser.is_complete

    def test_ipv6_host_header_accepted(self):
        """IPv6 Host header should be accepted."""
        parser = PythonProtocol()

        parser.feed(
            b"GET /test HTTP/1.1\r\n"
            b"Host: [::1]:8080\r\n"
            b"\r\n"
        )

        assert parser.is_complete


# ============================================================================
# Content-Type Header Tests
# ============================================================================

class TestContentTypeHeader:
    """Test Content-Type header handling."""

    def test_content_type_with_charset(self):
        """Content-Type with charset parameter should work."""
        parser = PythonProtocol()

        parser.feed(
            b"POST /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Type: text/html; charset=utf-8\r\n"
            b"Content-Length: 0\r\n"
            b"\r\n"
        )

        assert parser.is_complete

    def test_content_type_multipart(self):
        """Multipart Content-Type should work."""
        parser = PythonProtocol()

        parser.feed(
            b"POST /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Type: multipart/form-data; boundary=----WebKitFormBoundary\r\n"
            b"Content-Length: 0\r\n"
            b"\r\n"
        )

        assert parser.is_complete
