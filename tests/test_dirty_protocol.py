#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for dirty arbiter protocol module."""

import asyncio
import os
import socket
import struct
import pytest

from gunicorn.dirty.protocol import (
    DirtyProtocol,
    make_request,
    make_response,
    make_error_response,
)
from gunicorn.dirty.errors import (
    DirtyError,
    DirtyProtocolError,
    DirtyTimeoutError,
    DirtyAppError,
)


class TestDirtyProtocolEncodeDecode:
    """Tests for encode/decode functionality."""

    def test_encode_decode_roundtrip(self):
        """Test basic encode/decode roundtrip."""
        message = {"type": "request", "id": "123", "data": "hello"}
        encoded = DirtyProtocol.encode(message)

        # Check header format
        assert len(encoded) > DirtyProtocol.HEADER_SIZE
        length = struct.unpack(
            DirtyProtocol.HEADER_FORMAT,
            encoded[:DirtyProtocol.HEADER_SIZE]
        )[0]
        assert length == len(encoded) - DirtyProtocol.HEADER_SIZE

        # Decode payload
        payload = encoded[DirtyProtocol.HEADER_SIZE:]
        decoded = DirtyProtocol.decode(payload)
        assert decoded == message

    def test_encode_decode_complex_data(self):
        """Test with complex nested data structures."""
        message = {
            "type": "response",
            "id": "456",
            "result": {
                "models": ["gpt-4", "claude-3"],
                "config": {"temperature": 0.7, "max_tokens": 1000},
                "metadata": None,
            },
            "args": [1, 2, 3],
        }
        encoded = DirtyProtocol.encode(message)
        payload = encoded[DirtyProtocol.HEADER_SIZE:]
        decoded = DirtyProtocol.decode(payload)
        assert decoded == message

    def test_encode_decode_unicode(self):
        """Test with unicode characters."""
        message = {
            "type": "request",
            "data": "Hello, world!"
        }
        encoded = DirtyProtocol.encode(message)
        payload = encoded[DirtyProtocol.HEADER_SIZE:]
        decoded = DirtyProtocol.decode(payload)
        assert decoded == message

    def test_encode_large_message(self):
        """Test encoding a large message."""
        large_data = "x" * (1024 * 1024)  # 1 MB of data
        message = {"type": "request", "data": large_data}
        encoded = DirtyProtocol.encode(message)
        payload = encoded[DirtyProtocol.HEADER_SIZE:]
        decoded = DirtyProtocol.decode(payload)
        assert decoded == message

    def test_encode_empty_dict(self):
        """Test encoding an empty dictionary."""
        message = {}
        encoded = DirtyProtocol.encode(message)
        payload = encoded[DirtyProtocol.HEADER_SIZE:]
        decoded = DirtyProtocol.decode(payload)
        assert decoded == message

    def test_encode_message_too_large(self):
        """Test that encoding a message that's too large raises error."""
        large_data = "x" * (DirtyProtocol.MAX_MESSAGE_SIZE + 1000)
        message = {"data": large_data}
        with pytest.raises(DirtyProtocolError) as exc_info:
            DirtyProtocol.encode(message)
        assert "too large" in str(exc_info.value)

    def test_encode_non_serializable(self):
        """Test that encoding non-JSON-serializable data raises error."""
        message = {"func": lambda x: x}
        with pytest.raises(DirtyProtocolError) as exc_info:
            DirtyProtocol.encode(message)
        assert "Failed to encode" in str(exc_info.value)

    def test_decode_invalid_json(self):
        """Test decoding invalid JSON raises error."""
        invalid_data = b"not valid json"
        with pytest.raises(DirtyProtocolError) as exc_info:
            DirtyProtocol.decode(invalid_data)
        assert "Failed to decode" in str(exc_info.value)

    def test_decode_invalid_unicode(self):
        """Test decoding invalid unicode raises error."""
        invalid_data = b"\x80\x81\x82"
        with pytest.raises(DirtyProtocolError) as exc_info:
            DirtyProtocol.decode(invalid_data)
        assert "Failed to decode" in str(exc_info.value)


