#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
ASGI 3.0 specification compliance tests.

Tests that gunicorn's ASGI implementation conforms to the ASGI 3.0 spec:
https://asgi.readthedocs.io/en/latest/specs/main.html
"""

import asyncio
from unittest import mock

from gunicorn.config import Config


# ============================================================================
# ASGI Version Tests
# ============================================================================

class TestASGIVersion:
    """Test ASGI version information in scope."""

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

    def test_asgi_version_present(self):
        """Test that 'asgi' key is present in HTTP scope."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        scope = protocol._build_http_scope(
            request,
            ("127.0.0.1", 8000),
            ("127.0.0.1", 12345),
        )

        assert "asgi" in scope

    def test_asgi_version_is_dict(self):
        """Test that 'asgi' value is a dictionary."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        scope = protocol._build_http_scope(
            request,
            ("127.0.0.1", 8000),
            ("127.0.0.1", 12345),
        )

        assert isinstance(scope["asgi"], dict)

    def test_asgi_version_value(self):
        """Test that ASGI version is '3.0'."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        scope = protocol._build_http_scope(
            request,
            ("127.0.0.1", 8000),
            ("127.0.0.1", 12345),
        )

        assert scope["asgi"]["version"] == "3.0"

    def test_asgi_spec_version_present(self):
        """Test that spec_version is present in ASGI dict."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        scope = protocol._build_http_scope(
            request,
            ("127.0.0.1", 8000),
            ("127.0.0.1", 12345),
        )

        assert "spec_version" in scope["asgi"]

    def test_asgi_spec_version_value(self):
        """Test that spec_version follows semantic versioning."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        scope = protocol._build_http_scope(
            request,
            ("127.0.0.1", 8000),
            ("127.0.0.1", 12345),
        )

        spec_version = scope["asgi"]["spec_version"]
        # Should be in format "X.Y" (major.minor)
        parts = spec_version.split(".")
        assert len(parts) == 2
        assert all(part.isdigit() for part in parts)


# ============================================================================
# HTTP Scope Keys Tests (ASGI HTTP Connection Scope)
# ============================================================================

