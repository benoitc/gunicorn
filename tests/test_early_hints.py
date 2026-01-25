# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for HTTP 103 Early Hints support (RFC 8297)."""

import pytest
from unittest import mock
from io import BytesIO

# Check if h2 is available for HTTP/2 tests
try:
    import h2.connection
    import h2.config
    import h2.events
    H2_AVAILABLE = True
except ImportError:
    H2_AVAILABLE = False

from gunicorn.http import wsgi


class MockConfig:
    """Mock gunicorn configuration."""

    def __init__(self):
        self.is_ssl = False
        self.workers = 1
        self.limit_request_fields = 100
        self.limit_request_field_size = 8190
        self.limit_request_line = 8190
        self.secure_scheme_headers = {}
        self.forwarded_allow_ips = ['127.0.0.1']
        self.forwarder_headers = []
        self.strip_header_spaces = False
        self.permit_obsolete_folding = False
        self.header_map = "refuse"
        self.sendfile = True
        self.errorlog = "-"

        # HTTP/2 settings
        self.http2_max_concurrent_streams = 100
        self.http2_initial_window_size = 65535
        self.http2_max_frame_size = 16384
        self.http2_max_header_list_size = 65536

    def forwarded_allow_networks(self):
        return []


class MockRequest:
    """Mock HTTP request for testing."""

    def __init__(self, version=(1, 1)):
        self.version = version
        self.method = "GET"
        self.uri = "/"
        self.path = "/"
        self.query = ""
        self.fragment = ""
        self.scheme = "http"
        self.headers = []
        self.body = BytesIO(b"")
        self.proxy_protocol_info = None
        self._expected_100_continue = False

    def should_close(self):
        return False


class MockSocket:
    """Mock socket for testing."""

    def __init__(self):
        self._sent = bytearray()
        self._closed = False

    def sendall(self, data):
        if self._closed:
            raise OSError("Socket is closed")
        self._sent.extend(data)

    def send(self, data):
        if self._closed:
            raise OSError("Socket is closed")
        self._sent.extend(data)
        return len(data)

    def get_sent_data(self):
        return bytes(self._sent)

    def clear(self):
        self._sent = bytearray()

    def close(self):
        self._closed = True