class TestDirtyProtocolSync:
    """Tests for synchronous socket operations."""

    def test_read_write_message(self):
        """Test read/write through socket pair."""
        # Create a socket pair for testing
        server_sock, client_sock = socket.socketpair()
        try:
            message = {"type": "request", "id": "123", "action": "test"}

            # Write message
            DirtyProtocol.write_message(client_sock, message)

            # Read message
            received = DirtyProtocol.read_message(server_sock)
            assert received == message
        finally:
            server_sock.close()
            client_sock.close()

    def test_multiple_messages(self):
        """Test sending multiple messages."""
        server_sock, client_sock = socket.socketpair()
        try:
            messages = [
                {"type": "request", "id": "1"},
                {"type": "request", "id": "2"},
                {"type": "request", "id": "3"},
            ]

            # Write all messages
            for msg in messages:
                DirtyProtocol.write_message(client_sock, msg)

            # Read all messages
            for expected in messages:
                received = DirtyProtocol.read_message(server_sock)
                assert received == expected
        finally:
            server_sock.close()
            client_sock.close()

    def test_read_connection_closed(self):
        """Test reading from closed connection."""
        server_sock, client_sock = socket.socketpair()
        client_sock.close()
        with pytest.raises(DirtyProtocolError) as exc_info:
            DirtyProtocol.read_message(server_sock)
        assert "closed" in str(exc_info.value).lower()
        server_sock.close()


class TestDirtyProtocolAsync:
    """Tests for async stream operations."""

    @pytest.mark.asyncio
    async def test_async_read_write(self):
        """Test async read/write with mock streams."""
        message = {"type": "request", "id": "123"}

        # Create a pipe for testing
        read_fd, write_fd = os.pipe()
        try:
            reader = asyncio.StreamReader()
            _ = asyncio.StreamReaderProtocol(reader)

            # Write the message to the pipe
            encoded = DirtyProtocol.encode(message)
            os.write(write_fd, encoded)
            os.close(write_fd)
            write_fd = None

            # Feed data to reader
            data = os.read(read_fd, len(encoded))
            reader.feed_data(data)
            reader.feed_eof()

            # Read the message
            received = await DirtyProtocol.read_message_async(reader)
            assert received == message
        finally:
            if write_fd is not None:
                os.close(write_fd)
            os.close(read_fd)

    @pytest.mark.asyncio
    async def test_async_read_incomplete_header(self):
        """Test async read with incomplete header."""
        reader = asyncio.StreamReader()
        # Feed only 2 bytes instead of 4
        reader.feed_data(b"\x00\x00")
        reader.feed_eof()

        with pytest.raises((asyncio.IncompleteReadError, DirtyProtocolError)):
            await DirtyProtocol.read_message_async(reader)

    @pytest.mark.asyncio
    async def test_async_read_empty_connection(self):
        """Test async read on empty connection."""
        reader = asyncio.StreamReader()
        reader.feed_eof()

        with pytest.raises(asyncio.IncompleteReadError):
            await DirtyProtocol.read_message_async(reader)

    @pytest.mark.asyncio
    async def test_async_read_message_too_large(self):
        """Test async read rejects too-large messages."""
        reader = asyncio.StreamReader()
        # Create a header claiming an absurdly large message
        header = struct.pack(
            DirtyProtocol.HEADER_FORMAT,
            DirtyProtocol.MAX_MESSAGE_SIZE + 1000
        )
        reader.feed_data(header)
        reader.feed_eof()

        with pytest.raises(DirtyProtocolError) as exc_info:
            await DirtyProtocol.read_message_async(reader)
        assert "too large" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_async_read_empty_message(self):
        """Test async read rejects empty messages."""
        reader = asyncio.StreamReader()
        header = struct.pack(DirtyProtocol.HEADER_FORMAT, 0)
        reader.feed_data(header)
        reader.feed_eof()

        with pytest.raises(DirtyProtocolError) as exc_info:
            await DirtyProtocol.read_message_async(reader)
        assert "Empty message" in str(exc_info.value)


