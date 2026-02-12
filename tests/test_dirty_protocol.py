#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for dirty worker binary protocol module."""

import asyncio
import os
import socket
import struct
import pytest

from gunicorn.dirty.protocol import (
    BinaryProtocol,
    DirtyProtocol,
    make_request,
    make_response,
    make_error_response,
    make_chunk_message,
    make_end_message,
    MAGIC,
    VERSION,
    HEADER_SIZE,
    HEADER_FORMAT,
    MSG_TYPE_REQUEST,
    MSG_TYPE_RESPONSE,
    MSG_TYPE_ERROR,
    MSG_TYPE_CHUNK,
    MSG_TYPE_END,
    MAX_MESSAGE_SIZE,
)
from gunicorn.dirty.errors import (
    DirtyError,
    DirtyProtocolError,
    DirtyTimeoutError,
    DirtyAppError,
)


class TestBinaryProtocolHeader:
    """Tests for header encoding/decoding."""

    def test_header_size(self):
        """Test header size is 16 bytes."""
        assert HEADER_SIZE == 16

    def test_encode_header(self):
        """Test header encoding."""
        header = BinaryProtocol.encode_header(MSG_TYPE_REQUEST, 12345, 100)
        assert len(header) == HEADER_SIZE
        assert header[:2] == MAGIC
        assert header[2] == VERSION
        assert header[3] == MSG_TYPE_REQUEST

    def test_decode_header(self):
        """Test header decoding."""
        header = BinaryProtocol.encode_header(MSG_TYPE_RESPONSE, 67890, 200)
        msg_type, request_id, length = BinaryProtocol.decode_header(header)
        assert msg_type == MSG_TYPE_RESPONSE
        assert request_id == 67890
        assert length == 200

    def test_decode_header_invalid_magic(self):
        """Test header decoding with invalid magic."""
        header = b"XX" + b"\x01\x01" + b"\x00" * 12
        with pytest.raises(DirtyProtocolError) as exc_info:
            BinaryProtocol.decode_header(header)
        assert "magic" in str(exc_info.value).lower()

    def test_decode_header_invalid_version(self):
        """Test header decoding with invalid version."""
        header = MAGIC + b"\x99\x01" + b"\x00" * 12
        with pytest.raises(DirtyProtocolError) as exc_info:
            BinaryProtocol.decode_header(header)
        assert "version" in str(exc_info.value).lower()

    def test_decode_header_invalid_type(self):
        """Test header decoding with invalid message type."""
        header = MAGIC + bytes([VERSION, 0xFF]) + b"\x00" * 12
        with pytest.raises(DirtyProtocolError) as exc_info:
            BinaryProtocol.decode_header(header)
        assert "type" in str(exc_info.value).lower()

    def test_decode_header_too_large(self):
        """Test header decoding rejects too-large messages."""
        header = struct.pack(HEADER_FORMAT, MAGIC, VERSION, MSG_TYPE_REQUEST,
                             MAX_MESSAGE_SIZE + 1, 0)
        with pytest.raises(DirtyProtocolError) as exc_info:
            BinaryProtocol.decode_header(header)
        assert "too large" in str(exc_info.value).lower()

    def test_decode_header_too_short(self):
        """Test header decoding with too-short data."""
        header = MAGIC + b"\x01"
        with pytest.raises(DirtyProtocolError) as exc_info:
            BinaryProtocol.decode_header(header)
        assert "short" in str(exc_info.value).lower()