class TestHTTPScopeKeys:
    """Test required keys in HTTP connection scope per ASGI spec."""

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

    def test_type_key_present(self):
        """Test 'type' key is present and equals 'http'."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        scope = protocol._build_http_scope(
            request,
            ("127.0.0.1", 8000),
            ("127.0.0.1", 12345),
        )

        assert scope["type"] == "http"

    def test_http_version_key_present(self):
        """Test 'http_version' key is present."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        scope = protocol._build_http_scope(
            request,
            ("127.0.0.1", 8000),
            ("127.0.0.1", 12345),
        )

        assert "http_version" in scope
        assert scope["http_version"] == "1.1"

    def test_http_version_formats(self):
        """Test various HTTP version formats."""
        protocol = self._create_protocol()

        # HTTP/1.0
        request_10 = self._create_mock_request(version=(1, 0))
        scope_10 = protocol._build_http_scope(request_10, None, None)
        assert scope_10["http_version"] == "1.0"

        # HTTP/1.1
        request_11 = self._create_mock_request(version=(1, 1))
        scope_11 = protocol._build_http_scope(request_11, None, None)
        assert scope_11["http_version"] == "1.1"

    def test_method_key_present(self):
        """Test 'method' key is present and is uppercase string."""
        protocol = self._create_protocol()

        for method in ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]:
            request = self._create_mock_request(method=method)
            scope = protocol._build_http_scope(request, None, None)
            assert scope["method"] == method
            assert scope["method"].isupper()

    def test_scheme_key_present(self):
        """Test 'scheme' key is present."""
        protocol = self._create_protocol()

        # HTTP
        request_http = self._create_mock_request(scheme="http")
        scope_http = protocol._build_http_scope(request_http, None, None)
        assert scope_http["scheme"] == "http"

        # HTTPS
        request_https = self._create_mock_request(scheme="https")
        scope_https = protocol._build_http_scope(request_https, None, None)
        assert scope_https["scheme"] == "https"

    def test_path_key_present(self):
        """Test 'path' key is present and starts with /."""
        protocol = self._create_protocol()
        request = self._create_mock_request(path="/api/users")

        scope = protocol._build_http_scope(request, None, None)

        assert "path" in scope
        assert scope["path"] == "/api/users"
        assert scope["path"].startswith("/")

    def test_raw_path_key_present(self):
        """Test 'raw_path' key is present and is bytes."""
        protocol = self._create_protocol()
        request = self._create_mock_request(path="/api/users")

        scope = protocol._build_http_scope(request, None, None)

        assert "raw_path" in scope
        assert isinstance(scope["raw_path"], bytes)
        assert scope["raw_path"] == b"/api/users"

    def test_query_string_key_present(self):
        """Test 'query_string' key is present and is bytes."""
        protocol = self._create_protocol()
        request = self._create_mock_request(query="page=1&limit=10")

        scope = protocol._build_http_scope(request, None, None)

        assert "query_string" in scope
        assert isinstance(scope["query_string"], bytes)
        assert scope["query_string"] == b"page=1&limit=10"

    def test_query_string_empty(self):
        """Test 'query_string' is empty bytes when no query."""
        protocol = self._create_protocol()
        request = self._create_mock_request(query="")

        scope = protocol._build_http_scope(request, None, None)

        assert scope["query_string"] == b""

    def test_root_path_key_present(self):
        """Test 'root_path' key is present."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        scope = protocol._build_http_scope(request, None, None)

        assert "root_path" in scope
        assert isinstance(scope["root_path"], str)

    def test_headers_key_present(self):
        """Test 'headers' key is present and is list of 2-tuples."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            headers=[("HOST", "localhost"), ("ACCEPT", "text/html")]
        )

        scope = protocol._build_http_scope(request, None, None)

        assert "headers" in scope
        assert isinstance(scope["headers"], list)

        for header in scope["headers"]:
            assert isinstance(header, tuple)
            assert len(header) == 2

    def test_headers_are_bytes(self):
        """Test that header names and values are bytes."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            headers=[("HOST", "localhost"), ("CONTENT-TYPE", "application/json")]
        )

        scope = protocol._build_http_scope(request, None, None)

        for name, value in scope["headers"]:
            assert isinstance(name, bytes), f"Header name should be bytes: {name}"
            assert isinstance(value, bytes), f"Header value should be bytes: {value}"

    def test_headers_names_lowercase(self):
        """Test that header names are lowercase."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            headers=[("HOST", "localhost"), ("Content-Type", "application/json")]
        )

        scope = protocol._build_http_scope(request, None, None)

        for name, _ in scope["headers"]:
            assert name == name.lower(), f"Header name should be lowercase: {name}"

    def test_server_key_present(self):
        """Test 'server' key is present when sockname provided."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        scope = protocol._build_http_scope(
            request,
            ("127.0.0.1", 8000),
            ("127.0.0.1", 12345),
        )

        assert "server" in scope
        assert scope["server"] == ("127.0.0.1", 8000)

    def test_server_key_none(self):
        """Test 'server' key is None when sockname not provided."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        scope = protocol._build_http_scope(request, None, None)

        assert scope["server"] is None

    def test_client_key_present(self):
        """Test 'client' key is present when peername provided."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        scope = protocol._build_http_scope(
            request,
            ("127.0.0.1", 8000),
            ("192.168.1.100", 54321),
        )

        assert "client" in scope
        assert scope["client"] == ("192.168.1.100", 54321)

    def test_client_key_none(self):
        """Test 'client' key is None when peername not provided."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        scope = protocol._build_http_scope(request, None, None)

        assert scope["client"] is None


# ============================================================================
# HTTP Message Format Tests
# ============================================================================

