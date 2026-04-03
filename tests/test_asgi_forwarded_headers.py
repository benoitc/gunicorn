#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
ASGI forwarded headers tests.

Tests for X-Forwarded-For, X-Forwarded-Proto, and related
proxy header handling in ASGI applications.
"""

from unittest import mock

import pytest

from gunicorn.config import Config


# ============================================================================
# X-Forwarded-For Header Tests
# ============================================================================

class TestXForwardedFor:
    """Test X-Forwarded-For header handling."""

    def _create_protocol(self, forwarded_allow_ips=None):
        """Create an ASGIProtocol instance for testing."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        worker.cfg = Config()
        if forwarded_allow_ips is not None:
            worker.cfg.forwarded_allow_ips = forwarded_allow_ips
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()

        return ASGIProtocol(worker)

    def _create_mock_request(self, headers=None):
        """Create a mock HTTP request."""
        request = mock.Mock()
        request.method = "GET"
        request.path = "/"
        request.raw_path = b"/"
        request.query = ""
        request.version = (1, 1)
        request.scheme = "http"
        request.headers = headers or []
        return request

    def test_x_forwarded_for_in_headers(self):
        """X-Forwarded-For header should be passed through."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            headers=[
                ("HOST", "localhost"),
                ("X-FORWARDED-FOR", "192.168.1.1, 10.0.0.1"),
            ]
        )

        scope = protocol._build_http_scope(request, None, None)

        # Header should be in scope headers
        header_names = [name for name, _ in scope["headers"]]
        assert b"x-forwarded-for" in header_names

    def test_x_forwarded_for_multiple_addresses(self):
        """X-Forwarded-For can contain multiple addresses."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            headers=[
                ("HOST", "localhost"),
                ("X-FORWARDED-FOR", "203.0.113.195, 70.41.3.18, 150.172.238.178"),
            ]
        )

        scope = protocol._build_http_scope(request, None, None)

        # Find the header value
        xff_value = None
        for name, value in scope["headers"]:
            if name == b"x-forwarded-for":
                xff_value = value
                break

        assert xff_value == b"203.0.113.195, 70.41.3.18, 150.172.238.178"


# ============================================================================
# X-Forwarded-Proto Header Tests
# ============================================================================

class TestXForwardedProto:
    """Test X-Forwarded-Proto header handling."""

    def _create_protocol(self):
        """Create an ASGIProtocol instance for testing."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()

        return ASGIProtocol(worker)

    def _create_mock_request(self, headers=None, scheme="http"):
        """Create a mock HTTP request."""
        request = mock.Mock()
        request.method = "GET"
        request.path = "/"
        request.raw_path = b"/"
        request.query = ""
        request.version = (1, 1)
        request.scheme = scheme
        request.headers = headers or []
        return request

    def test_x_forwarded_proto_http(self):
        """X-Forwarded-Proto: http should be passed through."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            headers=[
                ("HOST", "localhost"),
                ("X-FORWARDED-PROTO", "http"),
            ]
        )

        scope = protocol._build_http_scope(request, None, None)

        # Header should be in scope headers
        header_dict = {name: value for name, value in scope["headers"]}
        assert b"x-forwarded-proto" in header_dict

    def test_x_forwarded_proto_https(self):
        """X-Forwarded-Proto: https should be passed through."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            headers=[
                ("HOST", "localhost"),
                ("X-FORWARDED-PROTO", "https"),
            ]
        )

        scope = protocol._build_http_scope(request, None, None)

        header_dict = {name: value for name, value in scope["headers"]}
        assert header_dict[b"x-forwarded-proto"] == b"https"


# ============================================================================
# X-Forwarded-Host Header Tests
# ============================================================================

class TestXForwardedHost:
    """Test X-Forwarded-Host header handling."""

    def _create_protocol(self):
        """Create an ASGIProtocol instance for testing."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()

        return ASGIProtocol(worker)

    def _create_mock_request(self, headers=None):
        """Create a mock HTTP request."""
        request = mock.Mock()
        request.method = "GET"
        request.path = "/"
        request.raw_path = b"/"
        request.query = ""
        request.version = (1, 1)
        request.scheme = "http"
        request.headers = headers or []
        return request

    def test_x_forwarded_host_in_headers(self):
        """X-Forwarded-Host should be passed through."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            headers=[
                ("HOST", "backend.internal"),
                ("X-FORWARDED-HOST", "www.example.com"),
            ]
        )

        scope = protocol._build_http_scope(request, None, None)

        header_dict = {name: value for name, value in scope["headers"]}
        assert b"x-forwarded-host" in header_dict
        assert header_dict[b"x-forwarded-host"] == b"www.example.com"


# ============================================================================
# X-Forwarded-Port Header Tests
# ============================================================================

class TestXForwardedPort:
    """Test X-Forwarded-Port header handling."""

    def _create_protocol(self):
        """Create an ASGIProtocol instance for testing."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()

        return ASGIProtocol(worker)

    def _create_mock_request(self, headers=None):
        """Create a mock HTTP request."""
        request = mock.Mock()
        request.method = "GET"
        request.path = "/"
        request.raw_path = b"/"
        request.query = ""
        request.version = (1, 1)
        request.scheme = "http"
        request.headers = headers or []
        return request

    def test_x_forwarded_port_in_headers(self):
        """X-Forwarded-Port should be passed through."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            headers=[
                ("HOST", "localhost:8000"),
                ("X-FORWARDED-PORT", "443"),
            ]
        )

        scope = protocol._build_http_scope(request, None, None)

        header_dict = {name: value for name, value in scope["headers"]}
        assert b"x-forwarded-port" in header_dict
        assert header_dict[b"x-forwarded-port"] == b"443"


# ============================================================================
# Forwarded Header (RFC 7239) Tests
# ============================================================================

class TestForwardedHeader:
    """Test Forwarded header (RFC 7239) handling."""

    def _create_protocol(self):
        """Create an ASGIProtocol instance for testing."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()

        return ASGIProtocol(worker)

    def _create_mock_request(self, headers=None):
        """Create a mock HTTP request."""
        request = mock.Mock()
        request.method = "GET"
        request.path = "/"
        request.raw_path = b"/"
        request.query = ""
        request.version = (1, 1)
        request.scheme = "http"
        request.headers = headers or []
        return request

    def test_forwarded_header_in_scope(self):
        """Forwarded header should be passed through."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            headers=[
                ("HOST", "localhost"),
                ("FORWARDED", "for=192.0.2.60;proto=http;by=203.0.113.43"),
            ]
        )

        scope = protocol._build_http_scope(request, None, None)

        header_dict = {name: value for name, value in scope["headers"]}
        assert b"forwarded" in header_dict

    def test_forwarded_header_multiple_proxies(self):
        """Forwarded header with multiple proxies."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            headers=[
                ("HOST", "localhost"),
                ("FORWARDED", "for=192.0.2.43, for=198.51.100.178"),
            ]
        )

        scope = protocol._build_http_scope(request, None, None)

        header_dict = {name: value for name, value in scope["headers"]}
        assert header_dict[b"forwarded"] == b"for=192.0.2.43, for=198.51.100.178"