class TestBinaryProtocolEncodeDecode:
    """Tests for message encoding/decoding."""

    def test_encode_decode_request(self):
        """Test request encoding/decoding roundtrip."""
        encoded = BinaryProtocol.encode_request(
            request_id=12345,
            app_path="myapp.ml:MLApp",
            action="predict",
            args=("data",),
            kwargs={"temperature": 0.7}
        )
        assert len(encoded) > HEADER_SIZE

        msg_type_str, request_id, payload = BinaryProtocol.decode_message(encoded)
        assert msg_type_str == "request"
        assert request_id == 12345
        assert payload["app_path"] == "myapp.ml:MLApp"
        assert payload["action"] == "predict"
        assert payload["args"] == ["data"]
        assert payload["kwargs"] == {"temperature": 0.7}

    def test_encode_decode_response(self):
        """Test response encoding/decoding roundtrip."""
        result = {"predictions": [0.1, 0.9], "metadata": {"model": "v1"}}
        encoded = BinaryProtocol.encode_response(request_id=67890, result=result)

        msg_type_str, request_id, payload = BinaryProtocol.decode_message(encoded)
        assert msg_type_str == "response"
        assert request_id == 67890
        assert payload["result"] == result

    def test_encode_decode_error(self):
        """Test error encoding/decoding roundtrip."""
        error = DirtyTimeoutError("Timed out", timeout=30)
        encoded = BinaryProtocol.encode_error(request_id=11111, error=error)

        msg_type_str, request_id, payload = BinaryProtocol.decode_message(encoded)
        assert msg_type_str == "error"
        assert request_id == 11111
        assert payload["error"]["error_type"] == "DirtyTimeoutError"
        assert "Timed out" in payload["error"]["message"]

    def test_encode_decode_chunk(self):
        """Test chunk encoding/decoding roundtrip."""
        chunk_data = {"token": "hello", "index": 5}
        encoded = BinaryProtocol.encode_chunk(request_id=22222, data=chunk_data)

        msg_type_str, request_id, payload = BinaryProtocol.decode_message(encoded)
        assert msg_type_str == "chunk"
        assert request_id == 22222
        assert payload["data"] == chunk_data

    def test_encode_decode_end(self):
        """Test end message encoding/decoding roundtrip."""
        encoded = BinaryProtocol.encode_end(request_id=33333)
        assert len(encoded) == HEADER_SIZE  # End has no payload

        msg_type_str, request_id, payload = BinaryProtocol.decode_message(encoded)
        assert msg_type_str == "end"
        assert request_id == 33333
        assert payload == {}

    def test_encode_decode_binary_data(self):
        """Test binary data passes through without base64 encoding."""
        binary_data = bytes(range(256))
        encoded = BinaryProtocol.encode_response(
            request_id=44444,
            result={"data": binary_data}
        )

        msg_type_str, request_id, payload = BinaryProtocol.decode_message(encoded)
        assert payload["result"]["data"] == binary_data

    def test_encode_decode_large_message(self):
        """Test encoding a large message."""
        large_data = b"x" * (1024 * 1024)  # 1 MB
        encoded = BinaryProtocol.encode_response(
            request_id=55555,
            result={"data": large_data}
        )

        msg_type_str, request_id, payload = BinaryProtocol.decode_message(encoded)
        assert payload["result"]["data"] == large_data


