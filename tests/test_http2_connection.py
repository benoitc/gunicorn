# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for HTTP/2 server connection."""

import pytest

from gunicorn.config import Config
from unittest import mock
from io import BytesIO

# Check if h2 is available for integration tests
try:
    import h2.connection
    import h2.config
    import h2.events
    import h2.exceptions
    import h2.errors
    H2_AVAILABLE = True
except ImportError:
    H2_AVAILABLE = False

from gunicorn.http2.stream import StreamState
from gunicorn.http2.errors import (
    HTTP2Error, HTTP2ConnectionError, HTTP2ProtocolError
)


pytestmark = pytest.mark.skipif(not H2_AVAILABLE, reason="h2 library not available")


def MockConfig():
    """Real gunicorn configuration with the HTTP/2 defaults these tests want.

    HTTP2Request applies the same header policy as HTTP/1, which reads
    forwarded_allow_ips, header_map and friends, so a stub with only the
    http2_* attributes would not exercise the real defaults.
    """
    cfg = Config()
    cfg.set("http2_max_concurrent_streams", 100)
    cfg.set("http2_initial_window_size", 65535)
    cfg.set("http2_max_frame_size", 16384)
    cfg.set("http2_max_header_list_size", 65536)
    return cfg


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
        cfg.set("http2_max_concurrent_streams", 50)
        cfg.set("http2_initial_window_size", 32768)

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
    """A peer sending past the receive window gets GOAWAY(FLOW_CONTROL_ERROR)."""

    def test_window_overflow_sends_goaway(self):
        from hyperframe.frame import DataFrame
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        client_conn = create_client_connection()
        conn.receive_data(client_conn.data_to_send())
        client_conn.receive_data(sock.get_sent_data())
        client_conn.send_headers(1, [
            (':method', 'POST'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=False)
        conn.receive_data(client_conn.data_to_send())

        # Nothing is credited back until the application reads, so five
        # full frames overrun the 65535 byte window. Serialized by hand
        # because a well-behaved client would refuse to send them.
        frames = b""
        for _ in range(5):
            f = DataFrame(1, data=b"x" * 16384)
            frames += f.serialize()
        before = len(sock.get_sent_data())
        with pytest.raises(HTTP2ProtocolError):
            conn.receive_data(frames)

        assert conn.is_closed is True
        events = client_conn.receive_data(sock.get_sent_data()[before:])
        goaway = [e for e in events if isinstance(e, h2.events.ConnectionTerminated)]
        # h2 sends one GOAWAY itself before raising; close() sends another.
        assert goaway
        assert {g.error_code for g in goaway} == {h2.errors.ErrorCodes.FLOW_CONTROL_ERROR}


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


class TestHTTP2StreamEndedBodyComplete:
    """Test that _handle_stream_ended sets _body_complete on the stream."""

    def test_stream_ended_sets_body_complete(self):
        """_handle_stream_ended must set stream._body_complete = True."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        client = create_client_connection()
        client_preface = client.data_to_send()
        conn.receive_data(client_preface)

        server_data = sock.get_sent_data()
        if server_data:
            client.receive_data(server_data)

        # Client sends POST with body (separate HEADERS and DATA frames)
        client.send_headers(
            stream_id=1,
            headers=[
                (':method', 'POST'),
                (':path', '/test'),
                (':scheme', 'https'),
                (':authority', 'localhost'),
                ('content-type', 'application/json'),
            ],
            end_stream=False,
        )
        client.send_data(stream_id=1, data=b'{"input": "test"}', end_stream=True)
        request_data = client.data_to_send()

        requests = conn.receive_data(request_data)

        assert len(requests) == 1
        stream = conn.streams.get(1)
        assert stream is not None
        assert stream._body_complete is True
        assert stream.request_complete is True

    def test_stream_ended_signals_body_event(self):
        """_handle_stream_ended must signal _body_event if it exists."""
        import asyncio
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        client = create_client_connection()
        client_preface = client.data_to_send()
        conn.receive_data(client_preface)

        server_data = sock.get_sent_data()
        if server_data:
            client.receive_data(server_data)

        # Client sends headers without end_stream to create the stream
        client.send_headers(
            stream_id=1,
            headers=[
                (':method', 'POST'),
                (':path', '/test'),
                (':scheme', 'https'),
                (':authority', 'localhost'),
            ],
            end_stream=False,
        )
        headers_data = client.data_to_send()
        conn.receive_data(headers_data)

        # Manually set _body_event on the stream (simulates read_body_chunk
        # having been called, which lazy-inits the event)
        stream = conn.streams.get(1)
        assert stream is not None
        stream._body_event = asyncio.Event()

        # Now send data + end_stream
        client.send_data(stream_id=1, data=b'body', end_stream=True)
        request_data = client.data_to_send()
        conn.receive_data(request_data)

        assert stream._body_event.is_set()

    def test_stream_ended_without_body_event_does_not_raise(self):
        """_handle_stream_ended must not raise when _body_event is None."""
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        client = create_client_connection()
        client_preface = client.data_to_send()
        conn.receive_data(client_preface)

        server_data = sock.get_sent_data()
        if server_data:
            client.receive_data(server_data)

        # Send GET with end_stream (no body, _body_event never initialised)
        client.send_headers(
            stream_id=1,
            headers=[
                (':method', 'GET'),
                (':path', '/test'),
                (':scheme', 'https'),
                (':authority', 'localhost'),
            ],
            end_stream=True,
        )
        request_data = client.data_to_send()

        # Should not raise even though _body_event is None
        requests = conn.receive_data(request_data)
        assert len(requests) == 1

    @pytest.mark.asyncio
    async def test_h2_post_body_not_duplicated(self):
        """Full flow: streaming read must not re-read body from BytesIO.

        Simulates what the receive() closure in protocol.py does:
        1. read_body_chunk() returns the body
        2. read_body_chunk() returns None (body complete)
        3. Total bytes received == original body length (not doubled)
        """
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()

        client = create_client_connection()
        client_preface = client.data_to_send()
        conn.receive_data(client_preface)

        server_data = sock.get_sent_data()
        if server_data:
            client.receive_data(server_data)

        body = b'{"input": ["hello world"]}'
        client.send_headers(
            stream_id=1,
            headers=[
                (':method', 'POST'),
                (':path', '/embeddings'),
                (':scheme', 'https'),
                (':authority', 'localhost'),
                ('content-type', 'application/json'),
                ('content-length', str(len(body))),
            ],
            end_stream=False,
        )
        client.send_data(stream_id=1, data=body, end_stream=True)
        request_data = client.data_to_send()

        requests = conn.receive_data(request_data)
        assert len(requests) == 1

        stream = conn.streams.get(1)

        # Simulate what receive() does: read chunks via read_body_chunk()
        received = bytearray()
        while True:
            chunk = await stream.read_body_chunk()
            if chunk is None:
                break
            received.extend(chunk)

        # The critical assertion: body must not be duplicated
        assert bytes(received) == body
        assert len(received) == len(body)

        # _body_complete must be True so receive() knows to stop
        assert stream._body_complete is True

        # BytesIO must still have the data (for get_request_body compatibility)
        # but read_body_chunk returning None prevents the fast path in receive()
        # from ever being reached because body_received gets set to True


class TestHTTP2NotAvailable:
    """Test behavior when h2 is not available."""

    def test_import_error_raises_not_available(self):
        from gunicorn.http2 import errors

        # Test that HTTP2NotAvailable can be raised
        with pytest.raises(errors.HTTP2NotAvailable):
            raise errors.HTTP2NotAvailable()


class TestDeferredFlowControlEvents:
    """Events arriving during a flow-control wait must not be lost."""

    def _conn(self):
        from gunicorn.http2.connection import HTTP2ServerConnection
        return HTTP2ServerConnection(MockConfig(), MockSocket(),
                                     ('127.0.0.1', 12345))

    def test_deferred_events_are_drained_by_receive_data(self):
        conn = self._conn()
        marker = mock.Mock(name="RequestReceived")
        conn._deferred_events.append(marker)

        seen = []
        conn._handle_event = lambda e: seen.append(e) or None
        conn.h2_conn = mock.Mock()
        conn.h2_conn.receive_data.return_value = ["later"]
        conn._send_pending_data = lambda: None

        conn.receive_data(b"some bytes")

        # the deferred event is processed, and before the new one
        assert seen == [marker, "later"]
        assert not conn._deferred_events

    def test_queue_starts_empty(self):
        assert not self._conn()._deferred_events

class TestEndStream:
    """Ending a stream must actually put END_STREAM on the wire."""

    def _conn(self):
        from gunicorn.http2.connection import HTTP2ServerConnection
        conn = HTTP2ServerConnection(MockConfig(), MockSocket(),
                                     ('127.0.0.1', 12345))
        conn.h2_conn = mock.Mock()
        conn.streams[1] = mock.Mock()
        conn._send_pending_data = lambda: None
        return conn

    def test_end_stream_sets_the_flag(self):
        # Regression: routing this through send_data() sent nothing, because
        # send_data loops on the payload and an empty one skips the loop. The
        # client then waited forever for a response that had already finished.
        conn = self._conn()
        conn.end_stream(1)
        conn.h2_conn.send_data.assert_called_once()
        assert conn.h2_conn.send_data.call_args.kwargs["end_stream"] is True

    def test_end_stream_with_trailers_sends_trailers(self):
        conn = self._conn()
        conn.send_trailers = mock.Mock()
        conn.end_stream(1, trailers=[("x-sum", "1")])
        conn.send_trailers.assert_called_once_with(1, [("x-sum", "1")])
        conn.h2_conn.send_data.assert_not_called()

    def test_end_stream_on_unknown_stream(self):
        conn = self._conn()
        assert conn.end_stream(999) is False


class TestStreamingRequestBody:
    """The request goes out on its headers; the body follows as it arrives."""

    def _open_post(self):
        from gunicorn.http2.connection import HTTP2ServerConnection

        sock = MockSocket()
        conn = HTTP2ServerConnection(MockConfig(), sock, ('127.0.0.1', 12345))
        conn.initiate_connection()
        client = create_client_connection()
        conn.receive_data(client.data_to_send())
        client.receive_data(sock.get_sent_data())
        client.send_headers(
            stream_id=1,
            headers=[
                (':method', 'POST'),
                (':path', '/upload'),
                (':scheme', 'https'),
                (':authority', 'localhost'),
            ],
            end_stream=False,
        )
        requests = conn.receive_data(client.data_to_send())
        return conn, client, sock, requests

    def _drain(self, client, sock, since):
        """Feed the client what the server wrote since ``since``."""
        data = sock.get_sent_data()
        client.receive_data(data[since:])
        return len(data)

    def test_request_is_dispatched_before_the_body_arrives(self):
        conn, client, sock, requests = self._open_post()
        assert len(requests) == 1
        req = requests[0]
        assert req.method == 'POST'
        assert req.stream.body_complete is False

    def test_body_is_pulled_off_the_socket_as_the_app_reads(self):
        conn, client, sock, requests = self._open_post()
        req = requests[0]

        client.send_data(1, b"a" * 600, end_stream=False)
        client.send_data(1, b"b" * 600, end_stream=True)
        sock.set_recv_data(client.data_to_send())

        # Nothing has been read from the socket yet.
        assert req.stream.body_size == 0
        assert req.body.read(700) == b"a" * 600 + b"b" * 100
        assert req.body.read() == b"b" * 500
        assert req.body.read() == b""
        assert req.stream.body_complete is True

    def test_stream_credit_returns_only_for_what_the_app_read(self):
        conn, client, sock, requests = self._open_post()
        req = requests[0]

        # Fill most of the stream window without ending the stream.
        for _ in range(3):
            client.send_data(1, b"x" * 16384, end_stream=False)
        before = len(sock.get_sent_data())
        conn.receive_data(client.data_to_send())

        assert req.stream.body_size == 3 * 16384
        assert req.stream.unacked_size == 3 * 16384
        # Connection-level credit comes straight back...
        before = self._drain(client, sock, before)
        assert client.outbound_flow_control_window == 65535
        # ...the stream window only once the application reads.
        assert client.local_flow_control_window(1) == 65535 - 3 * 16384

        req.body.read(2 * 16384)
        assert req.stream.unacked_size == 16384
        self._drain(client, sock, before)
        assert client.local_flow_control_window(1) == 65535 - 16384

    def test_queued_stream_cannot_starve_the_one_being_served(self):
        conn, client, sock, requests = self._open_post()
        req = requests[0]
        client.send_headers(
            stream_id=3,
            headers=[
                (':method', 'POST'),
                (':path', '/other'),
                (':scheme', 'https'),
                (':authority', 'localhost'),
            ],
            end_stream=False,
        )
        # Stream 3 uses up a whole connection window while stream 1 is
        # the one being served.
        for _ in range(4):
            client.send_data(3, b"y" * 16383, end_stream=False)
        before = len(sock.get_sent_data())
        later = conn.receive_data(client.data_to_send())
        assert [r.stream.stream_id for r in later] == [3]
        before = self._drain(client, sock, before)

        assert client.outbound_flow_control_window == 65535
        assert client.local_flow_control_window(1) == 65535
        client.send_data(1, b"rest", end_stream=True)
        sock.set_recv_data(client.data_to_send())
        assert req.body.read() == b"rest"

    def test_peer_past_the_window_gets_flow_control_error(self):
        from hyperframe.frame import DataFrame
        conn, client, sock, requests = self._open_post()
        frames = b"".join(DataFrame(1, data=b"x" * 16384).serialize() for _ in range(5))
        with pytest.raises(HTTP2ProtocolError):
            conn.receive_data(frames)
        assert conn.is_closed is True

    def test_unread_body_is_reset_with_no_error_on_cleanup(self):
        conn, client, sock, requests = self._open_post()
        for _ in range(3):
            client.send_data(1, b"a" * 16384, end_stream=False)
        before = len(sock.get_sent_data())
        conn.receive_data(client.data_to_send())
        before = self._drain(client, sock, before)

        assert conn.send_response(1, 200, [], b"done") is True
        conn.cleanup_stream(1)

        assert 1 not in conn.streams
        events = client.receive_data(sock.get_sent_data()[before:])
        resets = [e for e in events if isinstance(e, h2.events.StreamReset)]
        assert len(resets) == 1
        assert resets[0].error_code == h2.errors.ErrorCodes.NO_ERROR
        # The unread bytes never cost connection-level credit.
        assert client.outbound_flow_control_window == 65535
        assert conn.is_closed is False

    def test_complete_body_cleanup_sends_no_reset(self):
        conn, client, sock, requests = self._open_post()
        client.send_data(1, b"a" * 10, end_stream=True)
        conn.receive_data(client.data_to_send())
        assert requests[0].body.read() == b"a" * 10
        assert conn.send_response(1, 200, [], b"done") is True
        before = len(sock.get_sent_data())
        conn.cleanup_stream(1)
        events = client.receive_data(sock.get_sent_data()[before:])
        assert not [e for e in events if isinstance(e, h2.events.StreamReset)]

    def test_unfinished_response_is_reset_with_internal_error_on_cleanup(self):
        """The app returned without completing its response."""
        conn, client, sock, requests = self._open_post()
        client.send_data(1, b"a" * 10, end_stream=True)
        conn.receive_data(client.data_to_send())
        assert requests[0].body.read() == b"a" * 10
        before = len(sock.get_sent_data())
        conn.cleanup_stream(1)
        events = client.receive_data(sock.get_sent_data()[before:])
        resets = [e for e in events if isinstance(e, h2.events.StreamReset)]
        assert [r.error_code for r in resets] == [h2.errors.ErrorCodes.INTERNAL_ERROR]
        assert 1 not in conn.streams

    def test_requests_arriving_during_a_body_read_are_queued(self):
        conn, client, sock, requests = self._open_post()
        req = requests[0]

        client.send_headers(
            stream_id=3,
            headers=[
                (':method', 'GET'),
                (':path', '/other'),
                (':scheme', 'https'),
                (':authority', 'localhost'),
            ],
            end_stream=True,
        )
        client.send_data(1, b"body", end_stream=True)
        sock.set_recv_data(client.data_to_send())

        assert req.body.read() == b"body"
        queued = conn.receive_data()
        assert [r.stream.stream_id for r in queued] == [3]
        assert queued[0].path == '/other'
        assert conn.receive_data(b"") == []

    def test_peer_reset_during_a_body_read_raises_stream_error(self):
        from gunicorn.http2.errors import HTTP2StreamError
        conn, client, sock, requests = self._open_post()
        req = requests[0]
        client.send_data(1, b"a" * 10, end_stream=False)
        client.reset_stream(1, error_code=h2.errors.ErrorCodes.CANCEL)
        sock.set_recv_data(client.data_to_send())

        assert req.body.read(10) == b"a" * 10
        with pytest.raises(HTTP2StreamError):
            req.body.read()

    def test_trailers_are_visible_after_the_body(self):
        conn, client, sock, requests = self._open_post()
        req = requests[0]
        client.send_data(1, b"payload", end_stream=False)
        client.send_headers(1, [('x-checksum', 'abc')], end_stream=True)
        sock.set_recv_data(client.data_to_send())

        assert req.trailers == []
        assert req.body.read() == b"payload"
        assert req.trailers == [('X-CHECKSUM', 'abc')]

    def test_readline_across_frames(self):
        conn, client, sock, requests = self._open_post()
        req = requests[0]
        client.send_data(1, b"line one\nli", end_stream=False)
        client.send_data(1, b"ne two\nlast", end_stream=True)
        sock.set_recv_data(client.data_to_send())

        assert req.body.readline() == b"line one\n"
        assert req.body.readline(3) == b"lin"
        assert list(req.body) == [b"e two\n", b"last"]

    def test_padding_is_credited_back(self):
        from hyperframe.frame import DataFrame
        conn, client, sock, requests = self._open_post()
        req = requests[0]

        frames = b""
        for _ in range(255):
            f = DataFrame(1, data=b"x", pad_length=255)
            f.flags.add("PADDED")
            frames += f.serialize()
        conn.receive_data(frames)
        assert req.body.read(255) == b"x" * 255

        # Every flow-controlled byte, padding included, is back.
        assert conn.h2_conn.remote_flow_control_window(1) == 65535


def frame_types(data):
    """Frame type names in ``data``, parsed without an h2 state machine."""
    from hyperframe.frame import Frame
    kinds = []
    while data:
        frame, length = Frame.parse_frame_header(memoryview(data[:9]))
        frame.parse_body(memoryview(data[9:9 + length]))
        kinds.append(type(frame).__name__)
        data = data[9 + length:]
    return kinds


class TestGracefulGoAway:
    """GOAWAY(NO_ERROR) drains established streams; other codes close."""

    def _open(self):
        from gunicorn.http2.connection import HTTP2ServerConnection

        sock = MockSocket()
        conn = HTTP2ServerConnection(MockConfig(), sock, ('127.0.0.1', 12345))
        conn.initiate_connection()
        client = create_client_connection()
        conn.receive_data(client.data_to_send())
        client.receive_data(sock.get_sent_data())
        return conn, client, sock

    def _get(self, client, stream_id, path="/"):
        client.send_headers(
            stream_id=stream_id,
            headers=[
                (':method', 'GET'),
                (':path', path),
                (':scheme', 'https'),
                (':authority', 'localhost'),
            ],
            end_stream=True,
        )

    def test_established_stream_is_answered_then_connection_closes(self):
        conn, client, sock = self._open()
        self._get(client, 1)
        client.close_connection()
        requests = conn.receive_data(client.data_to_send())

        assert [r.stream.stream_id for r in requests] == [1]
        assert conn.draining is True
        assert conn.is_closed is False

        before = len(sock.get_sent_data())
        assert conn.send_response(1, 200, [], b"hello") is True
        conn.cleanup_stream(1)
        assert conn.is_closed is True

        # The h2 client is closed once it has sent GOAWAY, so the frames
        # are checked raw, as a real client would still read them.
        kinds = frame_types(sock.get_sent_data()[before:])
        assert "HeadersFrame" in kinds
        assert "DataFrame" in kinds
        assert kinds[-1] == "GoAwayFrame"

    def test_stream_opened_after_goaway_is_refused(self):
        conn, client, sock = self._open()
        self._get(client, 1)
        client.close_connection()
        conn.receive_data(client.data_to_send())

        # h2 forbids the client from opening streams after its GOAWAY;
        # a raw HEADERS frame stands in for a misbehaving peer.
        from hyperframe.frame import HeadersFrame
        encoder = client.encoder
        f = HeadersFrame(3, data=encoder.encode([
            (':method', 'GET'), (':path', '/late'),
            (':scheme', 'https'), (':authority', 'localhost')]))
        f.flags.add('END_HEADERS')
        f.flags.add('END_STREAM')
        before = len(sock.get_sent_data())
        assert conn.receive_data(f.serialize()) == []
        assert 3 not in conn.streams
        assert 1 in conn.streams
        assert "RstStreamFrame" in frame_types(sock.get_sent_data()[before:])

    def test_goaway_followed_by_data_in_one_read(self):
        """The rest of the client's write lands after its GOAWAY."""
        from hyperframe.frame import DataFrame, GoAwayFrame
        conn, client, sock = self._open()
        client.send_headers(
            stream_id=1,
            headers=[
                (':method', 'POST'),
                (':path', '/upload'),
                (':scheme', 'https'),
                (':authority', 'localhost'),
            ],
            end_stream=False,
        )
        requests = conn.receive_data(client.data_to_send())
        req = requests[0]

        goaway = GoAwayFrame(0, last_stream_id=1, error_code=0)
        data = DataFrame(1, data=b"body")
        data.flags.add("END_STREAM")
        conn.receive_data(goaway.serialize() + data.serialize())

        assert conn.draining is True
        assert conn.is_closed is False
        assert conn.h2_conn.peer_goaway_last_stream_id == 1
        assert req.body.read() == b"body"
        before = len(sock.get_sent_data())
        assert conn.send_response(1, 200, [], b"hello") is True
        conn.cleanup_stream(1)
        assert conn.is_closed is True
        kinds = frame_types(sock.get_sent_data()[before:])
        assert "HeadersFrame" in kinds
        assert kinds[-1] == "GoAwayFrame"

    def test_stream_at_or_below_last_stream_id_is_served(self):
        """A stream the peer said it would still process is served."""
        from hyperframe.frame import GoAwayFrame, HeadersFrame
        conn, client, sock = self._open()
        self._get(client, 1)
        conn.receive_data(client.data_to_send())
        conn.receive_data(GoAwayFrame(0, last_stream_id=3, error_code=0).serialize())
        assert conn.draining is True

        f = HeadersFrame(3, data=client.encoder.encode([
            (':method', 'GET'), (':path', '/late'),
            (':scheme', 'https'), (':authority', 'localhost')]))
        f.flags.add('END_HEADERS')
        f.flags.add('END_STREAM')
        requests = conn.receive_data(f.serialize())
        assert [r.stream.stream_id for r in requests] == [3]

    def test_goaway_with_error_closes_at_once(self):
        conn, client, sock = self._open()
        self._get(client, 1)
        client.close_connection(error_code=h2.errors.ErrorCodes.PROTOCOL_ERROR)
        conn.receive_data(client.data_to_send())
        assert conn.is_closed is True
        assert conn.draining is False

    def test_goaway_with_nothing_in_flight_closes(self):
        conn, client, sock = self._open()
        client.close_connection()
        conn.receive_data(client.data_to_send())
        assert conn.is_closed is True


class TestStreamingEdgeCases:
    """Frames for unknown streams and failures while crediting or resetting."""

    def _open(self):
        from gunicorn.http2.connection import HTTP2ServerConnection

        sock = MockSocket()
        conn = HTTP2ServerConnection(MockConfig(), sock, ('127.0.0.1', 12345))
        conn.initiate_connection()
        client = create_client_connection()
        conn.receive_data(client.data_to_send())
        client.receive_data(sock.get_sent_data())
        return conn, client, sock

    def _post(self, client, stream_id=1):
        client.send_headers(
            stream_id=stream_id,
            headers=[
                (':method', 'POST'),
                (':path', '/'),
                (':scheme', 'https'),
                (':authority', 'localhost'),
            ],
            end_stream=False,
        )

    def test_data_and_trailers_for_a_cleaned_up_stream_are_ignored(self):
        conn, client, sock = self._open()
        self._post(client)
        requests = conn.receive_data(client.data_to_send())
        conn.cleanup_stream(1)
        client.send_data(1, b"late", end_stream=False)
        client.send_headers(1, [('x-t', '1')], end_stream=True)
        assert conn.receive_data(client.data_to_send()) == []
        assert conn.is_closed is False

    def test_credit_after_close_is_dropped(self):
        conn, client, sock = self._open()
        self._post(client)
        req = conn.receive_data(client.data_to_send())[0]
        client.send_data(1, b"abc", end_stream=True)
        conn.receive_data(client.data_to_send())
        conn.close()
        conn.h2_conn.increment_flow_control_window = mock.Mock()
        assert req.body.read() == b"abc"
        conn.h2_conn.increment_flow_control_window.assert_not_called()

    def test_credit_failure_is_swallowed(self):
        conn, client, sock = self._open()
        self._post(client)
        req = conn.receive_data(client.data_to_send())[0]
        client.send_data(1, b"abc", end_stream=True)
        conn.receive_data(client.data_to_send())
        conn.h2_conn.increment_flow_control_window = mock.Mock(
            side_effect=h2.exceptions.StreamClosedError(1))
        assert req.body.read() == b"abc"

    def test_cleanup_survives_reset_and_write_failures(self):
        conn, client, sock = self._open()
        self._post(client)
        conn.receive_data(client.data_to_send())
        conn.h2_conn.reset_stream = mock.Mock(
            side_effect=h2.exceptions.StreamClosedError(1))
        sock.close()
        conn.cleanup_stream(1)
        assert 1 not in conn.streams

    def test_acknowledge_rejects_non_positive(self):
        conn, client, sock = self._open()
        conn.h2_conn.increment_flow_control_window = mock.Mock()
        conn.acknowledge_data(1, 0)
        conn.h2_conn.increment_flow_control_window.assert_not_called()

    def test_frames_for_a_stream_we_dropped_are_ignored(self):
        """h2 still tracks the stream; gunicorn no longer does."""
        conn, client, sock = self._open()
        self._post(client)
        conn.receive_data(client.data_to_send())
        conn.streams.pop(1)
        client.send_data(1, b"late", end_stream=False)
        client.send_headers(1, [('x-t', '1')], end_stream=True)
        assert conn.receive_data(client.data_to_send()) == []
        assert conn.is_closed is False

    def test_cleanup_write_failure_is_swallowed(self):
        conn, client, sock = self._open()
        self._post(client)
        conn.receive_data(client.data_to_send())
        sock.close()
        conn.cleanup_stream(1)
        assert 1 not in conn.streams
        assert conn.is_closed is True

    def test_arrival_credit_failure_is_swallowed(self):
        conn, client, sock = self._open()
        self._post(client)
        req = conn.receive_data(client.data_to_send())[0]
        conn.h2_conn.increment_flow_control_window = mock.Mock(
            side_effect=h2.exceptions.ProtocolError("nope"))
        client.send_data(1, b"abc", end_stream=True)
        conn.receive_data(client.data_to_send())
        assert req.body.read() == b"abc"


class TestSendCreditWait:
    """The send-credit wait handles frames in order and is bounded by cfg.timeout."""

    def _open_get(self, timeout=30):
        """A served GET on stream 1 over a real socketpair, window held at 0."""
        import socket
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        cfg.set("timeout", timeout)
        server_sock, client_sock = socket.socketpair()
        conn = HTTP2ServerConnection(cfg, server_sock, ('127.0.0.1', 12345))
        conn.initiate_connection()
        client = create_client_connection()
        client.update_settings({h2.settings.SettingCodes.INITIAL_WINDOW_SIZE: 0})
        conn.receive_data(client.data_to_send())
        client.receive_data(client_sock.recv(65535))
        client.send_headers(1, [
            (':method', 'GET'), (':path', '/'),
            (':scheme', 'https'), (':authority', 'localhost'),
        ], end_stream=True)
        conn.receive_data(client.data_to_send())
        client_sock.setblocking(False)
        return conn, client, server_sock, client_sock

    def _server_events(self, client, client_sock):
        try:
            data = client_sock.recv(65535)
        except BlockingIOError:
            return []
        return client.receive_data(data)

    def test_deferred_events_are_processed_without_a_read(self):
        from gunicorn.http2.connection import HTTP2ServerConnection

        sock = MockSocket()
        conn = HTTP2ServerConnection(MockConfig(), sock, ('127.0.0.1', 12345))
        conn.initiate_connection()
        marker = mock.Mock(name="event")
        conn._deferred_events.append(marker)
        request = mock.Mock(name="request")
        request.stream.state = StreamState.OPEN
        conn._handle_event = mock.Mock(return_value=request)
        sock.recv = mock.Mock(side_effect=AssertionError("socket read"))
        assert conn.receive_data() == [request]
        conn._handle_event.assert_called_once_with(marker)
        assert not conn._deferred_events

    def test_reset_during_wait_marks_stream_and_keeps_other_events(self):
        conn, client, server_sock, client_sock = self._open_get()
        client.reset_stream(1, error_code=h2.errors.ErrorCodes.CANCEL)
        client.send_headers(3, [
            (':method', 'GET'), (':path', '/other'),
            (':scheme', 'https'), (':authority', 'localhost'),
        ], end_stream=True)
        client_sock.sendall(client.data_to_send())

        assert conn._wait_for_flow_control_window(1) == -1
        assert conn.streams[1].state is StreamState.CLOSED
        kinds = [type(e).__name__ for e in conn._deferred_events]
        assert "RequestReceived" in kinds
        assert [r.stream.stream_id for r in conn.receive_data()] == [3]

    def test_graceful_goaway_during_wait_keeps_waiting(self):
        from hyperframe.frame import GoAwayFrame
        conn, client, server_sock, client_sock = self._open_get()
        client_sock.sendall(GoAwayFrame(0, last_stream_id=1, error_code=0).serialize())
        client.increment_flow_control_window(1000, stream_id=1)
        client_sock.sendall(client.data_to_send())

        assert conn._wait_for_flow_control_window(1) == 1000
        assert conn.draining is True
        assert conn.is_closed is False

    def test_goaway_with_error_during_wait_returns_minus_one(self):
        from hyperframe.frame import GoAwayFrame
        conn, client, server_sock, client_sock = self._open_get()
        client_sock.sendall(GoAwayFrame(0, last_stream_id=1, error_code=2).serialize())
        assert conn._wait_for_flow_control_window(1) == -1
        assert conn.is_closed is True

    def test_stalled_peer_is_cancelled_after_the_deadline(self):
        conn, client, server_sock, client_sock = self._open_get(timeout=1)
        conn.stream_timeout = 0.2
        assert conn.send_response_headers(1, 200, [], end_stream=False) is True
        assert conn.send_data(1, b"x" * 10, end_stream=True) is False
        assert 1 not in conn.streams
        events = self._server_events(client, client_sock)
        resets = [e for e in events if isinstance(e, h2.events.StreamReset)]
        assert [r.error_code for r in resets] == [h2.errors.ErrorCodes.CANCEL]

    def test_timeout_zero_means_no_deadline(self):
        conn, client, server_sock, client_sock = self._open_get(timeout=0)
        assert conn.stream_timeout is None
        import threading

        def widen():
            client.increment_flow_control_window(100, stream_id=1)
            client_sock.sendall(client.data_to_send())
        threading.Timer(0.3, widen).start()
        assert conn._wait_for_flow_control_window(1, None) == 100


class TestErrorAfterHeaders:
    """An error once headers went out resets the stream; HPACK stays intact."""

    def _served_get(self, stream_id=1):
        from gunicorn.http2.connection import HTTP2ServerConnection

        sock = MockSocket()
        conn = HTTP2ServerConnection(MockConfig(), sock, ('127.0.0.1', 12345))
        conn.initiate_connection()
        client = create_client_connection()
        conn.receive_data(client.data_to_send())
        client.receive_data(sock.get_sent_data())
        client.send_headers(stream_id, [
            (':method', 'GET'), (':path', '/'),
            (':scheme', 'https'), (':authority', 'localhost'),
        ], end_stream=True)
        conn.receive_data(client.data_to_send())
        return conn, client, sock

    def test_send_error_after_headers_resets_with_internal_error(self):
        conn, client, sock = self._served_get()
        assert conn.send_response_headers(1, 200, [('content-length', '3')]) is True
        before = len(sock.get_sent_data())
        table = len(conn.h2_conn.encoder.header_table.dynamic_entries)

        conn.send_error(1, 500, "boom")

        events = client.receive_data(sock.get_sent_data()[before:])
        kinds = [type(e).__name__ for e in events]
        assert "ResponseReceived" not in kinds
        resets = [e for e in events if isinstance(e, h2.events.StreamReset)]
        assert [r.error_code for r in resets] == [h2.errors.ErrorCodes.INTERNAL_ERROR]
        assert len(conn.h2_conn.encoder.header_table.dynamic_entries) == table
        assert 1 not in conn.streams

    def test_later_stream_decodes_correctly_after_a_refused_second_headers(self):
        conn, client, sock = self._served_get()
        assert conn.send_response_headers(1, 200, [('content-length', '3')]) is True
        assert conn.send_response_headers(1, 500, [('x-a', '1')]) is False
        conn.send_error(1, 500, "boom")
        client.receive_data(sock.get_sent_data())

        client.send_headers(3, [
            (':method', 'GET'), (':path', '/next'),
            (':scheme', 'https'), (':authority', 'localhost'),
        ], end_stream=True)
        conn.receive_data(client.data_to_send())
        before = len(sock.get_sent_data())
        assert conn.send_response(3, 200, [('content-length', '3')], b"abc") is True
        events = client.receive_data(sock.get_sent_data()[before:])
        headers = [dict(e.headers) for e in events
                   if isinstance(e, h2.events.ResponseReceived)]
        assert headers == [{b':status': b'200', b'content-length': b'3'}]

    def test_informational_after_final_headers_is_refused(self):
        conn, client, sock = self._served_get()
        assert conn.send_response_headers(1, 200, []) is True
        with pytest.raises(HTTP2Error):
            conn.send_informational(1, 103, [('link', '</a>; rel=preload')])

    def test_cleanup_of_a_never_started_response_resets(self):
        conn, client, sock = self._served_get()
        before = len(sock.get_sent_data())
        conn.cleanup_stream(1)
        events = client.receive_data(sock.get_sent_data()[before:])
        resets = [e for e in events if isinstance(e, h2.events.StreamReset)]
        assert [r.error_code for r in resets] == [h2.errors.ErrorCodes.INTERNAL_ERROR]


class TestSocketTimeouts:
    """An idle connection or a stalled body read cannot hold the thread forever."""

    def _open(self, keepalive=2, timeout=30):
        import socket
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        cfg.set("keepalive", keepalive)
        cfg.set("timeout", timeout)
        server_sock, client_sock = socket.socketpair()
        conn = HTTP2ServerConnection(cfg, server_sock, ('127.0.0.1', 12345))
        conn.initiate_connection()
        client = create_client_connection()
        conn.receive_data(client.data_to_send())
        client.receive_data(client_sock.recv(65535))
        client_sock.setblocking(False)
        return conn, client, server_sock, client_sock

    def _events(self, client, client_sock):
        try:
            return client.receive_data(client_sock.recv(65535))
        except BlockingIOError:
            return []

    def test_idle_connection_gets_goaway_after_keepalive(self):
        conn, client, server_sock, client_sock = self._open()
        conn.idle_timeout = 0.2
        assert conn.receive_data() == []
        assert conn.is_closed is True
        kinds = [type(e).__name__ for e in self._events(client, client_sock)]
        assert "ConnectionTerminated" in kinds

    def test_stalled_body_read_resets_the_stream(self):
        from gunicorn.http2.errors import HTTP2StreamError
        conn, client, server_sock, client_sock = self._open()
        conn.stream_timeout = 0.2
        client.send_headers(1, [
            (':method', 'POST'), (':path', '/'),
            (':scheme', 'https'), (':authority', 'localhost'),
        ], end_stream=False)
        client_sock.sendall(client.data_to_send())
        req = conn.receive_data()[0]
        with pytest.raises(HTTP2StreamError):
            req.body.read()
        assert 1 not in conn.streams
        assert conn.is_closed is False
        resets = [e for e in self._events(client, client_sock)
                  if isinstance(e, h2.events.StreamReset)]
        assert [r.error_code for r in resets] == [h2.errors.ErrorCodes.CANCEL]

    def test_idle_timeout_does_not_close_with_a_stream_open(self):
        conn, client, server_sock, client_sock = self._open()
        conn.idle_timeout = 0.2
        client.send_headers(1, [
            (':method', 'POST'), (':path', '/'),
            (':scheme', 'https'), (':authority', 'localhost'),
        ], end_stream=False)
        client_sock.sendall(client.data_to_send())
        conn.receive_data()
        assert conn.receive_data() == []
        assert conn.is_closed is False

    def test_zero_timeouts_disable_socket_timeout(self):
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        cfg.set("keepalive", 0)
        cfg.set("timeout", 0)
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        assert conn.idle_timeout is None
        assert conn.stream_timeout is None
        sock.settimeout = mock.Mock()
        sock.set_recv_data(b"")
        conn.receive_data()
        sock.settimeout.assert_called_once_with(None)


class TestStreamFloods:
    """HEADERS+RST_STREAM pairs cannot pile up behind a body read."""

    def _open_post(self, max_streams=100):
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        cfg.set("http2_max_concurrent_streams", max_streams)
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()
        client = create_client_connection()
        conn.receive_data(client.data_to_send())
        client.receive_data(sock.get_sent_data())
        client.send_headers(1, [
            (':method', 'POST'), (':path', '/'),
            (':scheme', 'https'), (':authority', 'localhost'),
        ], end_stream=False)
        req = conn.receive_data(client.data_to_send())[0]
        return conn, client, sock, req

    def _get(self, client, stream_id):
        client.send_headers(stream_id, [
            (':method', 'GET'), (':path', '/'),
            (':scheme', 'https'), (':authority', 'localhost'),
        ], end_stream=True)

    def test_reset_before_dispatch_drops_the_stream(self):
        conn, client, sock, req = self._open_post()
        self._get(client, 3)
        client.reset_stream(3, error_code=h2.errors.ErrorCodes.CANCEL)
        sock.set_recv_data(client.data_to_send())
        conn.pump(1)
        assert 3 not in conn.streams
        assert not conn.pending_requests

    def test_reset_after_queueing_is_not_handed_out(self):
        conn, client, sock, req = self._open_post()
        self._get(client, 3)
        sock.set_recv_data(client.data_to_send())
        conn.pump(1)
        assert [r.stream.stream_id for r in conn.pending_requests] == [3]
        client.reset_stream(3, error_code=h2.errors.ErrorCodes.CANCEL)
        sock.set_recv_data(client.data_to_send())
        conn.pump(1)
        assert not conn.pending_requests
        assert 3 not in conn.streams
        assert conn.receive_data(b"") == []

    def test_reset_pairs_below_the_rate_limit_leave_nothing_behind(self):
        from gunicorn.http2 import connection as connmod
        conn, client, sock, req = self._open_post()
        for sid in range(3, 3 + 2 * (connmod.RST_STREAM_RATE_LIMIT - 1), 2):
            self._get(client, sid)
            client.reset_stream(sid, error_code=h2.errors.ErrorCodes.CANCEL)
        data = client.data_to_send()
        for i in range(0, len(data), 65536):
            conn.receive_data(data[i:i + 65536])
        assert list(conn.streams) == [1]
        assert not conn.pending_requests
        assert conn.is_closed is False

    def test_reset_flood_gets_enhance_your_calm(self):
        from gunicorn.http2 import connection as connmod
        conn, client, sock, req = self._open_post()
        for sid in range(3, 3 + 2 * (connmod.RST_STREAM_RATE_LIMIT + 1), 2):
            self._get(client, sid)
            client.reset_stream(sid, error_code=h2.errors.ErrorCodes.CANCEL)
        data = client.data_to_send()
        before = len(sock.get_sent_data())
        with pytest.raises(HTTP2ProtocolError):
            for i in range(0, len(data), 65536):
                conn.receive_data(data[i:i + 65536])
        assert conn.is_closed is True
        kinds = frame_types(sock.get_sent_data()[before:])
        assert "GoAwayFrame" in kinds


class TestEmptyFinalChunk:
    """send_data(b"", end_stream=True) must put END_STREAM on the wire."""

    def _served_get(self):
        from gunicorn.http2.connection import HTTP2ServerConnection

        sock = MockSocket()
        conn = HTTP2ServerConnection(MockConfig(), sock, ('127.0.0.1', 12345))
        conn.initiate_connection()
        client = create_client_connection()
        conn.receive_data(client.data_to_send())
        client.receive_data(sock.get_sent_data())
        client.send_headers(1, [
            (':method', 'GET'), (':path', '/'),
            (':scheme', 'https'), (':authority', 'localhost'),
        ], end_stream=True)
        conn.receive_data(client.data_to_send())
        return conn, client, sock

    def test_empty_final_chunk_ends_the_stream(self):
        conn, client, sock = self._served_get()
        before = len(sock.get_sent_data())
        assert conn.send_response_headers(1, 200, []) is True
        assert conn.send_data(1, b"part", end_stream=False) is True
        assert conn.send_data(1, b"", end_stream=True) is True
        events = client.receive_data(sock.get_sent_data()[before:])
        kinds = [type(e).__name__ for e in events]
        assert kinds == ["ResponseReceived", "DataReceived", "DataReceived", "StreamEnded"]
        assert conn.streams[1].response_complete is True

    def test_empty_chunk_without_end_stream_sends_nothing(self):
        conn, client, sock = self._served_get()
        assert conn.send_response_headers(1, 200, []) is True
        before = len(sock.get_sent_data())
        assert conn.send_data(1, b"", end_stream=False) is True
        assert sock.get_sent_data()[before:] == b""

    def test_end_stream_delegates_to_send_data(self):
        conn, client, sock = self._served_get()
        before = len(sock.get_sent_data())
        assert conn.send_response_headers(1, 200, []) is True
        assert conn.end_stream(1) is True
        events = client.receive_data(sock.get_sent_data()[before:])
        assert "StreamEnded" in [type(e).__name__ for e in events]


class TestBadRequestsAreStreamErrors:
    """A request gunicorn cannot accept resets its stream, nothing more."""

    def _open(self, **cfg_values):
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        for k, v in cfg_values.items():
            cfg.set(k, v)
        sock = MockSocket()
        conn = HTTP2ServerConnection(cfg, sock, ('127.0.0.1', 12345))
        conn.initiate_connection()
        client = create_client_connection()
        conn.receive_data(client.data_to_send())
        client.receive_data(sock.get_sent_data())
        return conn, client, sock

    def _resets(self, client, sock, since):
        events = client.receive_data(sock.get_sent_data()[since:])
        return [(e.stream_id, e.error_code) for e in events
                if isinstance(e, h2.events.StreamReset)]

    def test_control_character_in_a_value_resets_only_that_stream(self):
        conn, client, sock = self._open()
        for sid, value in ((1, "ok"), (3, "bad\x01value"), (5, "ok")):
            client.send_headers(sid, [
                (':method', 'GET'), (':path', '/'),
                (':scheme', 'https'), (':authority', 'localhost'),
                ('x-thing', value),
            ], end_stream=True)
        before = len(sock.get_sent_data())
        requests = conn.receive_data(client.data_to_send())
        assert [r.stream.stream_id for r in requests] == [1, 5]
        assert 3 not in conn.streams
        assert self._resets(client, sock, before) == [(3, h2.errors.ErrorCodes.PROTOCOL_ERROR)]
        assert conn.is_closed is False

    def test_request_line_and_field_limits_apply(self):
        conn, client, sock = self._open(limit_request_line=64, limit_request_fields=3,
                                        limit_request_field_size=40)
        base = [(':method', 'GET'), (':scheme', 'https'), (':authority', 'localhost')]
        client.send_headers(1, base + [(':path', '/' + 'a' * 100)], end_stream=True)
        client.send_headers(3, base + [(':path', '/'), ('a', '1'), ('b', '2'), ('c', '3'), ('d', '4')],
                            end_stream=True)
        client.send_headers(5, base + [(':path', '/'), ('x-long', 'v' * 60)], end_stream=True)
        client.send_headers(7, base + [(':path', '/fine'), ('x', '1')], end_stream=True)
        before = len(sock.get_sent_data())
        requests = conn.receive_data(client.data_to_send())
        assert [r.stream.stream_id for r in requests] == [7]
        assert sorted(sid for sid, _ in self._resets(client, sock, before)) == [1, 3, 5]

    def test_method_must_be_a_token(self):
        conn, client, sock = self._open()
        client.send_headers(1, [
            (':method', 'g e t'), (':path', '/'),
            (':scheme', 'https'), (':authority', 'localhost'),
        ], end_stream=True)
        before = len(sock.get_sent_data())
        assert conn.receive_data(client.data_to_send()) == []
        assert self._resets(client, sock, before) == [(1, h2.errors.ErrorCodes.PROTOCOL_ERROR)]

    def test_forbidden_trailers_are_dropped(self):
        conn, client, sock = self._open()
        client.send_headers(1, [
            (':method', 'POST'), (':path', '/'),
            (':scheme', 'https'), (':authority', 'localhost'),
        ], end_stream=False)
        req = conn.receive_data(client.data_to_send())[0]
        client.send_data(1, b"x", end_stream=False)
        client.send_headers(1, [('content-length', '99'), ('x-sum', 'abc')], end_stream=True)
        sock.set_recv_data(client.data_to_send())
        assert req.body.read() == b"x"
        assert req.trailers == [('X-SUM', 'abc')]

    def test_outbound_chunks_respect_the_peer_frame_size(self):
        """Our own max_frame_size is for inbound frames; the peer's rules ours."""
        conn, client, sock = self._open(http2_max_frame_size=32768)
        client.send_headers(1, [
            (':method', 'GET'), (':path', '/'),
            (':scheme', 'https'), (':authority', 'localhost'),
        ], end_stream=True)
        conn.receive_data(client.data_to_send())
        before = len(sock.get_sent_data())
        assert conn.send_response(1, 200, [], b"x" * 20000) is True
        kinds = frame_types(sock.get_sent_data()[before:])
        assert kinds.count("DataFrame") == 2

    def test_header_list_size_zero_is_not_advertised(self):
        from gunicorn.http2.connection import HTTP2ServerConnection

        cfg = MockConfig()
        cfg.set("http2_max_header_list_size", 0)
        conn = HTTP2ServerConnection(cfg, MockSocket(), ('127.0.0.1', 12345))
        conn.initiate_connection()
        # Left at h2's own default rather than advertised as 0, which
        # would refuse every request.
        assert conn.h2_conn.local_settings.max_header_list_size


class TestExpectContinue:
    def test_100_is_sent_before_the_body_is_pulled(self):
        from gunicorn.http2.connection import HTTP2ServerConnection

        sock = MockSocket()
        conn = HTTP2ServerConnection(MockConfig(), sock, ('127.0.0.1', 12345))
        conn.initiate_connection()
        client = create_client_connection()
        conn.receive_data(client.data_to_send())
        client.receive_data(sock.get_sent_data())
        client.send_headers(1, [
            (':method', 'POST'), (':path', '/'),
            (':scheme', 'https'), (':authority', 'localhost'),
            ('expect', '100-continue'),
        ], end_stream=False)
        req = conn.receive_data(client.data_to_send())[0]
        assert req.stream.expect_continue is True

        client.send_data(1, b"payload", end_stream=True)
        sock.set_recv_data(client.data_to_send())
        before = len(sock.get_sent_data())
        assert req.body.read() == b"payload"
        events = client.receive_data(sock.get_sent_data()[before:])
        informational = [e for e in events if isinstance(e, h2.events.InformationalResponseReceived)]
        assert [dict(e.headers)[b':status'] for e in informational] == [b'100']
        assert req.stream.expect_continue is False