class TestWSGIEarlyHints:
    """Test WSGI wsgi.early_hints callback."""

    def test_early_hints_callback_in_environ(self):
        """Verify wsgi.early_hints is added to environ."""
        cfg = MockConfig()
        req = MockRequest()
        sock = MockSocket()

        resp, environ = wsgi.create(req, sock, ('127.0.0.1', 12345),
                                    ('127.0.0.1', 8000), cfg)

        assert 'wsgi.early_hints' in environ
        assert callable(environ['wsgi.early_hints'])

    def test_send_single_early_hint(self):
        """Test sending one Link header as early hint."""
        cfg = MockConfig()
        req = MockRequest(version=(1, 1))
        sock = MockSocket()

        resp, environ = wsgi.create(req, sock, ('127.0.0.1', 12345),
                                    ('127.0.0.1', 8000), cfg)

        # Send early hints
        environ['wsgi.early_hints']([
            ('Link', '</style.css>; rel=preload; as=style'),
        ])

        sent_data = sock.get_sent_data()
        assert b"HTTP/1.1 103 Early Hints\r\n" in sent_data
        assert b"Link: </style.css>; rel=preload; as=style\r\n" in sent_data
        assert sent_data.endswith(b"\r\n\r\n")

    def test_send_multiple_early_hints(self):
        """Test sending multiple Link headers."""
        cfg = MockConfig()
        req = MockRequest(version=(1, 1))
        sock = MockSocket()

        resp, environ = wsgi.create(req, sock, ('127.0.0.1', 12345),
                                    ('127.0.0.1', 8000), cfg)

        environ['wsgi.early_hints']([
            ('Link', '</style.css>; rel=preload; as=style'),
            ('Link', '</app.js>; rel=preload; as=script'),
        ])

        sent_data = sock.get_sent_data()
        assert b"HTTP/1.1 103 Early Hints\r\n" in sent_data
        assert b"Link: </style.css>; rel=preload; as=style\r\n" in sent_data
        assert b"Link: </app.js>; rel=preload; as=script\r\n" in sent_data

    def test_early_hints_not_sent_for_http10(self):
        """Test that early hints are not sent for HTTP/1.0 clients."""
        cfg = MockConfig()
        req = MockRequest(version=(1, 0))  # HTTP/1.0
        sock = MockSocket()

        resp, environ = wsgi.create(req, sock, ('127.0.0.1', 12345),
                                    ('127.0.0.1', 8000), cfg)

        # Try to send early hints
        environ['wsgi.early_hints']([
            ('Link', '</style.css>; rel=preload; as=style'),
        ])

        # Nothing should be sent for HTTP/1.0
        sent_data = sock.get_sent_data()
        assert sent_data == b""

    def test_multiple_early_hints_calls(self):
        """Test multiple calls to wsgi.early_hints (multiple 103 responses)."""
        cfg = MockConfig()
        req = MockRequest(version=(1, 1))
        sock = MockSocket()

        resp, environ = wsgi.create(req, sock, ('127.0.0.1', 12345),
                                    ('127.0.0.1', 8000), cfg)

        # First early hints call
        environ['wsgi.early_hints']([
            ('Link', '</critical.css>; rel=preload; as=style'),
        ])

        # Second early hints call
        environ['wsgi.early_hints']([
            ('Link', '</app.js>; rel=preload; as=script'),
        ])

        sent_data = sock.get_sent_data()
        # Should have two separate 103 responses
        assert sent_data.count(b"HTTP/1.1 103 Early Hints\r\n") == 2

    def test_early_hints_with_bytes_headers(self):
        """Test early hints with bytes header values."""
        cfg = MockConfig()
        req = MockRequest(version=(1, 1))
        sock = MockSocket()

        resp, environ = wsgi.create(req, sock, ('127.0.0.1', 12345),
                                    ('127.0.0.1', 8000), cfg)

        # Send with bytes values
        environ['wsgi.early_hints']([
            (b'Link', b'</style.css>; rel=preload; as=style'),
        ])

        sent_data = sock.get_sent_data()
        assert b"HTTP/1.1 103 Early Hints\r\n" in sent_data
        assert b"Link: </style.css>; rel=preload; as=style\r\n" in sent_data

    def test_empty_early_hints(self):
        """Test early hints with empty headers list."""
        cfg = MockConfig()
        req = MockRequest(version=(1, 1))
        sock = MockSocket()

        resp, environ = wsgi.create(req, sock, ('127.0.0.1', 12345),
                                    ('127.0.0.1', 8000), cfg)

        # Send empty headers
        environ['wsgi.early_hints']([])

        sent_data = sock.get_sent_data()
        # Should still send 103 response with no headers
        assert sent_data == b"HTTP/1.1 103 Early Hints\r\n\r\n"


