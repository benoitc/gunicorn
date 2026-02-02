#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
ASGI HTTP scope validation tests.

Tests for HTTP scope building, URL encoding, header handling,
and extension support.
"""

from unittest import mock

import pytest

from gunicorn.config import Config


# ============================================================================
# HTTP Scope Building Tests
# ============================================================================

class TestHTTPScopeBuilding:
    """Tests for _build_http_scope method."""

    def _create_protocol(self, **config_kwargs):
        """Create an ASGIProtocol instance for testing."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        worker.cfg = Config()
        for key, value in config_kwargs.items():
            worker.cfg.set(key, value)
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()

        return ASGIProtocol(worker)

    def _create_mock_request(self, **kwargs):
        """Create a mock HTTP request."""
        request = mock.Mock()
        request.method = kwargs.get("method", "GET")
        request.path = kwargs.get("path", "/")
        request.query = kwargs.get("query", "")
        request.version = kwargs.get("version", (1, 1))
        request.scheme = kwargs.get("scheme", "http")
        request.headers = kwargs.get("headers", [])

        # Optionally add HTTP/2 priority attributes
        if "priority_weight" in kwargs:
            request.priority_weight = kwargs["priority_weight"]
            request.priority_depends_on = kwargs.get("priority_depends_on", 0)

        return request

    def test_basic_scope_structure(self):
        """Test basic HTTP scope structure."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        scope = protocol._build_http_scope(
            request,
            ("127.0.0.1", 8000),
            ("192.168.1.100", 54321),
        )

        # All required keys should be present
        required_keys = [
            "type", "asgi", "http_version", "method", "scheme",
            "path", "raw_path", "query_string", "root_path",
            "headers", "server", "client",
        ]
        for key in required_keys:
            assert key in scope, f"Missing required key: {key}"

    def test_root_path_configuration(self):
        """Test root_path from configuration."""
        protocol = self._create_protocol(root_path="/api/v1")
        request = self._create_mock_request()

        scope = protocol._build_http_scope(request, None, None)

        assert scope["root_path"] == "/api/v1"

    def test_root_path_default_empty(self):
        """Test root_path defaults to empty string."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        scope = protocol._build_http_scope(request, None, None)

        assert scope["root_path"] == ""


# ============================================================================
# Path Handling Tests
# ============================================================================

class TestPathHandling:
    """Tests for path handling in HTTP scope."""

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
        request.path = kwargs.get("path", "/")
        request.query = kwargs.get("query", "")
        request.version = kwargs.get("version", (1, 1))
        request.scheme = kwargs.get("scheme", "http")
        request.headers = kwargs.get("headers", [])
        return request

    def test_simple_path(self):
        """Test simple path handling."""
        protocol = self._create_protocol()
        request = self._create_mock_request(path="/users")

        scope = protocol._build_http_scope(request, None, None)

        assert scope["path"] == "/users"
        assert scope["raw_path"] == b"/users"

    def test_path_with_unicode(self):
        """Test path with unicode characters."""
        protocol = self._create_protocol()
        # Latin-1 encodable characters
        request = self._create_mock_request(path="/caf\xe9")

        scope = protocol._build_http_scope(request, None, None)

        assert scope["path"] == "/caf\xe9"
        assert scope["raw_path"] == b"/caf\xe9"

    def test_nested_path(self):
        """Test nested path handling."""
        protocol = self._create_protocol()
        request = self._create_mock_request(path="/api/v1/users/123/posts")

        scope = protocol._build_http_scope(request, None, None)

        assert scope["path"] == "/api/v1/users/123/posts"

    def test_root_path_only(self):
        """Test root path only."""
        protocol = self._create_protocol()
        request = self._create_mock_request(path="/")

        scope = protocol._build_http_scope(request, None, None)

        assert scope["path"] == "/"
        assert scope["raw_path"] == b"/"

    def test_empty_path(self):
        """Test empty path handling."""
        protocol = self._create_protocol()
        request = self._create_mock_request(path="")

        scope = protocol._build_http_scope(request, None, None)

        assert scope["path"] == ""
        assert scope["raw_path"] == b""


# ============================================================================
# Query String Tests
# ============================================================================