class TestBinaryProtocolSync:
    """Tests for synchronous socket operations."""

    def test_read_write_message(self):
        """Test read/write through socket pair."""
        server_sock, client_sock = socket.socketpair()
        try:
            message = make_request(
                request_id=12345,
                app_path="test:App",
                action="run"
            )

            BinaryProtocol.write_message(client_sock, message)
            received = BinaryProtocol.read_message(server_sock)

            assert received["type"] == "request"
            assert received["id"] == hash("12345") & 0xFFFFFFFFFFFFFFFF or \
                   received["id"] == 12345
            assert received["app_path"] == "test:App"
            assert received["action"] == "run"
        finally:
            server_sock.close()
            client_sock.close()

    def test_read_write_with_int_id(self):
        """Test read/write with integer request ID."""
        server_sock, client_sock = socket.socketpair()
        try:
            message = {
                "type": "request",
                "id": 999888777,
                "app_path": "test:App",
                "action": "run",
                "args": [],
                "kwargs": {}
            }

            BinaryProtocol.write_message(client_sock, message)
            received = BinaryProtocol.read_message(server_sock)

            assert received["id"] == 999888777
        finally:
            server_sock.close()
            client_sock.close()

    def test_multiple_messages(self):
        """Test sending multiple messages."""
        server_sock, client_sock = socket.socketpair()
        try:
            messages = [
                make_request(i, f"app{i}:App", f"action{i}")
                for i in range(1, 4)
            ]

            for msg in messages:
                BinaryProtocol.write_message(client_sock, msg)

            for i, _ in enumerate(messages, 1):
                received = BinaryProtocol.read_message(server_sock)
                assert received["app_path"] == f"app{i}:App"
                assert received["action"] == f"action{i}"
        finally:
            server_sock.close()
            client_sock.close()

    def test_read_connection_closed(self):
        """Test reading from closed connection."""
        server_sock, client_sock = socket.socketpair()
        client_sock.close()
        with pytest.raises(DirtyProtocolError) as exc_info:
            BinaryProtocol.read_message(server_sock)
        assert "closed" in str(exc_info.value).lower()
        server_sock.close()

    def test_binary_data_roundtrip(self):
        """Test binary data roundtrip through socket."""
        server_sock, client_sock = socket.socketpair()
        try:
            binary_payload = b"\x00\x01\x02\xff\xfe\xfd"
            message = make_response(12345, {"binary": binary_payload})

            BinaryProtocol.write_message(client_sock, message)
            received = BinaryProtocol.read_message(server_sock)

            assert received["result"]["binary"] == binary_payload
        finally:
            server_sock.close()
            client_sock.close()


class TestBinaryProtocolAsync:
    """Tests for async stream operations."""

    @pytest.mark.asyncio
    async def test_async_read_write(self):
        """Test async read/write with mock streams."""
        message = make_request(12345, "test:App", "run")

        read_fd, write_fd = os.pipe()
        try:
            reader = asyncio.StreamReader()
            _ = asyncio.StreamReaderProtocol(reader)

            encoded = BinaryProtocol._encode_from_dict(message)
            os.write(write_fd, encoded)
            os.close(write_fd)
            write_fd = None

            data = os.read(read_fd, len(encoded))
            reader.feed_data(data)
            reader.feed_eof()

            received = await BinaryProtocol.read_message_async(reader)
            assert received["type"] == "request"
            assert received["app_path"] == "test:App"
        finally:
            if write_fd is not None:
                os.close(write_fd)
            os.close(read_fd)

    @pytest.mark.asyncio
    async def test_async_read_incomplete_header(self):
        """Test async read with incomplete header."""
        reader = asyncio.StreamReader()
        reader.feed_data(MAGIC + b"\x01")  # Only 3 bytes
        reader.feed_eof()

        with pytest.raises((asyncio.IncompleteReadError, DirtyProtocolError)):
            await BinaryProtocol.read_message_async(reader)

    @pytest.mark.asyncio
    async def test_async_read_empty_connection(self):
        """Test async read on empty connection."""
        reader = asyncio.StreamReader()
        reader.feed_eof()

        with pytest.raises(asyncio.IncompleteReadError):
            await BinaryProtocol.read_message_async(reader)

    @pytest.mark.asyncio
    async def test_async_read_invalid_magic(self):
        """Test async read rejects invalid magic."""
        reader = asyncio.StreamReader()
        header = b"XX" + bytes([VERSION, MSG_TYPE_REQUEST]) + b"\x00" * 12
        reader.feed_data(header)
        reader.feed_eof()

        with pytest.raises(DirtyProtocolError) as exc_info:
            await BinaryProtocol.read_message_async(reader)
        assert "magic" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_async_read_message_too_large(self):
        """Test async read rejects too-large messages."""
        reader = asyncio.StreamReader()
        header = struct.pack(HEADER_FORMAT, MAGIC, VERSION, MSG_TYPE_REQUEST,
                             MAX_MESSAGE_SIZE + 1000, 0)
        reader.feed_data(header)
        reader.feed_eof()

        with pytest.raises(DirtyProtocolError) as exc_info:
            await BinaryProtocol.read_message_async(reader)
        assert "too large" in str(exc_info.value)


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

    def test_make_chunk_message(self):
        """Test chunk message builder."""
        chunk = make_chunk_message("req-123", "Hello, ")
        assert chunk["type"] == DirtyProtocol.MSG_TYPE_CHUNK
        assert chunk["id"] == "req-123"
        assert chunk["data"] == "Hello, "

    def test_make_chunk_message_with_complex_data(self):
        """Test chunk message with complex data."""
        data = {"token": "world", "score": 0.95, "index": 5}
        chunk = make_chunk_message("req-456", data)
        assert chunk["type"] == DirtyProtocol.MSG_TYPE_CHUNK
        assert chunk["id"] == "req-456"
        assert chunk["data"] == data

    def test_make_chunk_message_with_binary_data(self):
        """Test chunk message with binary data."""
        data = b"\x00\x01\x02\xff"
        chunk = make_chunk_message("req-789", data)
        assert chunk["data"] == data

    def test_make_end_message(self):
        """Test end message builder."""
        end = make_end_message("req-123")
        assert end["type"] == DirtyProtocol.MSG_TYPE_END
        assert end["id"] == "req-123"
        assert "data" not in end

    def test_chunk_and_end_roundtrip(self):
        """Test that chunk and end messages can be encoded/decoded."""
        chunk = make_chunk_message(12345, {"token": "hello"})
        end = make_end_message(12345)

        # Test chunk roundtrip
        encoded_chunk = BinaryProtocol._encode_from_dict(chunk)
        msg_type, req_id, payload = BinaryProtocol.decode_message(encoded_chunk)
        assert msg_type == "chunk"
        assert payload["data"] == {"token": "hello"}

        # Test end roundtrip
        encoded_end = BinaryProtocol._encode_from_dict(end)
        msg_type, req_id, payload = BinaryProtocol.decode_message(encoded_end)
        assert msg_type == "end"
        assert payload == {}


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


