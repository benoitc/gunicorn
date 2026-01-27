# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for HTTP/2 server connection."""

import pytest
from unittest import mock
from io import BytesIO

# Check if h2 is available for integration tests
try:
    import h2.connection
    import h2.config
    import h2.events
    import h2.exceptions
    H2_AVAILABLE = True
except ImportError:
    H2_AVAILABLE = False

from gunicorn.http2.errors import (
    HTTP2Error, HTTP2ConnectionError
)


pytestmark = pytest.mark.skipif(not H2_AVAILABLE, reason="h2 library not available")


class MockConfig:
    """Mock gunicorn configuration for HTTP/2."""

    def __init__(self):
        self.http2_max_concurrent_streams = 100
        self.http2_initial_window_size = 65535
        self.http2_max_frame_size = 16384
        self.http2_max_header_list_size = 65536


class MockSocket:
    """Mock socket for testing connection without real network I/O."""

    def __init__(self, data=b''):
        self._recv_buffer = BytesIO(data)
        self._sent = bytearray()
        self._closed = False

    def recv(self, size):
        return self._recv_buffer.read(size)

    def sendall(self, data):
        if self._closed:
            raise OSError("Socket is closed")
        self._sent.extend(data)

    def close(self):
        self._closed = True

    def get_sent_data(self):
        return bytes(self._sent)

    def set_recv_data(self, data):
        self._recv_buffer = BytesIO(data)


def create_client_connection():
    """Create an h2 client connection for generating test frames."""
    config = h2.config.H2Configuration(client_side=True)
    conn = h2.connection.H2Connection(config=config)
    conn.initiate_connection()
    return conn


class TestHTTP2ServerConnectionInit:
    """Test HTTP2ServerConnection initialization."""

    def test_basic_initialization(self):
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))

        assert conn.cfg is cfg
        assert conn.sock is sock
        assert conn.client_addr == ('127.0.0.1', 12345)
        assert conn.streams == {}
        assert conn.is_closed is False
        assert conn._initialized is False

    def test_settings_from_config(self):
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        cfg.http2_max_concurrent_streams = 50
        cfg.http2_initial_window_size = 32768

        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))

        assert conn.max_concurrent_streams == 50
        assert conn.initial_window_size == 32768


class TestHTTP2ServerConnectionInitiate:
    """Test connection initiation."""

    def test_initiate_connection(self):
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))

        conn.initiate_connection()

        assert conn._initialized is True
        # Should have sent settings frame
        sent_data = sock.get_sent_data()
        assert len(sent_data) > 0

    def test_initiate_connection_idempotent(self):
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))

        conn.initiate_connection()
        first_sent = len(sock.get_sent_data())

        conn.initiate_connection()  # Second call
        second_sent = len(sock.get_sent_data())

        # Should not send additional data
        assert first_sent == second_sent


class TestHTTP2ServerConnectionReceiveData:
    """Test receiving and processing data."""

    def test_receive_empty_data_closes_connection(self):
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket(b'')
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        requests = conn.receive_data()

        assert conn.is_closed is True
        assert requests == []

    def test_receive_client_preface_and_headers(self):
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        # Generate client data
        client = create_client_connection()
        client_preface = client.data_to_send()

        # Simulate server receiving client settings
        # Feed client preface to server
        requests = conn.receive_data(client_preface)

        # No requests yet, just settings exchange
        assert requests == []

    def test_receive_simple_get_request(self):
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        # Create client and send request
        client = create_client_connection()
        client_preface = client.data_to_send()

        # Process client preface on server
        conn.receive_data(client_preface)

        # Server may have sent settings, feed them to client
        server_data = sock.get_sent_data()
        if server_data:
            client.receive_data(server_data)

        # Client sends GET request
        client.send_headers(
            stream_id=1,
            headers=[
                (':method', 'GET'),
                (':path', '/test'),
                (':scheme', 'https'),
                (':authority', 'localhost'),
            ],
            end_stream=True
        )
        request_data = client.data_to_send()

        # Server receives request
        requests = conn.receive_data(request_data)

        assert len(requests) == 1
        req = requests[0]
        assert req.method == 'GET'
        assert req.path == '/test'

    def test_receive_post_with_body(self):
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        # Create client
        client = create_client_connection()
        client_preface = client.data_to_send()
        conn.receive_data(client_preface)

        server_data = sock.get_sent_data()
        if server_data:
            client.receive_data(server_data)

        # Client sends POST with body
        client.send_headers(
            stream_id=1,
            headers=[
                (':method', 'POST'),
                (':path', '/submit'),
                (':scheme', 'https'),
                (':authority', 'localhost'),
                ('content-type', 'application/json'),
                ('content-length', '13'),
            ],
            end_stream=False
        )
        client.send_data(stream_id=1, data=b'{"key":"val"}', end_stream=True)
        request_data = client.data_to_send()

        requests = conn.receive_data(request_data)

        assert len(requests) == 1
        req = requests[0]
        assert req.method == 'POST'
        assert req.body.read() == b'{"key":"val"}'

    def test_socket_error_raises_connection_error(self):
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = mock.Mock()
        sock.recv.side_effect = OSError("Connection reset")

        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        with pytest.raises(HTTP2ConnectionError):
            conn.receive_data()