class TestMessageBuilders:
    """Tests for message builder helper functions."""

    def test_make_request(self):
        """Test request message builder."""
        request = make_request(
            request_id="abc123",
            app_path="myapp.ml:MLApp",
            action="inference",
            args=("model1",),
            kwargs={"temperature": 0.7}
        )
        assert request["type"] == DirtyProtocol.MSG_TYPE_REQUEST
        assert request["id"] == "abc123"
        assert request["app_path"] == "myapp.ml:MLApp"
        assert request["action"] == "inference"
        assert request["args"] == ["model1"]
        assert request["kwargs"] == {"temperature": 0.7}

    def test_make_request_minimal(self):
        """Test request with minimal arguments."""
        request = make_request(
            request_id="abc",
            app_path="app:App",
            action="run"
        )
        assert request["args"] == []
        assert request["kwargs"] == {}

    def test_make_response(self):
        """Test response message builder."""
        response = make_response(
            request_id="abc123",
            result={"status": "ok", "data": [1, 2, 3]}
        )
        assert response["type"] == DirtyProtocol.MSG_TYPE_RESPONSE
        assert response["id"] == "abc123"
        assert response["result"] == {"status": "ok", "data": [1, 2, 3]}

    def test_make_error_response_with_exception(self):
        """Test error response with DirtyError."""
        error = DirtyTimeoutError("Operation timed out", timeout=30)
        response = make_error_response("abc123", error)

        assert response["type"] == DirtyProtocol.MSG_TYPE_ERROR
        assert response["id"] == "abc123"
        assert response["error"]["error_type"] == "DirtyTimeoutError"
        assert response["error"]["message"] == "Operation timed out"
        assert response["error"]["details"]["timeout"] == 30

    def test_make_error_response_with_dict(self):
        """Test error response with dict."""
        error_dict = {
            "error_type": "CustomError",
            "message": "Something went wrong",
            "details": {"code": 500}
        }
        response = make_error_response("abc123", error_dict)

        assert response["error"] == error_dict

    def test_make_error_response_with_generic_exception(self):
        """Test error response with generic exception."""
        error = ValueError("Invalid value")
        response = make_error_response("abc123", error)

        assert response["error"]["error_type"] == "ValueError"
        assert response["error"]["message"] == "Invalid value"


class TestDirtyErrors:
    """Tests for error classes."""

    def test_dirty_error_to_dict(self):
        """Test serializing error to dict."""
        error = DirtyError("Test error", {"key": "value"})
        d = error.to_dict()
        assert d["error_type"] == "DirtyError"
        assert d["message"] == "Test error"
        assert d["details"] == {"key": "value"}

    def test_dirty_error_from_dict(self):
        """Test deserializing error from dict."""
        d = {
            "error_type": "DirtyTimeoutError",
            "message": "Timed out",
            "details": {"timeout": 30}
        }
        error = DirtyError.from_dict(d)
        assert isinstance(error, DirtyTimeoutError)
        assert error.message == "Timed out"
        assert error.details["timeout"] == 30

    def test_dirty_error_from_dict_unknown_type(self):
        """Test deserializing unknown error type falls back to DirtyError."""
        d = {
            "error_type": "UnknownError",
            "message": "Unknown",
            "details": {}
        }
        error = DirtyError.from_dict(d)
        assert isinstance(error, DirtyError)
        assert not isinstance(error, DirtyTimeoutError)

    def test_dirty_app_error(self):
        """Test DirtyAppError fields."""
        error = DirtyAppError(
            "App failed",
            app_path="myapp:App",
            action="run",
            traceback="Traceback..."
        )
        assert error.app_path == "myapp:App"
        assert error.action == "run"
        assert error.traceback == "Traceback..."
        assert "myapp:App" in str(error)