class TestHTTPMessageFormats:
    """Test HTTP message formats per ASGI spec."""

    def test_http_request_message_format(self):
        """Test http.request message format."""
        message = {
            "type": "http.request",
            "body": b"request body",
            "more_body": False,
        }

        assert message["type"] == "http.request"
        assert isinstance(message["body"], bytes)
        assert isinstance(message["more_body"], bool)

    def test_http_request_message_empty_body(self):
        """Test http.request message with empty body."""
        message = {
            "type": "http.request",
            "body": b"",
            "more_body": False,
        }

        assert message["body"] == b""
        assert message["more_body"] is False

    def test_http_response_start_format(self):
        """Test http.response.start message format."""
        message = {
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"text/plain"),
                (b"content-length", b"13"),
            ],
        }

        assert message["type"] == "http.response.start"
        assert isinstance(message["status"], int)
        assert 100 <= message["status"] < 600
        assert isinstance(message["headers"], list)

    def test_http_response_body_format(self):
        """Test http.response.body message format."""
        message = {
            "type": "http.response.body",
            "body": b"Hello, World!",
            "more_body": False,
        }

        assert message["type"] == "http.response.body"
        assert isinstance(message["body"], bytes)
        assert isinstance(message["more_body"], bool)

    def test_http_response_body_streaming(self):
        """Test http.response.body message for streaming."""
        # First chunk
        chunk1 = {
            "type": "http.response.body",
            "body": b"First chunk",
            "more_body": True,
        }

        # Last chunk
        chunk2 = {
            "type": "http.response.body",
            "body": b"Last chunk",
            "more_body": False,
        }

        assert chunk1["more_body"] is True
        assert chunk2["more_body"] is False

    def test_http_disconnect_format(self):
        """Test http.disconnect message format."""
        message = {"type": "http.disconnect"}

        assert message["type"] == "http.disconnect"


# ============================================================================
# HTTP Response Status Codes Tests
# ============================================================================

