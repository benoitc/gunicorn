#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for control socket protocol."""

import json
import struct
import pytest

from gunicorn.ctl.protocol import (
    ControlProtocol,
    ProtocolError,
    make_request,
    make_response,
    make_error_response,
)


class TestControlProtocolEncoding:
    """Tests for message encoding/decoding."""

    def test_encode_message_simple(self):
        """Test encoding a simple message."""
        data = {"command": "test"}
        result = ControlProtocol.encode_message(data)

        # First 4 bytes are length
        length = struct.unpack('>I', result[:4])[0]
        payload = result[4:]

        assert length == len(payload)
        assert json.loads(payload.decode('utf-8')) == data

    def test_encode_message_unicode(self):
        """Test encoding message with unicode characters."""
        data = {"message": "Hello \u4e16\u754c"}
        result = ControlProtocol.encode_message(data)

        length = struct.unpack('>I', result[:4])[0]
        payload = result[4:]

        assert length == len(payload)
        assert json.loads(payload.decode('utf-8')) == data

    def test_decode_message_simple(self):
        """Test decoding a simple message."""
        data = {"command": "test", "args": [1, 2, 3]}
        payload = json.dumps(data).encode('utf-8')
        length = struct.pack('>I', len(payload))
        raw = length + payload

        result = ControlProtocol.decode_message(raw)
        assert result == data

    def test_decode_message_too_short(self):
        """Test decoding message that's too short."""
        with pytest.raises(ProtocolError) as exc_info:
            ControlProtocol.decode_message(b'\x00\x00')
        assert "too short" in str(exc_info.value)

    def test_decode_message_incomplete(self):
        """Test decoding incomplete message."""
        # Length says 100 bytes but only 4 bytes provided
        raw = struct.pack('>I', 100) + b'test'
        with pytest.raises(ProtocolError) as exc_info:
            ControlProtocol.decode_message(raw)
        assert "Incomplete" in str(exc_info.value)

    def test_roundtrip(self):
        """Test encode/decode roundtrip."""
        original = {
            "id": 42,
            "command": "show workers",
            "args": ["arg1", 123, True, None],
            "nested": {"a": 1, "b": [1, 2, 3]},
        }

        encoded = ControlProtocol.encode_message(original)
        decoded = ControlProtocol.decode_message(encoded)

        assert decoded == original


class TestMakeRequest:
    """Tests for request creation."""

    def test_make_request_simple(self):
        """Test creating a simple request."""
        result = make_request(1, "show workers")

        assert result["id"] == 1
        assert result["command"] == "show workers"
        assert result["args"] == []

    def test_make_request_with_args(self):
        """Test creating a request with arguments."""
        result = make_request(42, "worker add", [2])

        assert result["id"] == 42
        assert result["command"] == "worker add"
        assert result["args"] == [2]


class TestMakeResponse:
    """Tests for response creation."""

    def test_make_response_simple(self):
        """Test creating a simple response."""
        result = make_response(1, {"count": 5})

        assert result["id"] == 1
        assert result["status"] == "ok"
        assert result["data"] == {"count": 5}

    def test_make_response_empty_data(self):
        """Test creating response with no data."""
        result = make_response(1)

        assert result["id"] == 1
        assert result["status"] == "ok"
        assert result["data"] == {}


class TestMakeErrorResponse:
    """Tests for error response creation."""

    def test_make_error_response(self):
        """Test creating an error response."""
        result = make_error_response(1, "Unknown command")

        assert result["id"] == 1
        assert result["status"] == "error"
        assert result["error"] == "Unknown command"


class TestControlProtocolSocket:
    """Tests for socket reading/writing."""

    def test_read_write_message(self):
        """Test read/write through socket pair."""
        import socket
        import threading

        data = {"id": 1, "command": "test"}
        received = []

        # Create socket pair
        server, client = socket.socketpair()

        def reader():
            received.append(ControlProtocol.read_message(server))

        t = threading.Thread(target=reader)
        t.start()

        ControlProtocol.write_message(client, data)
        t.join(timeout=2.0)

        client.close()
        server.close()

        assert len(received) == 1
        assert received[0] == data

    def test_read_connection_closed(self):
        """Test reading from closed connection."""
        import socket

        server, client = socket.socketpair()
        client.close()

        with pytest.raises(ConnectionError):
            ControlProtocol.read_message(server)

        server.close()

    def test_read_message_too_large(self):
        """Test reading message exceeding max size."""
        import socket

        server, client = socket.socketpair()

        # Send a length that exceeds MAX_MESSAGE_SIZE
        huge_length = ControlProtocol.MAX_MESSAGE_SIZE + 1
        client.send(struct.pack('>I', huge_length))

        with pytest.raises(ProtocolError) as exc_info:
            ControlProtocol.read_message(server)
        assert "too large" in str(exc_info.value)

        client.close()
        server.close()


class TestControlProtocolAsync:
    """Tests for async protocol methods."""

    @pytest.mark.asyncio
    async def test_async_read_write(self):
        """Test async read/write using a unix server."""
        import asyncio
        import tempfile
        import os

        data = {"id": 1, "command": "async test"}
        received = []

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "test.sock")

            async def handler(reader, writer):
                msg = await ControlProtocol.read_message_async(reader)
                received.append(msg)
                await ControlProtocol.write_message_async(writer, data)
                writer.close()
                await writer.wait_closed()

            server = await asyncio.start_unix_server(handler, path=socket_path)

            async with server:
                reader, writer = await asyncio.open_unix_connection(socket_path)
                await ControlProtocol.write_message_async(writer, data)
                response = await ControlProtocol.read_message_async(reader)
                writer.close()
                await writer.wait_closed()

            assert len(received) == 1
            assert received[0] == data
            assert response == data


class TestProtocolMaxSize:
    """Tests for protocol size limits."""

    def test_max_message_size_constant(self):
        """Test that MAX_MESSAGE_SIZE is set to a reasonable value."""
        # Should be 16 MB
        assert ControlProtocol.MAX_MESSAGE_SIZE == 16 * 1024 * 1024

    def test_encode_large_message(self):
        """Test encoding a large (but valid) message."""
        # Create a message with ~1MB of data
        data = {"data": "x" * (1024 * 1024)}
        encoded = ControlProtocol.encode_message(data)

        # Should succeed and be decodable
        decoded = ControlProtocol.decode_message(encoded)
        assert decoded == data