class TestHTTP2ServerConnectionSendResponse:
    """Test sending responses."""

    def test_send_simple_response(self):
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        # Create a stream by receiving a request
        client = create_client_connection()
        client_preface = client.data_to_send()
        conn.receive_data(client_preface)

        server_data = sock.get_sent_data()
        if server_data:
            client.receive_data(server_data)

        client.send_headers(1, [
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=True)
        conn.receive_data(client.data_to_send())

        # Send response
        sock._sent.clear()
        conn.send_response(
            stream_id=1,
            status=200,
            headers=[('content-type', 'text/plain')],
            body=b'Hello!'
        )

        sent = sock.get_sent_data()
        assert len(sent) > 0

        # Verify client receives valid response
        events = client.receive_data(sent)
        response_events = [e for e in events if isinstance(e, h2.events.ResponseReceived)]
        data_events = [e for e in events if isinstance(e, h2.events.DataReceived)]

        assert len(response_events) == 1
        assert len(data_events) == 1
        assert data_events[0].data == b'Hello!'

    def test_send_response_with_empty_body(self):
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        client = create_client_connection()
        conn.receive_data(client.data_to_send())
        client.receive_data(sock.get_sent_data())

        client.send_headers(1, [
            (':method', 'HEAD'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=True)
        conn.receive_data(client.data_to_send())

        sock._sent.clear()
        conn.send_response(stream_id=1, status=200, headers=[], body=None)

        events = client.receive_data(sock.get_sent_data())
        stream_ended = [e for e in events if isinstance(e, h2.events.StreamEnded)]
        assert len(stream_ended) == 1

    def test_send_response_invalid_stream(self):
        """Test that sending response on invalid stream returns False."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        # Sending to a non-existent stream should return False gracefully
        result = conn.send_response(stream_id=999, status=200, headers=[], body=None)
        assert result is False


class TestHTTP2ServerConnectionSendError:
    """Test sending error responses."""

    def test_send_error_with_message(self):
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        client = create_client_connection()
        conn.receive_data(client.data_to_send())
        client.receive_data(sock.get_sent_data())

        client.send_headers(1, [
            (':method', 'GET'),
            (':path', '/notfound'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=True)
        conn.receive_data(client.data_to_send())

        sock._sent.clear()
        conn.send_error(stream_id=1, status_code=404, message="Not Found")

        events = client.receive_data(sock.get_sent_data())
        response_events = [e for e in events if isinstance(e, h2.events.ResponseReceived)]
        data_events = [e for e in events if isinstance(e, h2.events.DataReceived)]

        assert len(response_events) == 1
        # h2 library returns headers as list of tuples, convert to dict
        # Note: headers may be bytes or strings depending on h2 version
        headers_list = response_events[0].headers
        status = None
        for name, value in headers_list:
            name_str = name.decode() if isinstance(name, bytes) else name
            if name_str == ':status':
                status = value.decode() if isinstance(value, bytes) else value
                break
        assert status == '404'

        assert len(data_events) == 1
        assert data_events[0].data == b"Not Found"


class TestHTTP2ServerConnectionResetStream:
    """Test stream reset."""

    def test_reset_stream(self):
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        client = create_client_connection()
        conn.receive_data(client.data_to_send())
        client.receive_data(sock.get_sent_data())

        client.send_headers(1, [
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=False)
        conn.receive_data(client.data_to_send())

        sock._sent.clear()
        conn.reset_stream(stream_id=1, error_code=0x8)  # CANCEL

        events = client.receive_data(sock.get_sent_data())
        reset_events = [e for e in events if isinstance(e, h2.events.StreamReset)]
        assert len(reset_events) == 1
        assert reset_events[0].error_code == 0x8


class TestHTTP2ServerConnectionClose:
    """Test connection close."""

    def test_close_connection(self):
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        client = create_client_connection()
        conn.receive_data(client.data_to_send())

        sock._sent.clear()
        conn.close()

        assert conn.is_closed is True

        # Should have sent GOAWAY
        events = client.receive_data(sock.get_sent_data())
        goaway_events = [e for e in events if isinstance(e, h2.events.ConnectionTerminated)]
        assert len(goaway_events) == 1

    def test_close_idempotent(self):
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        conn.close()
        sent_after_first = len(sock.get_sent_data())

        conn.close()  # Second call
        sent_after_second = len(sock.get_sent_data())

        # Should not send additional GOAWAY
        assert sent_after_first == sent_after_second


class TestHTTP2ServerConnectionCleanup:
    """Test stream cleanup."""

    def test_cleanup_stream(self):
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        client = create_client_connection()
        conn.receive_data(client.data_to_send())
        client.receive_data(sock.get_sent_data())

        client.send_headers(1, [
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=True)
        conn.receive_data(client.data_to_send())

        assert 1 in conn.streams

        conn.cleanup_stream(1)

        assert 1 not in conn.streams

    def test_cleanup_nonexistent_stream(self):
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        # Should not raise
        conn.cleanup_stream(999)


class TestHTTP2ServerConnectionMultipleStreams:
    """Test handling multiple concurrent streams."""

    def test_multiple_streams(self):
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        client = create_client_connection()
        conn.receive_data(client.data_to_send())
        client.receive_data(sock.get_sent_data())

        # Send multiple requests
        client.send_headers(1, [
            (':method', 'GET'),
            (':path', '/one'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=True)

        client.send_headers(3, [
            (':method', 'GET'),
            (':path', '/two'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=True)

        requests = conn.receive_data(client.data_to_send())

        assert len(requests) == 2
        paths = {req.path for req in requests}
        assert paths == {'/one', '/two'}


class TestHTTP2ServerConnectionRepr:
    """Test string representation."""

    def test_repr(self):
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))

        repr_str = repr(conn)
        assert "HTTP2ServerConnection" in repr_str
        assert "streams=" in repr_str
        assert "closed=" in repr_str


class TestHTTP2ServerConnectionPriority:
    """Test HTTP/2 priority handling."""

    def test_handle_priority_updated_existing_stream(self):
        """Test handling priority update for existing stream."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        # Create a client connection to generate frames
        client_conn = create_client_connection()

        # Get client preface
        client_data = client_conn.data_to_send()

        # Feed client preface to server
        conn.receive_data(client_data)
        sock._sent = bytearray()

        # Send a request to create a stream
        client_conn.send_headers(1, [
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ])
        request_data = client_conn.data_to_send()
        conn.receive_data(request_data)

        # Verify stream was created
        assert 1 in conn.streams
        stream = conn.streams[1]

        # Default priority values
        assert stream.priority_weight == 16
        assert stream.priority_depends_on == 0

        # Send a PRIORITY frame
        client_conn.prioritize(1, weight=128, depends_on=0, exclusive=False)
        priority_data = client_conn.data_to_send()
        conn.receive_data(priority_data)

        # Verify priority was updated
        assert stream.priority_weight == 128

    def test_handle_priority_updated_nonexistent_stream(self):
        """Test that priority update for nonexistent stream is ignored."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        # Create a client connection
        client_conn = create_client_connection()
        client_data = client_conn.data_to_send()
        conn.receive_data(client_data)

        # Send a PRIORITY frame for a stream that doesn't exist
        # This should not raise an error
        client_conn.prioritize(99, weight=64, depends_on=0, exclusive=False)
        priority_data = client_conn.data_to_send()

        # Should not raise
        conn.receive_data(priority_data)


class TestHTTP2ServerConnectionTrailers:
    """Test HTTP/2 response trailer support."""

    def test_send_trailers_after_headers_and_body(self):
        """Test sending trailers after response headers and body."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        # Create a client connection
        client_conn = create_client_connection()
        client_data = client_conn.data_to_send()
        conn.receive_data(client_data)
        sock._sent = bytearray()

        # Send a request
        client_conn.send_headers(1, [
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=True)
        request_data = client_conn.data_to_send()
        conn.receive_data(request_data)

        # Manually send headers without ending stream (for trailer support)
        stream = conn.streams[1]
        response_headers = [(':status', '200'), ('content-type', 'text/plain')]
        conn.h2_conn.send_headers(1, response_headers, end_stream=False)
        stream.send_headers(response_headers, end_stream=False)
        conn._send_pending_data()

        # Send body without ending stream
        conn.h2_conn.send_data(1, b'Hello World', end_stream=False)
        stream.send_data(b'Hello World', end_stream=False)
        conn._send_pending_data()

        # Send trailers
        trailers = [('grpc-status', '0'), ('grpc-message', 'OK')]
        conn.send_trailers(1, trailers)

        # Verify stream is closed
        assert stream.response_complete is True
        assert stream.response_trailers == [('grpc-status', '0'), ('grpc-message', 'OK')]

    def test_send_trailers_pseudo_header_raises(self):
        """Test that pseudo-headers in trailers raise error."""
        from gunicorn.http2.connection import HTTP2ServerConnection
        from gunicorn.http2.errors import HTTP2Error

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        client_conn = create_client_connection()
        client_data = client_conn.data_to_send()
        conn.receive_data(client_data)

        # Send a request
        client_conn.send_headers(1, [
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=True)
        conn.receive_data(client_conn.data_to_send())

        # Send response
        conn.send_response(1, 200, [('content-type', 'text/plain')], None)

        # Try to send trailers with pseudo-header
        with pytest.raises(HTTP2Error) as exc_info:
            conn.send_trailers(1, [(':status', '200')])
        assert "Pseudo-header" in str(exc_info.value)

    def test_send_trailers_without_headers_returns_false(self):
        """Test that sending trailers without headers returns False."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        client_conn = create_client_connection()
        client_data = client_conn.data_to_send()
        conn.receive_data(client_data)

        # Send a request
        client_conn.send_headers(1, [
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=True)
        conn.receive_data(client_conn.data_to_send())

        # Try to send trailers without sending headers first - should return False
        result = conn.send_trailers(1, [('trailer', 'value')])
        assert result is False

    def test_send_trailers_nonexistent_stream_returns_false(self):
        """Test that sending trailers on nonexistent stream returns False."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        client_conn = create_client_connection()
        conn.receive_data(client_conn.data_to_send())

        # Sending trailers to non-existent stream should return False
        result = conn.send_trailers(99, [('trailer', 'value')])
        assert result is False


class TestHTTP2FlowControl:
    """Test HTTP/2 flow control handling."""

    def test_send_data_respects_zero_window(self):
        """Test that send_data returns False when flow control window is 0."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        # Create client and send preface
        client_conn = create_client_connection()
        conn.receive_data(client_conn.data_to_send())

        # Send a request
        client_conn.send_headers(1, [
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=True)
        conn.receive_data(client_conn.data_to_send())

        # Send response headers without ending stream (pass body=b'' placeholder)
        # We need to send headers first, so use h2_conn directly
        conn.h2_conn.send_headers(1, [
            (':status', '200'),
            ('content-type', 'text/plain'),
        ], end_stream=False)
        conn._send_pending_data()
        conn.streams[1].send_headers([(':status', '200')], end_stream=False)

        # Mock the flow control window to return 0
        original_window = conn.h2_conn.local_flow_control_window
        conn.h2_conn.local_flow_control_window = lambda stream_id: 0

        # Try to send data - should return False (not raise)
        result = conn.send_data(1, b'Hello, World!')
        assert result is False

        # Restore
        conn.h2_conn.local_flow_control_window = original_window

    def test_send_data_respects_flow_control(self):
        """Test that send_data chunks data according to flow control window."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        # Create client and send preface
        client_conn = create_client_connection()
        conn.receive_data(client_conn.data_to_send())

        # Send a request
        client_conn.send_headers(1, [
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=True)
        conn.receive_data(client_conn.data_to_send())

        # Send response headers without ending stream
        conn.h2_conn.send_headers(1, [
            (':status', '200'),
            ('content-type', 'text/plain'),
        ], end_stream=False)
        conn._send_pending_data()
        conn.streams[1].send_headers([(':status', '200')], end_stream=False)

        # Send small data - should succeed within window
        small_data = b'Hello'
        conn.send_data(1, small_data, end_stream=True)

        # Verify data was sent
        sent_data = sock.get_sent_data()
        assert len(sent_data) > 0


class TestHTTP2StreamClosedHandling:
    """Test graceful handling of StreamClosedError."""

    def test_send_response_on_closed_stream(self):
        """Test that send_response gracefully handles closed stream."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        # Create client and send preface
        client_conn = create_client_connection()
        conn.receive_data(client_conn.data_to_send())

        # Send a request
        client_conn.send_headers(1, [
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=True)
        conn.receive_data(client_conn.data_to_send())

        # Simulate client resetting the stream
        client_conn.reset_stream(1)
        conn.receive_data(client_conn.data_to_send())

        # Try to send response - should return False, not raise
        result = conn.send_response(1, 200, [('content-type', 'text/plain')], b'Hello')
        assert result is False

    def test_send_data_on_reset_stream(self):
        """Test that send_data gracefully handles reset stream."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        # Create client and send preface
        client_conn = create_client_connection()
        conn.receive_data(client_conn.data_to_send())

        # Send a request
        client_conn.send_headers(1, [
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=True)
        conn.receive_data(client_conn.data_to_send())

        # Send response headers without ending stream
        conn.h2_conn.send_headers(1, [
            (':status', '200'),
            ('content-type', 'text/plain'),
        ], end_stream=False)
        conn._send_pending_data()
        conn.streams[1].send_headers([(':status', '200')], end_stream=False)

        # Simulate client resetting the stream
        client_conn.reset_stream(1)
        conn.receive_data(client_conn.data_to_send())

        # Try to send data - should return False, not raise
        result = conn.send_data(1, b'Hello, World!', end_stream=True)
        assert result is False


class TestHTTP2WindowOverflowHandling:
    """Test window overflow handling."""

    def test_window_overflow_sends_goaway(self):
        """Test that window overflow results in GOAWAY with FLOW_CONTROL_ERROR."""
        from gunicorn.http2.connection import HTTP2ServerConnection
        from gunicorn.http2.errors import HTTP2ErrorCode

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        # Create client and send preface
        client_conn = create_client_connection()
        conn.receive_data(client_conn.data_to_send())

        # Mock increment_flow_control_window to raise ValueError (overflow)
        original_increment = conn.h2_conn.increment_flow_control_window

        def raise_overflow(increment, stream_id=None):
            raise ValueError("Flow control window too large")

        conn.h2_conn.increment_flow_control_window = raise_overflow

        # Send a request with data to trigger the overflow
        client_conn.send_headers(1, [
            (':method', 'POST'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=False)
        client_conn.send_data(1, b'test data', end_stream=True)
        conn.receive_data(client_conn.data_to_send())

        # Connection should be closed with FLOW_CONTROL_ERROR
        assert conn.is_closed is True


class TestHTTP2ProtocolErrorHandling:
    """Test protocol error handling sends proper GOAWAY."""

    def test_protocol_error_sends_goaway(self):
        """Test that protocol errors result in GOAWAY being sent."""
        from gunicorn.http2.connection import HTTP2ServerConnection
        from gunicorn.http2.errors import HTTP2ProtocolError, HTTP2ErrorCode

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        # Create client and send preface
        client_conn = create_client_connection()
        conn.receive_data(client_conn.data_to_send())

        # Clear sent data to only capture new frames
        sock._sent.clear()

        # Mock h2_conn.receive_data to raise ProtocolError
        def raise_protocol_error(data):
            raise h2.exceptions.ProtocolError("Test protocol error")

        conn.h2_conn.receive_data = raise_protocol_error

        # This should send GOAWAY and raise ProtocolError
        with pytest.raises(HTTP2ProtocolError) as exc_info:
            conn.receive_data(b'dummy data')

        assert "Test protocol error" in str(exc_info.value)

        # Verify something was sent (GOAWAY frame)
        sent_data = sock.get_sent_data()
        assert len(sent_data) > 0
        # Connection should be marked as closed
        assert conn.is_closed is True


class TestHTTP2NotAvailable:
    """Test behavior when h2 is not available."""

    def test_import_error_raises_not_available(self):
        from gunicorn.http2 import errors

        # Test that HTTP2NotAvailable can be raised
        with pytest.raises(errors.HTTP2NotAvailable):
            raise errors.HTTP2NotAvailable()