class TestHTTPStatusCodes:
    """Test HTTP status code handling."""

    def _create_protocol(self):
        """Create an ASGIProtocol instance for testing."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()

        return ASGIProtocol(worker)

    def test_reason_phrase_informational(self):
        """Test reason phrases for 1xx status codes."""
        protocol = self._create_protocol()

        assert protocol._get_reason_phrase(100) == "Continue"
        assert protocol._get_reason_phrase(101) == "Switching Protocols"
        assert protocol._get_reason_phrase(103) == "Early Hints"

    def test_reason_phrase_success(self):
        """Test reason phrases for 2xx status codes."""
        protocol = self._create_protocol()

        assert protocol._get_reason_phrase(200) == "OK"
        assert protocol._get_reason_phrase(201) == "Created"
        assert protocol._get_reason_phrase(202) == "Accepted"
        assert protocol._get_reason_phrase(204) == "No Content"
        assert protocol._get_reason_phrase(206) == "Partial Content"

    def test_reason_phrase_redirect(self):
        """Test reason phrases for 3xx status codes."""
        protocol = self._create_protocol()

        assert protocol._get_reason_phrase(301) == "Moved Permanently"
        assert protocol._get_reason_phrase(302) == "Found"
        assert protocol._get_reason_phrase(303) == "See Other"
        assert protocol._get_reason_phrase(304) == "Not Modified"
        assert protocol._get_reason_phrase(307) == "Temporary Redirect"
        assert protocol._get_reason_phrase(308) == "Permanent Redirect"

    def test_reason_phrase_client_error(self):
        """Test reason phrases for 4xx status codes."""
        protocol = self._create_protocol()

        assert protocol._get_reason_phrase(400) == "Bad Request"
        assert protocol._get_reason_phrase(401) == "Unauthorized"
        assert protocol._get_reason_phrase(403) == "Forbidden"
        assert protocol._get_reason_phrase(404) == "Not Found"
        assert protocol._get_reason_phrase(405) == "Method Not Allowed"
        assert protocol._get_reason_phrase(408) == "Request Timeout"
        assert protocol._get_reason_phrase(409) == "Conflict"
        assert protocol._get_reason_phrase(410) == "Gone"
        assert protocol._get_reason_phrase(422) == "Unprocessable Entity"
        assert protocol._get_reason_phrase(429) == "Too Many Requests"

    def test_reason_phrase_server_error(self):
        """Test reason phrases for 5xx status codes."""
        protocol = self._create_protocol()

        assert protocol._get_reason_phrase(500) == "Internal Server Error"
        assert protocol._get_reason_phrase(501) == "Not Implemented"
        assert protocol._get_reason_phrase(502) == "Bad Gateway"
        assert protocol._get_reason_phrase(503) == "Service Unavailable"
        assert protocol._get_reason_phrase(504) == "Gateway Timeout"

    def test_reason_phrase_unknown(self):
        """Test reason phrase for unknown status codes."""
        protocol = self._create_protocol()

        assert protocol._get_reason_phrase(999) == "Unknown"
        assert protocol._get_reason_phrase(418) == "Unknown"  # I'm a teapot not defined


# ============================================================================
# Informational Response Tests (103 Early Hints, etc.)
# ============================================================================

class TestInformationalResponses:
    """Test support for HTTP 1xx informational responses."""

    def test_http_response_informational_format(self):
        """Test http.response.informational message format."""
        message = {
            "type": "http.response.informational",
            "status": 103,
            "headers": [
                (b"link", b"</style.css>; rel=preload; as=style"),
            ],
        }

        assert message["type"] == "http.response.informational"
        assert 100 <= message["status"] < 200
        assert isinstance(message["headers"], list)

    def test_early_hints_103(self):
        """Test 103 Early Hints message format."""
        message = {
            "type": "http.response.informational",
            "status": 103,
            "headers": [
                (b"link", b"</style.css>; rel=preload; as=style"),
                (b"link", b"</script.js>; rel=preload; as=script"),
            ],
        }

        assert message["status"] == 103


# ============================================================================
# ASGI Extensions Tests
# ============================================================================

class TestASGIExtensions:
    """Test ASGI extensions support."""

    def _create_protocol(self):
        """Create an ASGIProtocol instance for testing."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()

        return ASGIProtocol(worker)

    def _create_mock_http2_request(self, **kwargs):
        """Create a mock HTTP/2 request with priority."""
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

    def test_http2_scope_has_extensions(self):
        """Test that HTTP/2 scope includes extensions dict."""
        protocol = self._create_protocol()
        request = self._create_mock_http2_request()

        scope = protocol._build_http2_scope(request, None, None)

        assert "extensions" in scope
        assert isinstance(scope["extensions"], dict)

    def test_http2_priority_extension(self):
        """Test http.response.priority extension in HTTP/2 scope."""
        protocol = self._create_protocol()
        request = self._create_mock_http2_request(
            priority_weight=128,
            priority_depends_on=5,
        )

        scope = protocol._build_http2_scope(request, None, None)

        assert "http.response.priority" in scope["extensions"]
        priority = scope["extensions"]["http.response.priority"]
        assert "weight" in priority
        assert "depends_on" in priority
        assert priority["weight"] == 128
        assert priority["depends_on"] == 5

    def test_http2_trailers_extension(self):
        """Test http.response.trailers extension in HTTP/2 scope."""
        protocol = self._create_protocol()
        request = self._create_mock_http2_request()

        scope = protocol._build_http2_scope(request, None, None)

        assert "http.response.trailers" in scope["extensions"]

    def test_http_response_trailers_message_format(self):
        """Test http.response.trailers message format."""
        message = {
            "type": "http.response.trailers",
            "headers": [
                (b"grpc-status", b"0"),
                (b"grpc-message", b""),
            ],
            "more_trailers": False,
        }

        assert message["type"] == "http.response.trailers"
        assert isinstance(message["headers"], list)


# ============================================================================
# State Sharing Tests
# ============================================================================

