# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Integration tests for HTTP/2 with full request/response cycles."""

import pytest
from io import BytesIO

# Check if h2 is available
try:
    import h2.connection
    import h2.config
    import h2.events
    H2_AVAILABLE = True
except ImportError:
    H2_AVAILABLE = False


pytestmark = pytest.mark.skipif(not H2_AVAILABLE, reason="h2 library not available")


def get_header_value(headers_list, name):
    """Extract a header value from h2 headers list.

    h2 library may return headers as bytes or strings depending on version.
    """
    for header_name, header_value in headers_list:
        name_str = header_name.decode() if isinstance(header_name, bytes) else header_name
        if name_str == name:
            return header_value.decode() if isinstance(header_value, bytes) else header_value
    return None


class MockConfig:
    """Mock gunicorn configuration for HTTP/2."""

    def __init__(self):
        self.http2_max_concurrent_streams = 100
        self.http2_initial_window_size = 65535
        self.http2_max_frame_size = 16384
        self.http2_max_header_list_size = 65536


class MockSocket:
    """Mock socket for integration testing."""

    def __init__(self, data=b''):
        self._recv_buffer = BytesIO(data)
        self._sent = bytearray()

    def recv(self, size):
        return self._recv_buffer.read(size)

    def sendall(self, data):
        self._sent.extend(data)

    def get_sent_data(self):
        return bytes(self._sent)

    def set_recv_data(self, data):
        self._recv_buffer = BytesIO(data)

    def clear_sent(self):
        self._sent.clear()


def create_h2_client():
    """Create an h2 client connection."""
    config = h2.config.H2Configuration(client_side=True)
    conn = h2.connection.H2Connection(config=config)
    conn.initiate_connection()
    return conn


class TestSimpleRequestResponse:
    """Test simple request/response cycles."""

    def test_get_request_text_response(self):
        """Test a complete GET request with text response."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        server = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        server.initiate_connection()

        # Client setup
        client = create_h2_client()
        sock.set_recv_data(client.data_to_send())
        server.receive_data()
        client.receive_data(sock.get_sent_data())

        # Client sends request
        client.send_headers(1, [
            (':method', 'GET'),
            (':path', '/hello'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
            ('accept', 'text/plain'),
        ], end_stream=True)
        sock.set_recv_data(client.data_to_send())

        # Server receives request
        requests = server.receive_data()
        assert len(requests) == 1
        req = requests[0]

        # Verify request properties
        assert req.method == 'GET'
        assert req.path == '/hello'
        assert req.version == (2, 0)
        assert req.get_header('ACCEPT') == 'text/plain'

        # Server sends response
        sock.clear_sent()
        server.send_response(
            stream_id=1,
            status=200,
            headers=[
                ('content-type', 'text/plain'),
                ('content-length', '12'),
            ],
            body=b'Hello World!'
        )

        # Client verifies response
        events = client.receive_data(sock.get_sent_data())

        response_events = [e for e in events if isinstance(e, h2.events.ResponseReceived)]
        assert len(response_events) == 1
        headers_list = response_events[0].headers
        assert get_header_value(headers_list, ':status') == '200'
        assert get_header_value(headers_list, 'content-type') == 'text/plain'

        data_events = [e for e in events if isinstance(e, h2.events.DataReceived)]
        assert len(data_events) == 1
        assert data_events[0].data == b'Hello World!'

    def test_post_request_with_json_body(self):
        """Test POST request with JSON body and response."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        server = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        server.initiate_connection()

        client = create_h2_client()
        sock.set_recv_data(client.data_to_send())
        server.receive_data()
        client.receive_data(sock.get_sent_data())

        # Client sends POST with body
        request_body = b'{"username": "test", "action": "login"}'
        client.send_headers(1, [
            (':method', 'POST'),
            (':path', '/api/login'),
            (':scheme', 'https'),
            (':authority', 'api.example.com'),
            ('content-type', 'application/json'),
            ('content-length', str(len(request_body))),
        ], end_stream=False)
        client.send_data(1, request_body, end_stream=True)
        sock.set_recv_data(client.data_to_send())

        requests = server.receive_data()
        assert len(requests) == 1
        req = requests[0]

        assert req.method == 'POST'
        assert req.content_type == 'application/json'
        assert req.body.read() == request_body

        # Server responds
        sock.clear_sent()
        response_body = b'{"status": "success", "token": "abc123"}'
        server.send_response(
            stream_id=1,
            status=200,
            headers=[
                ('content-type', 'application/json'),
                ('content-length', str(len(response_body))),
            ],
            body=response_body
        )

        events = client.receive_data(sock.get_sent_data())
        data_events = [e for e in events if isinstance(e, h2.events.DataReceived)]
        assert data_events[0].data == response_body


