# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for async HTTP/2 server connection."""

import asyncio
import pytest
from unittest import mock
from io import BytesIO

# Check if h2 is available for integration tests
try:
    import h2.connection
    import h2.config
    import h2.events
    H2_AVAILABLE = True
except ImportError:
    H2_AVAILABLE = False

from gunicorn.http2.errors import (
    HTTP2Error, HTTP2ProtocolError, HTTP2ConnectionError
)


pytestmark = pytest.mark.skipif(not H2_AVAILABLE, reason="h2 library not available")


class MockConfig:
    """Mock gunicorn configuration for HTTP/2."""

    def __init__(self):
        self.http2_max_concurrent_streams = 100
        self.http2_initial_window_size = 65535
        self.http2_max_frame_size = 16384
        self.http2_max_header_list_size = 65536


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
        cfg.http2_max_concurrent_streams = 50

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
        from gunicorn.http2.async_connection import AsyncHTTP2Connection

        cfg = MockConfig()
        reader = MockAsyncReader()
        writer = MockAsyncWriter()
        conn = AsyncHTTP2Connection(cfg, reader, writer, ('127.0.0.1', 12345))
        await conn.initiate_connection()

        with pytest.raises(HTTP2Error):
            await conn.send_response(stream_id=999, status=200, headers=[], body=None)


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