class TestStateSharing:
    """Test state sharing between lifespan and request scopes."""

    def _create_protocol_with_state(self, state):
        """Create an ASGIProtocol with worker state."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()
        worker.state = state

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

    def test_state_in_http_scope(self):
        """Test that state dict is included in HTTP scope."""
        state = {"db": "connected", "cache": "ready"}
        protocol = self._create_protocol_with_state(state)
        request = self._create_mock_request()

        scope = protocol._build_http_scope(request, None, None)

        assert "state" in scope
        assert scope["state"] == state

    def test_state_is_same_object(self):
        """Test that state is the same object (not a copy)."""
        state = {"counter": 0}
        protocol = self._create_protocol_with_state(state)
        request = self._create_mock_request()

        scope = protocol._build_http_scope(request, None, None)

        # Modifying scope["state"] should modify the original
        scope["state"]["counter"] = 1
        assert state["counter"] == 1

    def test_state_not_present_without_worker_state(self):
        """Test that state is not in scope if worker has no state."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock(spec=["cfg", "log", "asgi"])
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()

        protocol = ASGIProtocol(worker)
        request = self._create_mock_request()

        scope = protocol._build_http_scope(request, None, None)

        assert "state" not in scope


# ============================================================================
# HTTP Disconnect Event Tests (ASGI Spec Compliance)
# https://asgi.readthedocs.io/en/latest/specs/www.html#disconnect-receive-event
# ============================================================================

class TestHTTPDisconnectEvent:
    """Test http.disconnect event compliance with ASGI spec.

    Per the ASGI HTTP Connection Scope spec:
    - Disconnect event is sent when client closes connection
    - Event type MUST be "http.disconnect"
    - Apps should receive this event and clean up gracefully
    """

    def _create_protocol(self):
        """Create an ASGIProtocol instance for testing."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()
        worker.nr_conns = 1
        worker.loop = mock.Mock()

        protocol = ASGIProtocol(worker)
        protocol.reader = mock.Mock()

        return protocol

    def test_disconnect_event_type(self):
        """Test that disconnect event has correct type per ASGI spec."""
        protocol = self._create_protocol()
        protocol._receive_queue = asyncio.Queue()

        # Simulate client disconnect
        protocol.connection_lost(None)

        # Get the message from queue
        msg = protocol._receive_queue.get_nowait()

        # Per ASGI spec: type MUST be "http.disconnect"
        assert msg["type"] == "http.disconnect"

    def test_disconnect_event_sent_on_connection_lost(self):
        """Test that http.disconnect is sent when connection is lost."""
        protocol = self._create_protocol()
        protocol._receive_queue = asyncio.Queue()

        assert protocol._receive_queue.empty()

        # Simulate client disconnect
        protocol.connection_lost(None)

        # Queue should have disconnect message
        assert not protocol._receive_queue.empty()

    def test_disconnect_sets_closed_flag(self):
        """Test that connection_lost sets the closed flag."""
        protocol = self._create_protocol()

        assert protocol._closed is False

        protocol.connection_lost(None)

        assert protocol._closed is True

    def test_disconnect_allows_graceful_cleanup(self):
        """Test that disconnect doesn't immediately cancel task.

        Per ASGI spec, apps should have opportunity to clean up
        when they receive http.disconnect.
        """
        protocol = self._create_protocol()

        # Create a mock task
        mock_task = mock.Mock()
        mock_task.done.return_value = False
        protocol._task = mock_task

        # Simulate disconnect
        protocol.connection_lost(None)

        # Task should NOT be cancelled immediately
        mock_task.cancel.assert_not_called()

        # Cancellation should be scheduled after grace period
        protocol.worker.loop.call_later.assert_called_once()

    def test_disconnect_message_format(self):
        """Test http.disconnect message format per ASGI spec.

        The disconnect message should only contain 'type' key.
        """
        protocol = self._create_protocol()
        protocol._receive_queue = asyncio.Queue()

        protocol.connection_lost(None)

        msg = protocol._receive_queue.get_nowait()

        # Per ASGI spec, disconnect message only has 'type'
        assert msg == {"type": "http.disconnect"}
        assert len(msg) == 1
