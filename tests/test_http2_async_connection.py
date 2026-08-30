# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for async HTTP/2 server connection."""

import asyncio
import pytest

from gunicorn.config import Config
from unittest import mock
from io import BytesIO

# Check if h2 is available for integration tests
try:
    import h2.connection
    import h2.config
    import h2.events
    import h2.errors
    H2_AVAILABLE = True
except ImportError:
    H2_AVAILABLE = False

from gunicorn.http2.stream import StreamState
from gunicorn.http2.errors import (
    HTTP2Error, HTTP2ConnectionError
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


class MockAsyncReader:
    """Mock asyncio StreamReader for testing."""

    def __init__(self, data=b''):
        self._buffer = BytesIO(data)
        self._eof = False

    async def read(self, n=-1):
        data = self._buffer.read(n)
        if not data and self._eof:
            return b''
        return data

    def set_data(self, data):
        self._buffer = BytesIO(data)

    def set_eof(self):
        self._eof = True
        self._buffer = BytesIO(b'')


class MockAsyncWriter:
    """Mock asyncio StreamWriter for testing."""

    def __init__(self):
        self._buffer = bytearray()
        self._closed = False
        self._drained = False

    def write(self, data):
        if self._closed:
            raise OSError("Writer is closed")
        self._buffer.extend(data)

    async def drain(self):
        self._drained = True

    def close(self):
        self._closed = True

    async def wait_closed(self):
        pass

    def get_written_data(self):
        return bytes(self._buffer)

    def clear(self):
        self._buffer.clear()


def create_client_connection():
    """Create an h2 client connection for generating test frames."""
    config = h2.config.H2Configuration(client_side=True)
    conn = h2.connection.H2Connection(config=config)
    conn.initiate_connection()
    return conn


class TestAsyncHTTP2ConnectionInit:
    """Test AsyncHTTP2Connection initialization."""

    def test_basic_initialization(self):
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))

        assert conn.cfg is cfg
        assert conn.reader is reader
        assert conn.writer is writer
        assert conn.client_addr == ('127.0.0.1', 12345)
        assert conn.streams == {}
        assert conn.is_closed is False
        assert conn._initialized is False

    def test_settings_from_config(self):
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        cfg.set("http2_max_concurrent_streams", 50)

        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))

        assert conn.max_concurrent_streams == 50


class TestAsyncHTTP2ConnectionInitiate:
    """Test async connection initiation."""

    @pytest.mark.asyncio
    async def test_initiate_connection(self):
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))

        await conn.initiate_connection()

        assert conn._initialized is True
        written_data = writer.get_written_data()
        assert len(written_data) > 0

    @pytest.mark.asyncio
    async def test_initiate_connection_idempotent(self):
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))

        await conn.initiate_connection()
        first_len = len(writer.get_written_data())

        await conn.initiate_connection()
        second_len = len(writer.get_written_data())

        assert first_len == second_len


class TestAsyncHTTP2ConnectionReceiveData:
    """Test async receiving and processing data."""

    @pytest.mark.asyncio
    async def test_receive_empty_data_closes_connection(self):
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = MockAsyncReader()
        reader.set_eof()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))
        await conn.initiate_connection()

        requests = await conn.receive_data()

        assert conn.is_closed is True
        assert requests == []

    @pytest.mark.asyncio
    async def test_receive_simple_get_request(self):
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))
        await conn.initiate_connection()

        # Create client and exchange settings
        client = create_client_connection()
        client_preface = client.data_to_send()
        reader.set_data(client_preface)

        await conn.receive_data()

        server_data = writer.get_written_data()
        if server_data:
            client.receive_data(server_data)

        # Client sends GET request
        client.send_headers(
            stream_id=1,
            headers=[
                (':method', 'GET'),
                (':path', '/async-test'),
                (':scheme', 'https'),
                (':authority', 'localhost'),
            ],
            end_stream=True
        )
        reader.set_data(client.data_to_send())

        requests = await conn.receive_data()

        assert len(requests) == 1
        assert requests[0].method == 'GET'
        assert requests[0].path == '/async-test'

    @pytest.mark.asyncio
    async def test_receive_with_timeout(self):
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))
        await conn.initiate_connection()

        client = create_client_connection()
        reader.set_data(client.data_to_send())

        # Should complete without timeout
        await conn.receive_data(timeout=5.0)

    @pytest.mark.asyncio
    async def test_receive_timeout_raises(self):
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()

        # Create a reader that blocks forever
        async def blocking_read(n):
            await asyncio.sleep(10)
            return b''

        reader = mock.Mock()
        reader.read = mock.AsyncMock(side_effect=blocking_read)
        writer = MockAsyncWriter()

        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))
        await conn.initiate_connection()

        # Timeout is converted to HTTP2ConnectionError by the implementation
        with pytest.raises((asyncio.TimeoutError, HTTP2ConnectionError)):
            await conn.receive_data(timeout=0.01)


class TestAsyncHTTP2ConnectionSendResponse:
    """Test async sending responses."""

    @pytest.mark.asyncio
    async def test_send_simple_response(self):
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))
        await conn.initiate_connection()

        # Setup stream via request
        client = create_client_connection()
        reader.set_data(client.data_to_send())
        await conn.receive_data()

        client.receive_data(writer.get_written_data())

        client.send_headers(1, [
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=True)
        reader.set_data(client.data_to_send())
        await conn.receive_data()

        writer.clear()
        await conn.send_response(
            stream_id=1,
            status=200,
            headers=[('content-type', 'text/plain')],
            body=b'Async Hello!'
        )

        events = client.receive_data(writer.get_written_data())
        data_events = [e for e in events if isinstance(e, h2.events.DataReceived)]
        assert len(data_events) == 1
        assert data_events[0].data == b'Async Hello!'

    @pytest.mark.asyncio
    async def test_send_response_invalid_stream(self):
        """Test that sending response on invalid stream returns False."""
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))
        await conn.initiate_connection()

        # Sending to a non-existent stream should return False gracefully
        result = await conn.send_response(stream_id=999, status=200, headers=[], body=None)
        assert result is False