class TestQueryStringHandling:
    """Tests for query string handling in HTTP scope."""

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
        request.path = kwargs.get("path", "/")
        request.query = kwargs.get("query", "")
        request.version = kwargs.get("version", (1, 1))
        request.scheme = kwargs.get("scheme", "http")
        request.headers = kwargs.get("headers", [])
        return request

    def test_simple_query_string(self):
        """Test simple query string."""
        protocol = self._create_protocol()
        request = self._create_mock_request(query="page=1")

        scope = protocol._build_http_scope(request, None, None)

        assert scope["query_string"] == b"page=1"

    def test_multiple_query_params(self):
        """Test multiple query parameters."""
        protocol = self._create_protocol()
        request = self._create_mock_request(query="page=1&limit=10&sort=name")

        scope = protocol._build_http_scope(request, None, None)

        assert scope["query_string"] == b"page=1&limit=10&sort=name"

    def test_empty_query_string(self):
        """Test empty query string."""
        protocol = self._create_protocol()
        request = self._create_mock_request(query="")

        scope = protocol._build_http_scope(request, None, None)

        assert scope["query_string"] == b""

    def test_query_with_special_characters(self):
        """Test query string with special characters."""
        protocol = self._create_protocol()
        request = self._create_mock_request(query="name=John%20Doe&email=test%40example.com")

        scope = protocol._build_http_scope(request, None, None)

        # Query string should be preserved as-is (URL encoded)
        assert scope["query_string"] == b"name=John%20Doe&email=test%40example.com"

    def test_query_with_unicode(self):
        """Test query string with unicode (Latin-1 encodable)."""
        protocol = self._create_protocol()
        request = self._create_mock_request(query="city=caf\xe9")

        scope = protocol._build_http_scope(request, None, None)

        assert scope["query_string"] == b"city=caf\xe9"


# ============================================================================
# Header Handling Tests
# ============================================================================

class TestHeaderHandling:
    """Tests for header handling in HTTP scope."""

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
        request.path = kwargs.get("path", "/")
        request.query = kwargs.get("query", "")
        request.version = kwargs.get("version", (1, 1))
        request.scheme = kwargs.get("scheme", "http")
        request.headers = kwargs.get("headers", [])
        return request

    def test_headers_converted_to_bytes(self):
        """Test that headers are converted to bytes tuples."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            headers=[("HOST", "localhost"), ("ACCEPT", "text/html")]
        )

        scope = protocol._build_http_scope(request, None, None)

        for name, value in scope["headers"]:
            assert isinstance(name, bytes)
            assert isinstance(value, bytes)

    def test_headers_lowercase(self):
        """Test that header names are lowercased."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            headers=[("HOST", "localhost"), ("Content-Type", "application/json")]
        )

        scope = protocol._build_http_scope(request, None, None)

        header_names = [name for name, _ in scope["headers"]]
        assert b"host" in header_names
        assert b"content-type" in header_names

    def test_multiple_headers_same_name(self):
        """Test multiple headers with the same name."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            headers=[
                ("ACCEPT", "text/html"),
                ("ACCEPT", "application/json"),
            ]
        )

        scope = protocol._build_http_scope(request, None, None)

        accept_headers = [value for name, value in scope["headers"] if name == b"accept"]
        assert len(accept_headers) == 2

    def test_empty_headers(self):
        """Test empty headers list."""
        protocol = self._create_protocol()
        request = self._create_mock_request(headers=[])

        scope = protocol._build_http_scope(request, None, None)

        assert scope["headers"] == []

    def test_header_value_with_special_chars(self):
        """Test header values with special characters."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            headers=[("USER-AGENT", "Mozilla/5.0 (compatible; bot/1.0)")]
        )

        scope = protocol._build_http_scope(request, None, None)

        user_agent = [v for n, v in scope["headers"] if n == b"user-agent"][0]
        assert user_agent == b"Mozilla/5.0 (compatible; bot/1.0)"


# ============================================================================
# WebSocket Scope Tests
# ============================================================================