@pytest.mark.skipif(not H2_AVAILABLE, reason="h2 library not available")
class TestHTTP2EarlyHints:
    """Test HTTP/2 early hints (send_informational method)."""

    def _create_mock_http2_config(self):
        """Create mock config for HTTP/2."""
        cfg = MockConfig()
        return cfg

    def _create_mock_socket(self):
        """Create mock socket for HTTP/2."""
        return MockSocket()

    def test_send_informational_method_exists(self):
        """Test that send_informational method exists on HTTP2ServerConnection."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = self._create_mock_http2_config()
        sock = self._create_mock_socket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))

        assert hasattr(conn, 'send_informational')
        assert callable(conn.send_informational)

    def test_send_informational_invalid_status(self):
        """Test send_informational raises for non-1xx status."""
        from gunicorn.http2.connection import HTTP2ServerConnection
        from gunicorn.http2.errors import HTTP2Error

        cfg = self._create_mock_http2_config()
        sock = self._create_mock_socket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        # Need to create a stream first
        client_conn = h2.connection.H2Connection(
            config=h2.config.H2Configuration(client_side=True)
        )
        client_conn.initiate_connection()

        # Get client's initial data
        client_data = client_conn.data_to_send()
        conn.receive_data(client_data)

        # Create a request on the client
        client_conn.send_headers(1, [
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=True)
        request_data = client_conn.data_to_send()
        conn.receive_data(request_data)

        # Try to send 200 as informational (should fail)
        with pytest.raises(HTTP2Error) as excinfo:
            conn.send_informational(1, 200, [('link', '</style.css>')])
        assert "Invalid informational status" in str(excinfo.value)

    def test_send_informational_103(self):
        """Test sending 103 Early Hints over HTTP/2."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = self._create_mock_http2_config()
        sock = self._create_mock_socket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        # Create a client connection
        client_conn = h2.connection.H2Connection(
            config=h2.config.H2Configuration(client_side=True)
        )
        client_conn.initiate_connection()
        client_data = client_conn.data_to_send()
        conn.receive_data(client_data)

        # Create a request on the client
        client_conn.send_headers(1, [
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=True)
        request_data = client_conn.data_to_send()
        conn.receive_data(request_data)

        # Clear sent data to isolate the informational response
        sock.clear()

        # Send 103 Early Hints
        conn.send_informational(1, 103, [
            ('link', '</style.css>; rel=preload; as=style'),
        ])

        # Verify data was sent
        sent_data = sock.get_sent_data()
        assert len(sent_data) > 0

        # Feed the data back to client to verify it's valid HTTP/2
        client_conn.receive_data(sent_data)
        # Client should receive an informational response

    def test_send_informational_stream_not_found(self):
        """Test send_informational raises for non-existent stream."""
        from gunicorn.http2.connection import HTTP2ServerConnection
        from gunicorn.http2.errors import HTTP2Error

        cfg = self._create_mock_http2_config()
        sock = self._create_mock_socket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        # Try to send on non-existent stream
        with pytest.raises(HTTP2Error) as excinfo:
            conn.send_informational(999, 103, [('link', '</style.css>')])
        assert "not found" in str(excinfo.value)


@pytest.mark.skipif(not H2_AVAILABLE, reason="h2 library not available")
class TestAsyncHTTP2EarlyHints:
    """Test async HTTP/2 early hints."""

    def test_async_send_informational_method_exists(self):
        """Test that send_informational method exists on AsyncHTTP2Connection."""
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = mock.MagicMock()
        writer = mock.MagicMock()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))

        assert hasattr(conn, 'send_informational')
        assert callable(conn.send_informational)


class TestASGIEarlyHints:
    """Test ASGI http.response.informational handling."""

    def test_reason_phrase_103(self):
        """Test that 103 has correct reason phrase."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.MagicMock()
        worker.cfg = MockConfig()
        worker.log = mock.MagicMock()

        protocol = ASGIProtocol(worker)
        reason = protocol._get_reason_phrase(103)
        assert reason == "Early Hints"

    def test_reason_phrase_100(self):
        """Test that 100 Continue has correct reason phrase."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.MagicMock()
        worker.cfg = MockConfig()
        worker.log = mock.MagicMock()

        protocol = ASGIProtocol(worker)
        reason = protocol._get_reason_phrase(100)
        assert reason == "Continue"

    def test_reason_phrase_101(self):
        """Test that 101 Switching Protocols has correct reason phrase."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.MagicMock()
        worker.cfg = MockConfig()
        worker.log = mock.MagicMock()

        protocol = ASGIProtocol(worker)
        reason = protocol._get_reason_phrase(101)
        assert reason == "Switching Protocols"