class TestAsyncHTTP2ConnectionSendData:
    """Test async send_data method."""

    @pytest.mark.asyncio
    async def test_send_data(self):
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))
        await conn.initiate_connection()

        # Setup stream
        client = create_client_connection()
        reader.set_data(client.data_to_send())
        await conn.receive_data()
        client.receive_data(writer.get_written_data())

        client.send_headers(1, [
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=True)
        reader.set_data(client.data_to_send())
        await conn.receive_data()

        # Send full response using send_response
        writer.clear()
        await conn.send_response(
            stream_id=1,
            status=200,
            headers=[('content-type', 'text/plain')],
            body=b'chunk1chunk2'
        )

        events = client.receive_data(writer.get_written_data())
        data_events = [e for e in events if isinstance(e, h2.events.DataReceived)]
        assert len(data_events) >= 1
        all_data = b''.join(e.data for e in data_events)
        assert all_data == b'chunk1chunk2'


def get_h2_header_value(headers_list, name):
    """Extract a header value from h2 headers list."""
    for header_name, header_value in headers_list:
        name_str = header_name.decode() if isinstance(header_name, bytes) else header_name
        if name_str == name:
            return header_value.decode() if isinstance(header_value, bytes) else header_value
    return None


class TestAsyncHTTP2ConnectionSendError:
    """Test async error response sending."""

    @pytest.mark.asyncio
    async def test_send_error(self):
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))
        await conn.initiate_connection()

        client = create_client_connection()
        reader.set_data(client.data_to_send())
        await conn.receive_data()
        client.receive_data(writer.get_written_data())

        client.send_headers(1, [
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=True)
        reader.set_data(client.data_to_send())
        await conn.receive_data()

        writer.clear()
        await conn.send_error(stream_id=1, status_code=500, message="Internal Error")

        events = client.receive_data(writer.get_written_data())
        response_events = [e for e in events if isinstance(e, h2.events.ResponseReceived)]
        assert len(response_events) == 1
        headers_list = response_events[0].headers
        assert get_h2_header_value(headers_list, ':status') == '500'


class TestAsyncHTTP2ConnectionResetStream:
    """Test async stream reset."""

    @pytest.mark.asyncio
    async def test_reset_stream(self):
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))
        await conn.initiate_connection()

        client = create_client_connection()
        reader.set_data(client.data_to_send())
        await conn.receive_data()
        client.receive_data(writer.get_written_data())

        client.send_headers(1, [
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=False)
        reader.set_data(client.data_to_send())
        await conn.receive_data()

        writer.clear()
        await conn.reset_stream(stream_id=1, error_code=0x8)

        events = client.receive_data(writer.get_written_data())
        reset_events = [e for e in events if isinstance(e, h2.events.StreamReset)]
        assert len(reset_events) == 1


class TestAsyncHTTP2ConnectionClose:
    """Test async connection close."""

    @pytest.mark.asyncio
    async def test_close_connection(self):
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))
        await conn.initiate_connection()

        client = create_client_connection()
        reader.set_data(client.data_to_send())
        await conn.receive_data()

        writer.clear()
        await conn.close()

        assert conn.is_closed is True
        assert writer._closed is True

    @pytest.mark.asyncio
    async def test_close_idempotent(self):
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))
        await conn.initiate_connection()

        await conn.close()
        await conn.close()  # Should not raise