class TestWebSocketScope:
    """Tests for WebSocket scope building."""

    def _create_protocol(self):
        """Create an ASGIProtocol instance for testing."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()

        return ASGIProtocol(worker)

    def _create_mock_request(self, **kwargs):
        """Create a mock WebSocket upgrade request."""
        request = mock.Mock()
        request.method = "GET"
        request.path = kwargs.get("path", "/ws")
        request.query = kwargs.get("query", "")
        request.version = kwargs.get("version", (1, 1))
        request.scheme = kwargs.get("scheme", "http")
        request.headers = kwargs.get("headers", [
            ("HOST", "localhost"),
            ("UPGRADE", "websocket"),
            ("CONNECTION", "upgrade"),
            ("SEC-WEBSOCKET-KEY", "dGhlIHNhbXBsZSBub25jZQ=="),
            ("SEC-WEBSOCKET-VERSION", "13"),
        ])
        return request

    def test_websocket_scope_type(self):
        """Test WebSocket scope type."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        scope = protocol._build_websocket_scope(
            request,
            ("127.0.0.1", 8000),
            ("127.0.0.1", 12345),
        )

        assert scope["type"] == "websocket"

    def test_websocket_scheme_ws(self):
        """Test WebSocket scheme for HTTP."""
        protocol = self._create_protocol()
        request = self._create_mock_request(scheme="http")

        scope = protocol._build_websocket_scope(request, None, None)

        assert scope["scheme"] == "ws"

    def test_websocket_scheme_wss(self):
        """Test WebSocket scheme for HTTPS."""
        protocol = self._create_protocol()
        request = self._create_mock_request(scheme="https")

        scope = protocol._build_websocket_scope(request, None, None)

        assert scope["scheme"] == "wss"

    def test_websocket_subprotocols(self):
        """Test WebSocket subprotocol extraction."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            headers=[
                ("HOST", "localhost"),
                ("UPGRADE", "websocket"),
                ("CONNECTION", "upgrade"),
                ("SEC-WEBSOCKET-KEY", "dGhlIHNhbXBsZSBub25jZQ=="),
                ("SEC-WEBSOCKET-VERSION", "13"),
                ("SEC-WEBSOCKET-PROTOCOL", "graphql-ws, subscriptions-transport-ws"),
            ]
        )

        scope = protocol._build_websocket_scope(request, None, None)

        assert "subprotocols" in scope
        assert "graphql-ws" in scope["subprotocols"]
        assert "subscriptions-transport-ws" in scope["subprotocols"]

    def test_websocket_no_subprotocols(self):
        """Test WebSocket scope without subprotocols."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        scope = protocol._build_websocket_scope(request, None, None)

        assert "subprotocols" in scope
        assert scope["subprotocols"] == []

    def test_websocket_asgi_version(self):
        """Test ASGI version in WebSocket scope."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        scope = protocol._build_websocket_scope(request, None, None)

        assert "asgi" in scope
        assert scope["asgi"]["version"] == "3.0"

    def test_websocket_required_keys(self):
        """Test all required keys are present in WebSocket scope."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        scope = protocol._build_websocket_scope(
            request,
            ("127.0.0.1", 8000),
            ("127.0.0.1", 12345),
        )

        required_keys = [
            "type", "asgi", "http_version", "scheme",
            "path", "raw_path", "query_string", "root_path",
            "headers", "server", "client", "subprotocols",
        ]
        for key in required_keys:
            assert key in scope, f"Missing required key: {key}"


# ============================================================================
# HTTP/2 Scope Tests
# ============================================================================

class TestHTTP2Scope:
    """Tests for HTTP/2 scope building."""

    def _create_protocol(self):
        """Create an ASGIProtocol instance for testing."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()

        return ASGIProtocol(worker)

    def _create_mock_http2_request(self, **kwargs):
        """Create a mock HTTP/2 request."""
        request = mock.Mock()
        request.method = kwargs.get("method", "GET")
        request.path = kwargs.get("path", "/")
        request.query = kwargs.get("query", "")
        request.uri = kwargs.get("uri", "/")
        request.scheme = kwargs.get("scheme", "https")
        request.headers = kwargs.get("headers", [])
        request.priority_weight = kwargs.get("priority_weight", 16)
        request.priority_depends_on = kwargs.get("priority_depends_on", 0)
        return request

    def test_http2_version_string(self):
        """Test HTTP/2 version string in scope."""
        protocol = self._create_protocol()
        request = self._create_mock_http2_request()

        scope = protocol._build_http2_scope(request, None, None)

        assert scope["http_version"] == "2"

    def test_http2_priority_extension(self):
        """Test HTTP/2 priority extension."""
        protocol = self._create_protocol()
        request = self._create_mock_http2_request(
            priority_weight=256,
            priority_depends_on=5,
        )

        scope = protocol._build_http2_scope(request, None, None)

        assert "extensions" in scope
        assert "http.response.priority" in scope["extensions"]
        priority = scope["extensions"]["http.response.priority"]
        assert priority["weight"] == 256
        assert priority["depends_on"] == 5

    def test_http2_trailers_extension(self):
        """Test HTTP/2 trailers extension present."""
        protocol = self._create_protocol()
        request = self._create_mock_http2_request()

        scope = protocol._build_http2_scope(request, None, None)

        assert "extensions" in scope
        assert "http.response.trailers" in scope["extensions"]

    def test_http2_scope_required_keys(self):
        """Test all required keys in HTTP/2 scope."""
        protocol = self._create_protocol()
        request = self._create_mock_http2_request()

        scope = protocol._build_http2_scope(
            request,
            ("127.0.0.1", 8443),
            ("127.0.0.1", 12345),
        )

        required_keys = [
            "type", "asgi", "http_version", "method", "scheme",
            "path", "raw_path", "query_string", "root_path",
            "headers", "server", "client", "extensions",
        ]
        for key in required_keys:
            assert key in scope, f"Missing required key: {key}"


# ============================================================================
# Server/Client Address Tests
# ============================================================================

class TestAddressHandling:
    """Tests for server and client address handling."""

    def _create_protocol(self):
        """Create an ASGIProtocol instance for testing."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()

        return ASGIProtocol(worker)

    def _create_mock_request(self):
        """Create a mock HTTP request."""
        request = mock.Mock()
        request.method = "GET"
        request.path = "/"
        request.query = ""
        request.version = (1, 1)
        request.scheme = "http"
        request.headers = []
        return request

    def test_ipv4_addresses(self):
        """Test IPv4 server and client addresses."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        scope = protocol._build_http_scope(
            request,
            ("192.168.1.1", 8000),
            ("192.168.1.100", 54321),
        )

        assert scope["server"] == ("192.168.1.1", 8000)
        assert scope["client"] == ("192.168.1.100", 54321)

    def test_ipv6_addresses(self):
        """Test IPv6 server and client addresses."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        scope = protocol._build_http_scope(
            request,
            ("::1", 8000),
            ("::1", 54321),
        )

        assert scope["server"] == ("::1", 8000)
        assert scope["client"] == ("::1", 54321)

    def test_localhost_addresses(self):
        """Test localhost addresses."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        scope = protocol._build_http_scope(
            request,
            ("127.0.0.1", 8000),
            ("127.0.0.1", 12345),
        )

        assert scope["server"] == ("127.0.0.1", 8000)
        assert scope["client"] == ("127.0.0.1", 12345)

    def test_addresses_none(self):
        """Test when addresses are not available."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        scope = protocol._build_http_scope(request, None, None)

        assert scope["server"] is None
        assert scope["client"] is None