# ============================================================================
# Trusted Proxy Tests
# ============================================================================

class TestTrustedProxy:
    """Test trusted proxy configuration."""

    def test_check_trusted_proxy_function_exists(self):
        """_check_trusted_proxy function should exist."""
        from gunicorn.asgi.protocol import _check_trusted_proxy

        assert callable(_check_trusted_proxy)

    def test_normalize_sockaddr_function_exists(self):
        """_normalize_sockaddr function should exist."""
        from gunicorn.asgi.protocol import _normalize_sockaddr

        assert callable(_normalize_sockaddr)

    def test_normalize_sockaddr_ipv4(self):
        """IPv4 address should be normalized."""
        from gunicorn.asgi.protocol import _normalize_sockaddr

        result = _normalize_sockaddr(("192.168.1.1", 8000))
        assert result == ("192.168.1.1", 8000)

    def test_normalize_sockaddr_ipv6(self):
        """IPv6 address should be normalized."""
        from gunicorn.asgi.protocol import _normalize_sockaddr

        # IPv6 sockaddr is a 4-tuple
        result = _normalize_sockaddr(("::1", 8000, 0, 0))
        assert result == ("::1", 8000)

    def test_normalize_sockaddr_none(self):
        """None sockaddr should return None."""
        from gunicorn.asgi.protocol import _normalize_sockaddr

        result = _normalize_sockaddr(None)
        assert result is None


# ============================================================================
# Header Preservation Tests
# ============================================================================

class TestHeaderPreservation:
    """Test that proxy headers are preserved in scope."""

    def _create_protocol(self):
        """Create an ASGIProtocol instance for testing."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()

        return ASGIProtocol(worker)

    def _create_mock_request(self, headers=None):
        """Create a mock HTTP request."""
        request = mock.Mock()
        request.method = "GET"
        request.path = "/"
        request.raw_path = b"/"
        request.query = ""
        request.version = (1, 1)
        request.scheme = "http"
        request.headers = headers or []
        return request

    def test_all_proxy_headers_preserved(self):
        """All standard proxy headers should be preserved."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            headers=[
                ("HOST", "localhost"),
                ("X-FORWARDED-FOR", "192.168.1.1"),
                ("X-FORWARDED-PROTO", "https"),
                ("X-FORWARDED-HOST", "example.com"),
                ("X-FORWARDED-PORT", "443"),
                ("X-REAL-IP", "10.0.0.1"),
            ]
        )

        scope = protocol._build_http_scope(request, None, None)

        header_names = {name for name, _ in scope["headers"]}

        assert b"x-forwarded-for" in header_names
        assert b"x-forwarded-proto" in header_names
        assert b"x-forwarded-host" in header_names
        assert b"x-forwarded-port" in header_names
        assert b"x-real-ip" in header_names

    def test_header_values_as_bytes(self):
        """Proxy header values should be bytes."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            headers=[
                ("HOST", "localhost"),
                ("X-FORWARDED-FOR", "192.168.1.1"),
            ]
        )

        scope = protocol._build_http_scope(request, None, None)

        for name, value in scope["headers"]:
            assert isinstance(name, bytes)
            assert isinstance(value, bytes)