class TestBackwardsCompatibility:
    """Tests for backwards compatibility with old JSON API."""

    def test_dirty_protocol_alias(self):
        """Test that DirtyProtocol is an alias for BinaryProtocol."""
        assert DirtyProtocol is BinaryProtocol

    def test_header_size_attribute(self):
        """Test HEADER_SIZE is accessible on class."""
        assert DirtyProtocol.HEADER_SIZE == 16

    def test_msg_type_constants(self):
        """Test message type constants are strings for compatibility."""
        assert DirtyProtocol.MSG_TYPE_REQUEST == "request"
        assert DirtyProtocol.MSG_TYPE_RESPONSE == "response"
        assert DirtyProtocol.MSG_TYPE_ERROR == "error"
        assert DirtyProtocol.MSG_TYPE_CHUNK == "chunk"
        assert DirtyProtocol.MSG_TYPE_END == "end"

    def test_encode_decode_preserves_dict_format(self):
        """Test that read_message returns dict compatible with old API."""
        server_sock, client_sock = socket.socketpair()
        try:
            message = {
                "type": "response",
                "id": 12345,
                "result": {"status": "ok"}
            }

            DirtyProtocol.write_message(client_sock, message)
            received = DirtyProtocol.read_message(server_sock)

            # Old API: access via dict keys
            assert received["type"] == "response"
            assert received["result"]["status"] == "ok"
        finally:
            server_sock.close()
            client_sock.close()

    def test_string_request_id_handled(self):
        """Test that string request IDs are handled (hashed to int)."""
        server_sock, client_sock = socket.socketpair()
        try:
            message = make_request("uuid-string-id", "test:App", "run")

            DirtyProtocol.write_message(client_sock, message)
            received = DirtyProtocol.read_message(server_sock)

            # Request ID should be converted to int
            assert isinstance(received["id"], int)
        finally:
            server_sock.close()
            client_sock.close()