# ============================================================================
# Environ Building Tests (for access logging)
# ============================================================================

class TestEnvironBuilding:
    """Tests for environ dict building (used for access logging)."""

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
        request.path = kwargs.get("path", "/")
        request.query = kwargs.get("query", "")
        request.uri = kwargs.get("uri", "/")
        request.version = kwargs.get("version", (1, 1))
        request.scheme = kwargs.get("scheme", "http")
        request.headers = kwargs.get("headers", [])
        return request

    def test_environ_request_method(self):
        """Test REQUEST_METHOD in environ."""
        protocol = self._create_protocol()
        request = self._create_mock_request(method="POST")

        environ = protocol._build_environ(
            request,
            ("127.0.0.1", 8000),
            ("127.0.0.1", 12345),
        )

        assert environ["REQUEST_METHOD"] == "POST"

    def test_environ_raw_uri(self):
        """Test RAW_URI in environ."""
        protocol = self._create_protocol()
        request = self._create_mock_request(uri="/api/users?page=1")

        environ = protocol._build_environ(request, None, None)

        assert environ["RAW_URI"] == "/api/users?page=1"

    def test_environ_path_info(self):
        """Test PATH_INFO in environ."""
        protocol = self._create_protocol()
        request = self._create_mock_request(path="/api/users")

        environ = protocol._build_environ(request, None, None)

        assert environ["PATH_INFO"] == "/api/users"

    def test_environ_query_string(self):
        """Test QUERY_STRING in environ."""
        protocol = self._create_protocol()
        request = self._create_mock_request(query="page=1&limit=10")

        environ = protocol._build_environ(request, None, None)

        assert environ["QUERY_STRING"] == "page=1&limit=10"

    def test_environ_server_protocol(self):
        """Test SERVER_PROTOCOL in environ."""
        protocol = self._create_protocol()
        request = self._create_mock_request(version=(1, 1))

        environ = protocol._build_environ(request, None, None)

        assert environ["SERVER_PROTOCOL"] == "HTTP/1.1"

    def test_environ_remote_addr(self):
        """Test REMOTE_ADDR in environ."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        environ = protocol._build_environ(
            request,
            None,
            ("192.168.1.100", 54321),
        )

        assert environ["REMOTE_ADDR"] == "192.168.1.100"

    def test_environ_remote_addr_missing(self):
        """Test REMOTE_ADDR when peername is None."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        environ = protocol._build_environ(request, None, None)

        assert environ["REMOTE_ADDR"] == "-"

    def test_environ_http_headers(self):
        """Test HTTP headers in environ."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            headers=[
                ("HOST", "localhost:8000"),
                ("USER-AGENT", "TestClient/1.0"),
                ("ACCEPT", "application/json"),
            ]
        )

        environ = protocol._build_environ(request, None, None)

        assert environ["HTTP_HOST"] == "localhost:8000"
        # Header names have dashes converted to underscores in environ
        assert environ["HTTP_USER_AGENT"] == "TestClient/1.0"
        assert environ["HTTP_ACCEPT"] == "application/json"