class TestAsyncHTTP2ConnectionCleanup:
    """Test async stream cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_stream(self):
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))
        await conn.initiate_connection()

        client = create_client_connection()
        reader.set_data(client.data_to_send())
        await conn.receive_data()
        client.receive_data(writer.get_written_data())

        client.send_headers(1, [
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=True)
        reader.set_data(client.data_to_send())
        await conn.receive_data()

        assert 1 in conn.streams
        conn.cleanup_stream(1)
        assert 1 not in conn.streams


class TestAsyncHTTP2ConnectionRepr:
    """Test async connection representation."""

    def test_repr(self):
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))

        repr_str = repr(conn)
        assert "AsyncHTTP2Connection" in repr_str
        assert "streams=" in repr_str


class TestAsyncHTTP2ConnectionSocketErrors:
    """Test socket error handling in async connection."""

    @pytest.mark.asyncio
    async def test_read_error_raises_connection_error(self):
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = mock.Mock()
        reader.read = mock.AsyncMock(side_effect=OSError("Connection reset"))
        writer = MockAsyncWriter()

        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))
        await conn.initiate_connection()

        with pytest.raises(HTTP2ConnectionError):
            await conn.receive_data()

    @pytest.mark.asyncio
    async def test_write_error_raises_connection_error(self):
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = MockAsyncReader()
        writer = mock.Mock()
        writer.write = mock.Mock(side_effect=OSError("Broken pipe"))
        writer.drain = mock.AsyncMock()

        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))

        with pytest.raises(HTTP2ConnectionError):
            await conn.initiate_connection()


class TestAsyncHTTP2ConnectionPriority:
    """Test async HTTP/2 priority handling."""

    @pytest.mark.asyncio
    async def test_handle_priority_updated_existing_stream(self):
        """Test handling priority update for existing stream."""
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))

        # Create a client connection to generate frames
        client_conn = create_client_connection()
        client_data = client_conn.data_to_send()

        # Set up reader with client preface
        reader.set_data(client_data)

        await conn.initiate_connection()
        await conn.receive_data()
        writer.clear()

        # Send a request to create a stream
        client_conn.send_headers(1, [
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ])
        request_data = client_conn.data_to_send()
        reader.set_data(request_data)
        await conn.receive_data()

        # Verify stream was created
        assert 1 in conn.streams
        stream = conn.streams[1]

        # Default priority values
        assert stream.priority_weight == 16
        assert stream.priority_depends_on == 0

        # Send a PRIORITY frame
        client_conn.prioritize(1, weight=128, depends_on=0, exclusive=False)
        priority_data = client_conn.data_to_send()
        reader.set_data(priority_data)
        await conn.receive_data()

        # Verify priority was updated
        assert stream.priority_weight == 128

    @pytest.mark.asyncio
    async def test_handle_priority_updated_nonexistent_stream(self):
        """Test that priority update for nonexistent stream is ignored."""
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))

        # Create a client connection
        client_conn = create_client_connection()
        client_data = client_conn.data_to_send()

        reader.set_data(client_data)
        await conn.initiate_connection()
        await conn.receive_data()

        # Send a PRIORITY frame for a stream that doesn't exist
        client_conn.prioritize(99, weight=64, depends_on=0, exclusive=False)
        priority_data = client_conn.data_to_send()
        reader.set_data(priority_data)

        # Should not raise
        await conn.receive_data()


class TestAsyncHTTP2ConnectionTrailers:
    """Test async HTTP/2 response trailer support."""

    @pytest.mark.asyncio
    async def test_send_trailers_after_headers_and_body(self):
        """Test sending trailers after response headers and body."""
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))

        # Create a client connection
        client_conn = create_client_connection()
        client_data = client_conn.data_to_send()
        reader.set_data(client_data)

        await conn.initiate_connection()
        await conn.receive_data()
        writer.clear()

        # Send a request
        client_conn.send_headers(1, [
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=True)
        reader.set_data(client_conn.data_to_send())
        await conn.receive_data()

        # Manually send headers without ending stream (for trailer support)
        stream = conn.streams[1]
        response_headers = [(':status', '200'), ('content-type', 'text/plain')]
        conn.h2_conn.send_headers(1, response_headers, end_stream=False)
        stream.send_headers(response_headers, end_stream=False)
        await conn._send_pending_data()

        # Send body without ending stream
        conn.h2_conn.send_data(1, b'Hello World', end_stream=False)
        stream.send_data(b'Hello World', end_stream=False)
        await conn._send_pending_data()

        # Send trailers
        trailers = [('grpc-status', '0'), ('grpc-message', 'OK')]
        await conn.send_trailers(1, trailers)

        # Verify stream is closed
        assert stream.response_complete is True
        assert stream.response_trailers == [('grpc-status', '0'), ('grpc-message', 'OK')]

    @pytest.mark.asyncio
    async def test_send_trailers_pseudo_header_raises(self):
        """Test that pseudo-headers in trailers raise error."""
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))

        client_conn = create_client_connection()
        reader.set_data(client_conn.data_to_send())
        await conn.initiate_connection()
        await conn.receive_data()

        # Send a request
        client_conn.send_headers(1, [
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=True)
        reader.set_data(client_conn.data_to_send())
        await conn.receive_data()

        # Send response
        await conn.send_response(1, 200, [('content-type', 'text/plain')], None)

        # Try to send trailers with pseudo-header
        with pytest.raises(HTTP2Error) as exc_info:
            await conn.send_trailers(1, [(':status', '200')])
        assert "Pseudo-header" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_send_trailers_without_headers_returns_false(self):
        """Test that sending trailers without headers returns False."""
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))

        client_conn = create_client_connection()
        reader.set_data(client_conn.data_to_send())
        await conn.initiate_connection()
        await conn.receive_data()

        # Send a request
        client_conn.send_headers(1, [
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=True)
        reader.set_data(client_conn.data_to_send())
        await conn.receive_data()

        # Try to send trailers without sending headers first - should return False
        result = await conn.send_trailers(1, [('trailer', 'value')])
        assert result is False


class TestAsyncHTTP2FlowControl:
    """Test async HTTP/2 flow control handling."""

    @pytest.mark.asyncio
    async def test_send_data_respects_zero_window(self):
        """Test that send_data returns False when flow control window is 0."""
        import types
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))

        # Create client and send preface
        client_conn = create_client_connection()
        reader.set_data(client_conn.data_to_send())
        await conn.initiate_connection()
        await conn.receive_data()

        # Send a request
        client_conn.send_headers(1, [
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=True)
        reader.set_data(client_conn.data_to_send())
        await conn.receive_data()

        # Send response headers without ending stream
        conn.h2_conn.send_headers(1, [
            (':status', '200'),
            ('content-type', 'text/plain'),
        ], end_stream=False)
        await conn._send_pending_data()
        conn.streams[1].send_headers([(':status', '200')], end_stream=False)

        # Mock the flow control window to return 0
        original_window = conn.h2_conn.local_flow_control_window
        conn.h2_conn.local_flow_control_window = lambda stream_id: 0

        # Try to send data - should return False (not raise)
        # The wait is bounded by cfg.timeout; keep the test short.
        conn.cfg = types.SimpleNamespace(timeout=0.2)
        result = await conn.send_data(1, b'Hello, World!')
        assert result is False

        # Restore
        conn.h2_conn.local_flow_control_window = original_window

    @pytest.mark.asyncio
    async def test_send_data_respects_flow_control(self):
        """Test that send_data chunks data according to flow control window."""
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))

        # Create client and send preface
        client_conn = create_client_connection()
        reader.set_data(client_conn.data_to_send())
        await conn.initiate_connection()
        await conn.receive_data()

        # Send a request
        client_conn.send_headers(1, [
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=True)
        reader.set_data(client_conn.data_to_send())
        await conn.receive_data()

        # Send response headers without ending stream
        conn.h2_conn.send_headers(1, [
            (':status', '200'),
            ('content-type', 'text/plain'),
        ], end_stream=False)
        await conn._send_pending_data()
        conn.streams[1].send_headers([(':status', '200')], end_stream=False)

        # Send small data - should succeed within window
        small_data = b'Hello'
        await conn.send_data(1, small_data, end_stream=True)

        # Verify data was sent
        sent_data = writer.get_written_data()
        assert len(sent_data) > 0


class TestAsyncHTTP2StreamClosedHandling:
    """Test graceful handling of StreamClosedError in async connection."""

    @pytest.mark.asyncio
    async def test_send_response_on_closed_stream(self):
        """Test that send_response gracefully handles closed stream."""
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))

        # Create client and send preface
        client_conn = create_client_connection()
        reader.set_data(client_conn.data_to_send())
        await conn.initiate_connection()
        await conn.receive_data()

        # Send a request
        client_conn.send_headers(1, [
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=True)
        reader.set_data(client_conn.data_to_send())
        await conn.receive_data()

        # Simulate client resetting the stream
        client_conn.reset_stream(1)
        reader.set_data(client_conn.data_to_send())
        await conn.receive_data()

        # Try to send response - should return False, not raise
        result = await conn.send_response(1, 200, [('content-type', 'text/plain')], b'Hello')
        assert result is False

    @pytest.mark.asyncio
    async def test_send_data_on_reset_stream(self):
        """Test that send_data gracefully handles reset stream."""
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))

        # Create client and send preface
        client_conn = create_client_connection()
        reader.set_data(client_conn.data_to_send())
        await conn.initiate_connection()
        await conn.receive_data()

        # Send a request
        client_conn.send_headers(1, [
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=True)
        reader.set_data(client_conn.data_to_send())
        await conn.receive_data()

        # Send response headers without ending stream
        conn.h2_conn.send_headers(1, [
            (':status', '200'),
            ('content-type', 'text/plain'),
        ], end_stream=False)
        await conn._send_pending_data()
        conn.streams[1].send_headers([(':status', '200')], end_stream=False)

        # Simulate client resetting the stream
        client_conn.reset_stream(1)
        reader.set_data(client_conn.data_to_send())
        await conn.receive_data()

        # Try to send data - should return False, not raise
        result = await conn.send_data(1, b'Hello, World!', end_stream=True)
        assert result is False


class TestAsyncHTTP2WindowOverflowHandling:
    """A peer sending past the receive window gets GOAWAY(FLOW_CONTROL_ERROR)."""

    @pytest.mark.asyncio
    async def test_window_overflow_sends_goaway(self):
        from hyperframe.frame import DataFrame
        from gunicorn.http2.async_connection import AsyncHTTP2Connection
        from gunicorn.http2.errors import HTTP2ProtocolError

        cfg = MockConfig()
        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))

        client_conn = create_client_connection()
        reader.set_data(client_conn.data_to_send())
        await conn.initiate_connection()
        await conn.receive_data()
        client_conn.receive_data(writer.get_written_data())
        client_conn.send_headers(1, [
            (':method', 'POST'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'localhost'),
        ], end_stream=False)
        reader.set_data(client_conn.data_to_send())
        await conn.receive_data()

        # Nothing is credited back until the application reads, so five
        # full frames overrun the 65535 byte window.
        frames = b"".join(DataFrame(1, data=b"x" * 16384).serialize() for _ in range(5))
        reader.set_data(frames)
        writer.clear()
        # The reader hands over 64KiB per call; the overrun lands on the second.
        with pytest.raises(HTTP2ProtocolError):
            for _ in range(3):
                await conn.receive_data()

        assert conn.is_closed is True
        events = client_conn.receive_data(writer.get_written_data())
        goaway = [e for e in events if isinstance(e, h2.events.ConnectionTerminated)]
        # h2 sends one GOAWAY itself before raising; close() sends another.
        assert goaway
        assert {g.error_code for g in goaway} == {h2.errors.ErrorCodes.FLOW_CONTROL_ERROR}


class TestAsyncHTTP2ProtocolErrorHandling:
    """Test protocol error handling sends proper GOAWAY."""

    @pytest.mark.asyncio
    async def test_protocol_error_sends_goaway(self):
        """Test that protocol errors result in GOAWAY being sent."""
        from gunicorn.http2.async_connection import AsyncHTTP2Connection
        from gunicorn.http2.errors import HTTP2ProtocolError, HTTP2ErrorCode

        cfg = MockConfig()
        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))

        # Create client and send preface
        client_conn = create_client_connection()
        reader.set_data(client_conn.data_to_send())
        await conn.initiate_connection()
        await conn.receive_data()

        # Clear sent data to only capture new frames
        writer.clear()

        # Mock h2_conn.receive_data to raise ProtocolError
        def raise_protocol_error(data):
            raise h2.exceptions.ProtocolError("Test protocol error")

        conn.h2_conn.receive_data = raise_protocol_error

        # Set some dummy data for the reader
        reader.set_data(b'dummy data')

        # This should send GOAWAY and raise ProtocolError
        with pytest.raises(HTTP2ProtocolError) as exc_info:
            await conn.receive_data()

        assert "Test protocol error" in str(exc_info.value)

        # Verify something was sent (GOAWAY frame)
        sent_data = writer.get_written_data()
        assert len(sent_data) > 0
        # Connection should be marked as closed
        assert conn.is_closed is True


class TestAsyncWindowWait:
    """A response task waits for credit on a signal, never on the reader."""

    def _conn(self):
        from gunicorn.http2.async_connection import AsyncHTTP2Connection
        return AsyncHTTP2Connection(MockConfig(), MockAsyncReader(),
                                    MockAsyncWriter(), ('127.0.0.1', 12345))

    def test_queue_starts_empty(self):
        assert not self._conn()._deferred_events

    @pytest.mark.asyncio
    async def test_wait_returns_when_the_receive_loop_signals(self):
        conn = self._conn()
        windows = iter([0, 65535])
        conn.h2_conn = mock.Mock()
        conn.h2_conn.local_flow_control_window.side_effect = \
            lambda sid: next(windows)
        conn.reader = mock.Mock()
        conn.reader.read = mock.AsyncMock(side_effect=AssertionError("reader touched"))

        async def widen():
            await asyncio.sleep(0.01)
            conn._signal_window()

        asyncio.get_running_loop().create_task(widen())
        assert await conn._wait_for_flow_control_window(1) == 65535
        conn.reader.read.assert_not_called()

    @pytest.mark.asyncio
    async def test_wait_gives_up_when_the_connection_closes(self):
        conn = self._conn()
        conn.h2_conn = mock.Mock()
        conn.h2_conn.local_flow_control_window.return_value = 0
        conn._closed = True
        assert await conn._wait_for_flow_control_window(1) == -1


class TestAsyncStreamingRequestBody:
    """The request goes out on its headers; chunks are read as they arrive."""

    async def _open_post(self):
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(MockConfig(), reader, writer, ('127.0.0.1', 12345))
        await conn.initiate_connection()
        client = create_client_connection()
        reader.set_data(client.data_to_send())
        await conn.receive_data()
        client.receive_data(writer.get_written_data())
        writer.clear()
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
        reader.set_data(client.data_to_send())
        requests = await conn.receive_data()
        return conn, client, reader, writer, requests

    @pytest.mark.asyncio
    async def test_request_is_dispatched_before_the_body_arrives(self):
        conn, client, reader, writer, requests = await self._open_post()
        assert len(requests) == 1
        assert requests[0].stream.body_complete is False

    @pytest.mark.asyncio
    async def test_chunks_are_read_as_they_arrive_and_credited_back(self):
        conn, client, reader, writer, requests = await self._open_post()
        stream = requests[0].stream

        for _ in range(3):
            client.send_data(1, b"x" * 16384, end_stream=False)
        reader.set_data(client.data_to_send())
        await conn.receive_data()
        assert stream.unacked_size == 3 * 16384
        client.receive_data(writer.get_written_data())
        writer.clear()
        # Connection-level credit comes straight back, the stream's
        # only once the application reads.
        assert client.outbound_flow_control_window == 65535
        assert client.local_flow_control_window(1) == 65535 - 3 * 16384

        assert await stream.read_body_chunk() == b"x" * 16384
        assert await stream.read_body_chunk() == b"x" * 16384
        assert stream.unacked_size == 16384
        client.receive_data(writer.get_written_data())
        assert client.local_flow_control_window(1) == 65535 - 16384

        client.send_data(1, b"end", end_stream=True)
        reader.set_data(client.data_to_send())
        await conn.receive_data()
        chunks = []
        while True:
            chunk = await stream.read_body_chunk()
            if chunk is None:
                break
            chunks.append(chunk)
        assert b"".join(chunks) == b"x" * 16384 + b"end"
        assert stream.unacked_size == 0

    @pytest.mark.asyncio
    async def test_unread_body_is_reset_with_no_error_on_cleanup(self):
        conn, client, reader, writer, requests = await self._open_post()
        for _ in range(3):
            client.send_data(1, b"a" * 16384, end_stream=False)
        reader.set_data(client.data_to_send())
        await conn.receive_data()
        client.receive_data(writer.get_written_data())
        writer.clear()

        assert await conn.send_response(1, 200, [], b"done") is True
        conn.cleanup_stream(1)

        assert 1 not in conn.streams
        events = client.receive_data(writer.get_written_data())
        resets = [e for e in events if isinstance(e, h2.events.StreamReset)]
        assert len(resets) == 1
        assert resets[0].error_code == h2.errors.ErrorCodes.NO_ERROR
        assert client.outbound_flow_control_window == 65535
        assert conn.is_closed is False

    @pytest.mark.asyncio
    async def test_peer_reset_wakes_a_waiting_reader(self):
        from gunicorn.http2.errors import HTTP2StreamError
        conn, client, reader, writer, requests = await self._open_post()
        stream = requests[0].stream

        async def feed_reset():
            await asyncio.sleep(0.01)
            client.reset_stream(1, error_code=h2.errors.ErrorCodes.CANCEL)
            reader.set_data(client.data_to_send())
            await conn.receive_data()

        asyncio.get_running_loop().create_task(feed_reset())
        with pytest.raises(HTTP2StreamError):
            await asyncio.wait_for(stream.read_body_chunk(), timeout=2)


class TestAsyncStreamingEdgeCases:
    """Frames for unknown streams and failures while crediting or resetting."""

    async def _open(self):
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(MockConfig(), reader, writer, ('127.0.0.1', 12345))
        await conn.initiate_connection()
        client = create_client_connection()
        reader.set_data(client.data_to_send())
        await conn.receive_data()
        client.receive_data(writer.get_written_data())
        writer.clear()
        client.send_headers(
            stream_id=1,
            headers=[
                (':method', 'POST'),
                (':path', '/'),
                (':scheme', 'https'),
                (':authority', 'localhost'),
            ],
            end_stream=False,
        )
        reader.set_data(client.data_to_send())
        requests = await conn.receive_data()
        return conn, client, reader, writer, requests

    @pytest.mark.asyncio
    async def test_data_and_trailers_for_a_cleaned_up_stream_are_ignored(self):
        conn, client, reader, writer, requests = await self._open()
        conn.cleanup_stream(1)
        client.send_data(1, b"late", end_stream=False)
        client.send_headers(1, [('x-t', '1')], end_stream=True)
        reader.set_data(client.data_to_send())
        assert await conn.receive_data() == []
        assert conn.is_closed is False

    @pytest.mark.asyncio
    async def test_trailers_wake_reader(self):
        conn, client, reader, writer, requests = await self._open()
        stream = requests[0].stream
        client.send_data(1, b"abc", end_stream=False)
        client.send_headers(1, [('x-t', '1')], end_stream=True)
        reader.set_data(client.data_to_send())
        await conn.receive_data()
        assert await stream.read_body_chunk() == b"abc"
        assert await stream.read_body_chunk() is None
        assert requests[0].trailers == [('X-T', '1')]

    @pytest.mark.asyncio
    async def test_credit_after_close_or_failure_is_dropped(self):
        conn, client, reader, writer, requests = await self._open()
        stream = requests[0].stream
        client.send_data(1, b"abc", end_stream=False)
        client.send_data(1, b"def", end_stream=True)
        reader.set_data(client.data_to_send())
        await conn.receive_data()
        conn.h2_conn.increment_flow_control_window = mock.Mock(
            side_effect=h2.exceptions.StreamClosedError(1))
        assert await stream.read_body_chunk() == b"abc"
        conn._closed = True
        conn.h2_conn.increment_flow_control_window = mock.Mock()
        assert await stream.read_body_chunk() == b"def"
        conn.h2_conn.increment_flow_control_window.assert_not_called()
        conn.acknowledge_data(1, 0)

    @pytest.mark.asyncio
    async def test_cleanup_survives_reset_and_write_failures(self):
        conn, client, reader, writer, requests = await self._open()
        conn.h2_conn.reset_stream = mock.Mock(
            side_effect=h2.exceptions.StreamClosedError(1))
        conn.h2_conn.data_to_send = mock.Mock(return_value=b"frame")
        writer.close()
        conn.cleanup_stream(1)
        assert 1 not in conn.streams
        assert conn.is_closed is True
        conn.cleanup_stream(1)

    @pytest.mark.asyncio
    async def test_frames_for_a_stream_we_dropped_are_ignored(self):
        conn, client, reader, writer, requests = await self._open()
        conn.streams.pop(1)
        client.send_data(1, b"late", end_stream=False)
        client.send_headers(1, [('x-t', '1')], end_stream=True)
        reader.set_data(client.data_to_send())
        assert await conn.receive_data() == []
        assert conn.is_closed is False

    @pytest.mark.asyncio
    async def test_arrival_credit_failure_is_swallowed(self):
        conn, client, reader, writer, requests = await self._open()
        conn.h2_conn.increment_flow_control_window = mock.Mock(
            side_effect=h2.exceptions.ProtocolError("nope"))
        client.send_data(1, b"abc", end_stream=True)
        reader.set_data(client.data_to_send())
        await conn.receive_data()
        assert await requests[0].stream.read_body_chunk() == b"abc"


class TestSendIsAtomicAgainstGoAway:
    """HEADERS queued while another task holds the writer survive a GOAWAY."""

    @pytest.mark.asyncio
    async def test_headers_are_not_erased(self):
        from gunicorn.http2.async_connection import AsyncHTTP2Connection
        from test_http2_connection import frame_types

        class SlowWriter(MockAsyncWriter):
            """Once armed, the next drain() blocks until released."""

            def __init__(self):
                super().__init__()
                self.release = asyncio.Event()
                self.armed = False

            async def drain(self):
                if self.armed:
                    self.armed = False
                    await self.release.wait()

        reader = MockAsyncReader()
        writer = SlowWriter()
        conn = AsyncHTTP2Connection(MockConfig(), reader, writer, ('127.0.0.1', 12345))
        await conn.initiate_connection()
        client = create_client_connection()
        reader.set_data(client.data_to_send())
        await conn.receive_data()
        client.receive_data(writer.get_written_data())
        for sid in (1, 3):
            client.send_headers(sid, [
                (':method', 'GET'), (':path', f'/{sid}'),
                (':scheme', 'https'), (':authority', 'localhost'),
            ], end_stream=True)
        reader.set_data(client.data_to_send())
        await conn.receive_data()
        writer.clear()

        # Task 1 holds the writer in drain(); task 2 queues its HEADERS and
        # waits; the peer's GOAWAY is parsed meanwhile.
        writer.armed = True
        t1 = asyncio.get_running_loop().create_task(conn.send_response(1, 200, [], b"one"))
        await asyncio.sleep(0.01)
        t2 = asyncio.get_running_loop().create_task(conn.send_response(3, 200, [], b"two"))
        await asyncio.sleep(0.01)
        client.close_connection()
        reader.set_data(client.data_to_send())
        t3 = asyncio.get_running_loop().create_task(conn.receive_data())
        await asyncio.sleep(0.01)
        writer.release.set()
        await asyncio.gather(t1, t2, t3)

        kinds = frame_types(writer.get_written_data())
        assert kinds.count("HeadersFrame") == 2, kinds
        assert conn.draining is True


class TestResetDuringDrain:
    """A RST_STREAM parsed while a send awaits drain() is not a send error."""

    async def _race(self, action):
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        class SlowWriter(MockAsyncWriter):
            def __init__(self):
                super().__init__()
                self.release = asyncio.Event()
                self.armed = False

            async def drain(self):
                if self.armed:
                    self.armed = False
                    await self.release.wait()

        reader = MockAsyncReader()
        writer = SlowWriter()
        conn = AsyncHTTP2Connection(MockConfig(), reader, writer, ('127.0.0.1', 12345))
        await conn.initiate_connection()
        client = create_client_connection()
        reader.set_data(client.data_to_send())
        await conn.receive_data()
        client.receive_data(writer.get_written_data())
        client.send_headers(1, [
            (':method', 'GET'), (':path', '/'),
            (':scheme', 'https'), (':authority', 'localhost'),
        ], end_stream=True)
        reader.set_data(client.data_to_send())
        await conn.receive_data()

        writer.armed = True
        loop = asyncio.get_running_loop()
        sender = loop.create_task(action(conn))
        await asyncio.sleep(0.01)
        # The sender holds the lock in drain(); the loop parses the reset
        # now and queues behind it for its own flush.
        client.reset_stream(1, error_code=h2.errors.ErrorCodes.CANCEL)
        reader.set_data(client.data_to_send())
        receiver = loop.create_task(conn.receive_data())
        await asyncio.sleep(0.01)
        assert conn.streams[1].state is StreamState.CLOSED
        writer.release.set()
        await asyncio.wait_for(receiver, timeout=2)
        return await asyncio.wait_for(sender, timeout=2)

    @pytest.mark.asyncio
    async def test_response_headers(self):
        assert await self._race(
            lambda c: c.send_response_headers(1, [(':status', '200')])) in (True, False)

    @pytest.mark.asyncio
    async def test_full_response(self):
        assert await self._race(
            lambda c: c.send_response(1, 200, [], b"body")) in (True, False)

    @pytest.mark.asyncio
    async def test_data_then_trailers(self):
        async def action(conn):
            await conn.send_response_headers(1, [(':status', '200')])
            conn.writer.armed = True
            await conn.send_data(1, b"x" * 20000, end_stream=False)
            return await conn.send_trailers(1, [('x-t', '1')])
        assert await self._race(action) in (True, False)


class TestAsyncGracefulGoAway:
    """GOAWAY(NO_ERROR) drains established streams wherever it lands in a read."""

    @pytest.mark.asyncio
    async def test_goaway_followed_by_data_in_one_read(self):
        from hyperframe.frame import DataFrame, GoAwayFrame
        from gunicorn.http2.async_connection import AsyncHTTP2Connection
        from test_http2_connection import frame_types

        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(MockConfig(), reader, writer, ('127.0.0.1', 12345))
        await conn.initiate_connection()
        client = create_client_connection()
        reader.set_data(client.data_to_send())
        await conn.receive_data()
        client.receive_data(writer.get_written_data())
        client.send_headers(1, [
            (':method', 'POST'), (':path', '/'),
            (':scheme', 'https'), (':authority', 'localhost'),
        ], end_stream=False)
        reader.set_data(client.data_to_send())
        requests = await conn.receive_data()
        stream = requests[0].stream

        goaway = GoAwayFrame(0, last_stream_id=1, error_code=0)
        data = DataFrame(1, data=b"body")
        data.flags.add("END_STREAM")
        reader.set_data(goaway.serialize() + data.serialize())
        await conn.receive_data()

        assert conn.draining is True
        assert conn.is_closed is False
        assert await stream.read_body_chunk() == b"body"
        writer.clear()
        assert await conn.send_response(1, 200, [], b"hello") is True
        assert "HeadersFrame" in frame_types(writer.get_written_data())

    @pytest.mark.asyncio
    async def test_unfinished_response_is_reset_with_internal_error(self):
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(MockConfig(), reader, writer, ('127.0.0.1', 12345))
        await conn.initiate_connection()
        client = create_client_connection()
        reader.set_data(client.data_to_send())
        await conn.receive_data()
        client.receive_data(writer.get_written_data())
        client.send_headers(1, [
            (':method', 'GET'), (':path', '/'),
            (':scheme', 'https'), (':authority', 'localhost'),
        ], end_stream=True)
        reader.set_data(client.data_to_send())
        await conn.receive_data()
        writer.clear()

        conn.cleanup_stream(1)

        events = client.receive_data(writer.get_written_data())
        resets = [e for e in events if isinstance(e, h2.events.StreamReset)]
        assert [r.error_code for r in resets] == [h2.errors.ErrorCodes.INTERNAL_ERROR]


class TestAsyncSendCreditDeadline:
    """The send-credit wait is bounded by cfg.timeout and woken by resets."""

    async def _open_get(self, timeout):
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        cfg.set("timeout", timeout)
        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))
        await conn.initiate_connection()
        client = create_client_connection()
        client.update_settings({h2.settings.SettingCodes.INITIAL_WINDOW_SIZE: 0})
        reader.set_data(client.data_to_send())
        await conn.receive_data()
        client.receive_data(writer.get_written_data())
        client.send_headers(1, [
            (':method', 'GET'), (':path', '/'),
            (':scheme', 'https'), (':authority', 'localhost'),
        ], end_stream=True)
        reader.set_data(client.data_to_send())
        await conn.receive_data()
        writer.clear()
        return conn, client, reader, writer

    @pytest.mark.asyncio
    async def test_idle_timeout_resets_the_stream(self):
        import types
        conn, client, reader, writer = await self._open_get(timeout=1)
        conn.cfg = types.SimpleNamespace(timeout=0.2)
        assert await conn.send_response_headers(1, [(':status', '200')]) is True
        assert await conn.send_data(1, b"x" * 10, end_stream=True) is False
        assert 1 not in conn.streams
        events = client.receive_data(writer.get_written_data())
        resets = [e for e in events if isinstance(e, h2.events.StreamReset)]
        assert [r.error_code for r in resets] == [h2.errors.ErrorCodes.CANCEL]

    @pytest.mark.asyncio
    async def test_reset_wakes_a_window_waiter(self):
        conn, client, reader, writer = await self._open_get(timeout=5)
        waiter = asyncio.get_running_loop().create_task(
            conn._wait_for_flow_control_window(1))
        await asyncio.sleep(0.01)
        client.reset_stream(1, error_code=h2.errors.ErrorCodes.CANCEL)
        reader.set_data(client.data_to_send())
        await conn.receive_data()
        assert await asyncio.wait_for(waiter, timeout=1) == -1

    @pytest.mark.asyncio
    async def test_eof_wakes_a_window_waiter(self):
        conn, client, reader, writer = await self._open_get(timeout=5)
        waiter = asyncio.get_running_loop().create_task(
            conn._wait_for_flow_control_window(1))
        await asyncio.sleep(0.01)
        reader.set_eof()
        await conn.receive_data()
        assert await asyncio.wait_for(waiter, timeout=1) == -1

    @pytest.mark.asyncio
    async def test_timeout_zero_waits_for_credit(self):
        conn, client, reader, writer = await self._open_get(timeout=0)
        waiter = asyncio.get_running_loop().create_task(
            conn._wait_for_flow_control_window(1))
        await asyncio.sleep(0.3)
        assert not waiter.done()
        client.increment_flow_control_window(100, stream_id=1)
        reader.set_data(client.data_to_send())
        await conn.receive_data()
        assert await asyncio.wait_for(waiter, timeout=1) == 100


class TestAsyncErrorAfterHeaders:
    """An error once headers went out resets the stream; HPACK stays intact."""

    async def _served_get(self):
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(MockConfig(), reader, writer, ('127.0.0.1', 12345))
        await conn.initiate_connection()
        client = create_client_connection()
        reader.set_data(client.data_to_send())
        await conn.receive_data()
        client.receive_data(writer.get_written_data())
        client.send_headers(1, [
            (':method', 'GET'), (':path', '/'),
            (':scheme', 'https'), (':authority', 'localhost'),
        ], end_stream=True)
        reader.set_data(client.data_to_send())
        await conn.receive_data()
        writer.clear()
        return conn, client, reader, writer

    @pytest.mark.asyncio
    async def test_send_error_after_headers_resets_with_internal_error(self):
        conn, client, reader, writer = await self._served_get()
        assert await conn.send_response_headers(1, [(':status', '200')]) is True
        assert await conn.send_response_headers(1, [(':status', '500')]) is False
        table = len(conn.h2_conn.encoder.header_table.dynamic_entries)
        writer.clear()

        await conn.send_error(1, 500, "boom")

        events = client.receive_data(writer.get_written_data())
        assert not [e for e in events if isinstance(e, h2.events.ResponseReceived)]
        resets = [e for e in events if isinstance(e, h2.events.StreamReset)]
        assert [r.error_code for r in resets] == [h2.errors.ErrorCodes.INTERNAL_ERROR]
        assert len(conn.h2_conn.encoder.header_table.dynamic_entries) == table
        assert 1 not in conn.streams


class TestAsyncEmptyFinalChunk:
    """send_data(b"", end_stream=True) must put END_STREAM on the wire."""

    async def _served_get(self):
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(MockConfig(), reader, writer, ('127.0.0.1', 12345))
        await conn.initiate_connection()
        client = create_client_connection()
        reader.set_data(client.data_to_send())
        await conn.receive_data()
        client.receive_data(writer.get_written_data())
        client.send_headers(1, [
            (':method', 'GET'), (':path', '/'),
            (':scheme', 'https'), (':authority', 'localhost'),
        ], end_stream=True)
        reader.set_data(client.data_to_send())
        await conn.receive_data()
        writer.clear()
        return conn, client, reader, writer

    @pytest.mark.asyncio
    async def test_empty_final_chunk_ends_the_stream(self):
        conn, client, reader, writer = await self._served_get()
        assert await conn.send_response_headers(1, [(':status', '200')]) is True
        assert await conn.send_data(1, b"part", end_stream=False) is True
        assert await conn.send_data(1, b"", end_stream=True) is True
        events = client.receive_data(writer.get_written_data())
        kinds = [type(e).__name__ for e in events]
        assert kinds == ["ResponseReceived", "DataReceived", "DataReceived", "StreamEnded"]
        assert conn.streams[1].response_complete is True

    @pytest.mark.asyncio
    async def test_empty_chunk_without_end_stream_sends_nothing(self):
        conn, client, reader, writer = await self._served_get()
        assert await conn.send_response_headers(1, [(':status', '200')]) is True
        writer.clear()
        assert await conn.send_data(1, b"", end_stream=False) is True
        assert writer.get_written_data() == b""


class TestWriteDrain:
    """The drain is bounded and does not hold the connection write lock."""

    class _Timeout:
        """The real config with cfg.timeout overridden, floats included."""

        def __init__(self, cfg, timeout):
            self._cfg = cfg
            self.timeout = timeout

        def __getattr__(self, name):
            return getattr(self._cfg, name)

    async def _conn(self, writer, timeout=30):
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = MockAsyncReader()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))
        await conn.initiate_connection()
        client = create_client_connection()
        reader.set_data(client.data_to_send())
        await conn.receive_data()
        client.receive_data(writer.get_written_data())
        client.send_headers(1, [
            (':method', 'GET'), (':path', '/'),
            (':scheme', 'https'), (':authority', 'localhost'),
        ], end_stream=True)
        reader.set_data(client.data_to_send())
        await conn.receive_data()
        writer.clear()
        conn.cfg = self._Timeout(conn.cfg, timeout)
        return conn, client, reader

    @pytest.mark.asyncio
    async def test_a_stalled_drain_does_not_hold_the_lock(self):
        """The receive loop keeps running while a stream waits on the transport."""

        class BlockingWriter(MockAsyncWriter):
            def __init__(self):
                super().__init__()
                self.release = asyncio.Event()
                self.blocking = False

            async def drain(self):
                if self.blocking:
                    await self.release.wait()

        writer = BlockingWriter()
        conn, client, reader = await self._conn(writer)
        assert await conn.send_response_headers(1, [(':status', '200')]) is True

        writer.blocking = True
        sender = asyncio.get_running_loop().create_task(
            conn.send_data(1, b"payload", end_stream=True))
        await asyncio.sleep(0.02)
        assert not sender.done()

        # The write lock is free while the sender waits on the transport,
        # so the receive loop and the other streams are not held hostage.
        assert not conn._lock().locked()

        async def take_lock():
            async with conn._lock():
                return True

        assert await asyncio.wait_for(take_lock(), timeout=1) is True

        writer.release.set()
        assert await asyncio.wait_for(sender, timeout=1) is True

    @pytest.mark.asyncio
    async def test_the_receive_loop_runs_while_a_drain_is_stalled(self):
        """Bodies, resets and window updates keep flowing for other streams."""

        class BlockingWriter(MockAsyncWriter):
            def __init__(self):
                super().__init__()
                self.release = asyncio.Event()
                self.blocking = False

            async def drain(self):
                if self.blocking:
                    await self.release.wait()

        writer = BlockingWriter()
        conn, client, reader = await self._conn(writer)
        assert await conn.send_response_headers(1, [(':status', '200')]) is True

        writer.blocking = True
        sender = asyncio.get_running_loop().create_task(
            conn.send_data(1, b"payload", end_stream=True))
        await asyncio.sleep(0.02)
        assert not sender.done()

        # A new request and a PING arrive while the sender waits
        client.send_headers(3, [
            (':method', 'POST'), (':path', '/other'),
            (':scheme', 'https'), (':authority', 'localhost'),
        ], end_stream=False)
        client.send_data(3, b"body", end_stream=True)
        client.ping(b"12345678")
        reader.set_data(client.data_to_send())

        requests = await asyncio.wait_for(conn.receive_data(), timeout=1)
        assert [r.stream.stream_id for r in requests] == [3]
        assert await asyncio.wait_for(requests[0].stream.read_body_chunk(), 1) == b"body"

        writer.release.set()
        assert await asyncio.wait_for(sender, timeout=1) is True

    @pytest.mark.asyncio
    async def test_nothing_to_write_does_not_wait_on_the_transport(self):
        """A flush with no bytes queued must not touch a stalled transport."""

        class CountingWriter(MockAsyncWriter):
            drains = 0

            async def drain(self):
                type(self).drains += 1

        writer = CountingWriter()
        conn, client, reader = await self._conn(writer)
        CountingWriter.drains = 0
        await conn._send_pending_data()      # h2 has nothing queued
        assert CountingWriter.drains == 0

    @pytest.mark.asyncio
    async def test_a_peer_that_never_reads_is_dropped_after_timeout(self):
        from gunicorn.http2.errors import HTTP2ConnectionError

        class DeafWriter(MockAsyncWriter):
            blocking = False

            async def drain(self):
                if self.blocking:
                    await asyncio.Event().wait()   # never resumes

        writer = DeafWriter()
        conn, client, reader = await self._conn(writer, timeout=0.2)
        writer.blocking = True
        with pytest.raises(HTTP2ConnectionError):
            await conn.send_response_headers(1, [(':status', '200')])
        assert conn.is_closed is True
        assert conn.streams[1].disconnected is True

    @pytest.mark.asyncio
    async def test_timeout_zero_waits_for_the_transport(self):
        class SlowWriter(MockAsyncWriter):
            def __init__(self):
                super().__init__()
                self.release = asyncio.Event()

            async def drain(self):
                await self.release.wait()

        writer = SlowWriter()
        writer.release.set()          # transport keeps up during setup
        conn, client, reader = await self._conn(writer, timeout=0)
        writer.release.clear()
        sender = asyncio.get_running_loop().create_task(
            conn.send_response_headers(1, [(':status', '200')]))
        await asyncio.sleep(0.3)
        assert not sender.done()
        writer.release.set()
        assert await asyncio.wait_for(sender, timeout=1) is True