class TestMultipleStreams:
    """Test concurrent stream handling."""

    def test_concurrent_requests(self):
        """Test handling multiple concurrent requests."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        server = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        server.initiate_connection()

        client = create_h2_client()
        sock.set_recv_data(client.data_to_send())
        server.receive_data()
        client.receive_data(sock.get_sent_data())

        # Client sends three concurrent requests
        for stream_id, path in [(1, '/one'), (3, '/two'), (5, '/three')]:
            client.send_headers(stream_id, [
                (':method', 'GET'),
                (':path', path),
                (':scheme', 'https'),
                (':authority', 'example.com'),
            ], end_stream=True)

        sock.set_recv_data(client.data_to_send())
        requests = server.receive_data()

        assert len(requests) == 3
        paths = {req.path for req in requests}
        assert paths == {'/one', '/two', '/three'}

        # Server responds to all
        sock.clear_sent()
        for req in requests:
            server.send_response(
                stream_id=req.stream.stream_id,
                status=200,
                headers=[('x-path', req.path)],
                body=req.path.encode()
            )

        events = client.receive_data(sock.get_sent_data())
        response_events = [e for e in events if isinstance(e, h2.events.ResponseReceived)]
        assert len(response_events) == 3

    def test_interleaved_request_response(self):
        """Test interleaved request and response processing."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        server = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        server.initiate_connection()

        client = create_h2_client()
        sock.set_recv_data(client.data_to_send())
        server.receive_data()
        client.receive_data(sock.get_sent_data())

        # First request
        client.send_headers(1, [
            (':method', 'GET'),
            (':path', '/first'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
        ], end_stream=True)
        sock.set_recv_data(client.data_to_send())
        requests = server.receive_data()
        assert len(requests) == 1

        # Respond to first before second arrives
        sock.clear_sent()
        server.send_response(1, 200, [], b'First response')
        client.receive_data(sock.get_sent_data())

        # Second request
        client.send_headers(3, [
            (':method', 'GET'),
            (':path', '/second'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
        ], end_stream=True)
        sock.set_recv_data(client.data_to_send())
        requests = server.receive_data()
        assert len(requests) == 1

        # Respond to second
        sock.clear_sent()
        server.send_response(3, 200, [], b'Second response')
        events = client.receive_data(sock.get_sent_data())
        data_events = [e for e in events if isinstance(e, h2.events.DataReceived)]
        assert data_events[0].data == b'Second response'


class TestErrorHandling:
    """Test error response scenarios."""

    def test_404_response(self):
        """Test 404 Not Found response."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        server = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        server.initiate_connection()

        client = create_h2_client()
        sock.set_recv_data(client.data_to_send())
        server.receive_data()
        client.receive_data(sock.get_sent_data())

        client.send_headers(1, [
            (':method', 'GET'),
            (':path', '/nonexistent'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
        ], end_stream=True)
        sock.set_recv_data(client.data_to_send())
        server.receive_data()

        sock.clear_sent()
        server.send_error(1, 404, "Not Found")

        events = client.receive_data(sock.get_sent_data())
        response_events = [e for e in events if isinstance(e, h2.events.ResponseReceived)]
        headers_list = response_events[0].headers
        assert get_header_value(headers_list, ':status') == '404'

    def test_500_response(self):
        """Test 500 Internal Server Error response."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        server = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        server.initiate_connection()

        client = create_h2_client()
        sock.set_recv_data(client.data_to_send())
        server.receive_data()
        client.receive_data(sock.get_sent_data())

        client.send_headers(1, [
            (':method', 'GET'),
            (':path', '/error'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
        ], end_stream=True)
        sock.set_recv_data(client.data_to_send())
        server.receive_data()

        sock.clear_sent()
        server.send_error(1, 500, "Internal Server Error")

        events = client.receive_data(sock.get_sent_data())
        response_events = [e for e in events if isinstance(e, h2.events.ResponseReceived)]
        headers_list = response_events[0].headers
        assert get_header_value(headers_list, ':status') == '500'

    def test_stream_reset_by_server(self):
        """Test server resetting a stream."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        server = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        server.initiate_connection()

        client = create_h2_client()
        sock.set_recv_data(client.data_to_send())
        server.receive_data()
        client.receive_data(sock.get_sent_data())

        # Start a request but don't finish
        client.send_headers(1, [
            (':method', 'POST'),
            (':path', '/upload'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
        ], end_stream=False)
        sock.set_recv_data(client.data_to_send())
        server.receive_data()

        # Server resets the stream
        sock.clear_sent()
        server.reset_stream(1, error_code=0x8)  # CANCEL

        events = client.receive_data(sock.get_sent_data())
        reset_events = [e for e in events if isinstance(e, h2.events.StreamReset)]
        assert len(reset_events) == 1
        assert reset_events[0].error_code == 0x8


class TestConnectionLifecycle:
    """Test connection lifecycle events."""

    def test_graceful_shutdown(self):
        """Test graceful connection shutdown with GOAWAY."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        server = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        server.initiate_connection()

        client = create_h2_client()
        sock.set_recv_data(client.data_to_send())
        server.receive_data()
        client.receive_data(sock.get_sent_data())

        # Process a request first
        client.send_headers(1, [
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
        ], end_stream=True)
        sock.set_recv_data(client.data_to_send())
        server.receive_data()

        sock.clear_sent()
        server.send_response(1, 200, [], b'OK')
        client.receive_data(sock.get_sent_data())

        # Server initiates graceful shutdown
        sock.clear_sent()
        server.close()

        events = client.receive_data(sock.get_sent_data())
        goaway_events = [e for e in events if isinstance(e, h2.events.ConnectionTerminated)]
        assert len(goaway_events) == 1

    def test_client_initiated_close(self):
        """Test handling client-initiated connection close."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        server = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        server.initiate_connection()

        client = create_h2_client()
        sock.set_recv_data(client.data_to_send())
        server.receive_data()
        client.receive_data(sock.get_sent_data())

        # Client closes connection
        client.close_connection()
        sock.set_recv_data(client.data_to_send())
        server.receive_data()

        assert server.is_closed is True


class TestLargePayloads:
    """Test handling of large payloads."""

    def test_moderate_request_body(self):
        """Test handling moderate-sized request body within flow control."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        server = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        server.initiate_connection()

        client = create_h2_client()
        sock.set_recv_data(client.data_to_send())
        server.receive_data()
        client.receive_data(sock.get_sent_data())

        # Send body that fits within initial window (65535 bytes)
        body = b'X' * 10000
        client.send_headers(1, [
            (':method', 'POST'),
            (':path', '/upload'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
            ('content-length', str(len(body))),
        ], end_stream=False)
        client.send_data(1, body, end_stream=True)
        sock.set_recv_data(client.data_to_send())

        requests = server.receive_data()

        assert len(requests) == 1
        received_body = requests[0].body.read()
        assert len(received_body) == len(body)
        assert received_body == body

    def test_moderate_response_body(self):
        """Test sending moderate-sized response body."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        server = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        server.initiate_connection()

        client = create_h2_client()
        sock.set_recv_data(client.data_to_send())
        server.receive_data()
        client.receive_data(sock.get_sent_data())

        client.send_headers(1, [
            (':method', 'GET'),
            (':path', '/moderate'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
        ], end_stream=True)
        sock.set_recv_data(client.data_to_send())
        server.receive_data()

        # Send moderate response (within max frame size)
        moderate_body = b'Y' * 8000
        sock.clear_sent()
        server.send_response(1, 200, [('content-length', str(len(moderate_body)))], moderate_body)

        # Client receives response
        events = client.receive_data(sock.get_sent_data())
        data_events = [e for e in events if isinstance(e, h2.events.DataReceived)]
        received_data = b''.join(e.data for e in data_events)
        assert received_data == moderate_body


class TestSpecialCases:
    """Test special/edge cases."""

    def test_head_request(self):
        """Test HEAD request (no body in response)."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        server = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        server.initiate_connection()

        client = create_h2_client()
        sock.set_recv_data(client.data_to_send())
        server.receive_data()
        client.receive_data(sock.get_sent_data())

        client.send_headers(1, [
            (':method', 'HEAD'),
            (':path', '/resource'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
        ], end_stream=True)
        sock.set_recv_data(client.data_to_send())
        requests = server.receive_data()

        assert requests[0].method == 'HEAD'

        # Send response with content-length but no body
        sock.clear_sent()
        server.send_response(
            1, 200,
            [('content-length', '1000'), ('content-type', 'text/html')],
            body=None
        )

        events = client.receive_data(sock.get_sent_data())
        stream_ended = [e for e in events if isinstance(e, h2.events.StreamEnded)]
        assert len(stream_ended) == 1

    def test_options_request(self):
        """Test OPTIONS request."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        server = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        server.initiate_connection()

        client = create_h2_client()
        sock.set_recv_data(client.data_to_send())
        server.receive_data()
        client.receive_data(sock.get_sent_data())

        client.send_headers(1, [
            (':method', 'OPTIONS'),
            (':path', '*'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
        ], end_stream=True)
        sock.set_recv_data(client.data_to_send())
        requests = server.receive_data()

        assert requests[0].method == 'OPTIONS'
        assert requests[0].uri == '*'

    def test_request_with_query_string(self):
        """Test request with query string parameters."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        server = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        server.initiate_connection()

        client = create_h2_client()
        sock.set_recv_data(client.data_to_send())
        server.receive_data()
        client.receive_data(sock.get_sent_data())

        client.send_headers(1, [
            (':method', 'GET'),
            (':path', '/search?q=test&page=2&sort=desc'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
        ], end_stream=True)
        sock.set_recv_data(client.data_to_send())
        requests = server.receive_data()

        req = requests[0]
        assert req.path == '/search'
        assert req.query == 'q=test&page=2&sort=desc'

    def test_request_with_multiple_headers_same_name(self):
        """Test request with multiple headers of the same name."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        server = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        server.initiate_connection()

        client = create_h2_client()
        sock.set_recv_data(client.data_to_send())
        server.receive_data()
        client.receive_data(sock.get_sent_data())

        client.send_headers(1, [
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
            ('accept', 'text/html'),
            ('accept', 'application/json'),
            ('accept', '*/*'),
        ], end_stream=True)
        sock.set_recv_data(client.data_to_send())
        requests = server.receive_data()

        req = requests[0]
        accept_headers = [h[1] for h in req.headers if h[0] == 'ACCEPT']
        assert len(accept_headers) == 3
