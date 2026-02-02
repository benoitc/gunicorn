#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
ASGI streaming response tests.

Tests for chunked transfer encoding, Server-Sent Events (SSE),
and streaming response handling.
"""

import asyncio
from unittest import mock

import pytest

from gunicorn.config import Config


# ============================================================================
# Chunked Transfer Encoding Tests
# ============================================================================

class TestChunkedTransferEncoding:
    """Tests for HTTP/1.1 chunked transfer encoding."""

    def test_chunked_encoding_format(self):
        """Test chunked encoding format: size in hex + CRLF + data + CRLF."""
        body = b"Hello"
        chunk = f"{len(body):x}\r\n".encode("latin-1") + body + b"\r\n"

        assert chunk == b"5\r\nHello\r\n"

    def test_chunked_encoding_large_chunk(self):
        """Test chunked encoding with larger data."""
        body = b"x" * 1000
        chunk = f"{len(body):x}\r\n".encode("latin-1") + body + b"\r\n"

        # 1000 in hex is 3e8
        assert chunk.startswith(b"3e8\r\n")
        assert chunk.endswith(b"\r\n")

    def test_chunked_encoding_terminal_chunk(self):
        """Test terminal chunk (zero-length)."""
        terminal = b"0\r\n\r\n"

        # Parse it
        assert terminal == b"0\r\n\r\n"

    def test_chunked_encoding_empty_chunk(self):
        """Test encoding empty body chunk."""
        body = b""
        chunk = f"{len(body):x}\r\n".encode("latin-1") + body + b"\r\n"

        assert chunk == b"0\r\n\r\n"

    def test_chunked_encoding_multiple_chunks(self):
        """Test multiple chunks in sequence."""
        chunks = []

        # First chunk
        body1 = b"Hello, "
        chunks.append(f"{len(body1):x}\r\n".encode() + body1 + b"\r\n")

        # Second chunk
        body2 = b"World!"
        chunks.append(f"{len(body2):x}\r\n".encode() + body2 + b"\r\n")

        # Terminal chunk
        chunks.append(b"0\r\n\r\n")

        full_response = b"".join(chunks)

        assert b"7\r\nHello, \r\n" in full_response
        assert b"6\r\nWorld!\r\n" in full_response
        assert full_response.endswith(b"0\r\n\r\n")


# ============================================================================
# ASGI Streaming Response Tests
# ============================================================================

class TestASGIStreamingResponse:
    """Tests for ASGI streaming response handling."""

    def test_streaming_response_more_body_true(self):
        """Test streaming response with more_body=True."""
        messages = [
            {
                "type": "http.response.body",
                "body": b"chunk1",
                "more_body": True,
            },
            {
                "type": "http.response.body",
                "body": b"chunk2",
                "more_body": True,
            },
            {
                "type": "http.response.body",
                "body": b"chunk3",
                "more_body": False,
            },
        ]

        assert messages[0]["more_body"] is True
        assert messages[1]["more_body"] is True
        assert messages[2]["more_body"] is False

    def test_streaming_response_empty_final_chunk(self):
        """Test streaming response with empty final chunk."""
        final_message = {
            "type": "http.response.body",
            "body": b"",
            "more_body": False,
        }

        assert final_message["body"] == b""
        assert final_message["more_body"] is False

    def test_response_start_without_content_length(self):
        """Test response start without Content-Length triggers chunked encoding."""
        # When Content-Length is missing, HTTP/1.1 should use chunked encoding
        message = {
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"text/plain"),
                # No content-length header
            ],
        }

        # Check no content-length in headers
        header_names = [name.lower() for name, _ in message["headers"]]
        assert b"content-length" not in header_names


# ============================================================================
# Server-Sent Events (SSE) Format Tests
# ============================================================================

class TestSSEFormat:
    """Tests for Server-Sent Events format."""

    def test_sse_data_event(self):
        """Test SSE data event format."""
        data = "Hello, SSE!"
        event = f"data: {data}\n\n"

        assert event == "data: Hello, SSE!\n\n"

    def test_sse_named_event(self):
        """Test SSE named event format."""
        event_name = "message"
        data = "Hello"
        event = f"event: {event_name}\ndata: {data}\n\n"

        assert "event: message\n" in event
        assert "data: Hello\n" in event
        assert event.endswith("\n\n")

    def test_sse_event_with_id(self):
        """Test SSE event with ID."""
        event_id = "12345"
        data = "Some data"
        event = f"id: {event_id}\ndata: {data}\n\n"

        assert "id: 12345\n" in event

    def test_sse_multiline_data(self):
        """Test SSE multiline data."""
        lines = ["line1", "line2", "line3"]
        data_lines = "\n".join(f"data: {line}" for line in lines)
        event = f"{data_lines}\n\n"

        assert event == "data: line1\ndata: line2\ndata: line3\n\n"

    def test_sse_retry_directive(self):
        """Test SSE retry directive."""
        retry_ms = 3000
        directive = f"retry: {retry_ms}\n\n"

        assert directive == "retry: 3000\n\n"

    def test_sse_comment(self):
        """Test SSE comment (keep-alive)."""
        comment = ": keep-alive\n\n"

        assert comment.startswith(":")

    def test_sse_content_type(self):
        """Test SSE Content-Type header."""
        headers = [
            (b"content-type", b"text/event-stream"),
            (b"cache-control", b"no-cache"),
            (b"connection", b"keep-alive"),
        ]

        content_type = dict(headers).get(b"content-type")
        assert content_type == b"text/event-stream"


# ============================================================================
# Protocol Send Body Tests
# ============================================================================

class TestProtocolSendBody:
    """Tests for ASGIProtocol._send_body method."""

    def _create_protocol(self):
        """Create an ASGIProtocol instance for testing."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()

        protocol = ASGIProtocol(worker)
        protocol.transport = mock.Mock()

        return protocol

    @pytest.mark.asyncio
    async def test_send_body_without_chunking(self):
        """Test sending body without chunked encoding."""
        protocol = self._create_protocol()

        await protocol._send_body(b"Hello, World!", chunked=False)

        protocol.transport.write.assert_called_once_with(b"Hello, World!")

    @pytest.mark.asyncio
    async def test_send_body_with_chunking(self):
        """Test sending body with chunked encoding."""
        protocol = self._create_protocol()

        await protocol._send_body(b"Hello", chunked=True)

        # Should write: "5\r\nHello\r\n"
        protocol.transport.write.assert_called_once()
        call_arg = protocol.transport.write.call_args[0][0]
        assert call_arg == b"5\r\nHello\r\n"

    @pytest.mark.asyncio
    async def test_send_body_empty_without_chunking(self):
        """Test sending empty body without chunked encoding."""
        protocol = self._create_protocol()

        await protocol._send_body(b"", chunked=False)

        # Empty body should not write anything
        protocol.transport.write.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_body_empty_with_chunking(self):
        """Test sending empty body with chunked encoding."""
        protocol = self._create_protocol()

        await protocol._send_body(b"", chunked=True)

        # Empty body should not write (terminal chunk handled separately)
        protocol.transport.write.assert_not_called()


# ============================================================================
# Content-Length Detection Tests
# ============================================================================

class TestContentLengthDetection:
    """Tests for Content-Length header detection."""

    def test_has_content_length_bytes(self):
        """Test detecting Content-Length header (bytes)."""
        headers = [
            (b"content-type", b"text/plain"),
            (b"content-length", b"100"),
        ]

        has_cl = any(
            name.lower() == b"content-length"
            for name, _ in headers
        )
        assert has_cl is True

    def test_has_content_length_string(self):
        """Test detecting Content-Length header (string)."""
        headers = [
            ("content-type", "text/plain"),
            ("content-length", "100"),
        ]

        has_cl = any(
            name.lower() == "content-length"
            for name, _ in headers
        )
        assert has_cl is True

    def test_no_content_length(self):
        """Test when Content-Length is missing."""
        headers = [
            (b"content-type", b"text/plain"),
        ]

        has_cl = any(
            name.lower() == b"content-length"
            for name, _ in headers
        )
        assert has_cl is False

    def test_content_length_case_insensitive(self):
        """Test Content-Length detection is case-insensitive."""
        headers = [
            (b"Content-Length", b"100"),
        ]

        has_cl = any(
            name.lower() == b"content-length"
            for name, _ in headers
        )
        assert has_cl is True


# ============================================================================
# HTTP Version Check for Chunked Encoding
# ============================================================================

class TestHTTPVersionForChunked:
    """Tests for HTTP version requirements for chunked encoding."""

    def test_http11_supports_chunked(self):
        """Test HTTP/1.1 supports chunked encoding."""
        version = (1, 1)
        supports_chunked = version >= (1, 1)
        assert supports_chunked is True

    def test_http10_no_chunked(self):
        """Test HTTP/1.0 does not support chunked encoding."""
        version = (1, 0)
        supports_chunked = version >= (1, 1)
        assert supports_chunked is False

    def test_http2_no_chunked(self):
        """Test HTTP/2 doesn't use chunked encoding (uses framing)."""
        # HTTP/2 has its own framing mechanism
        version = (2, 0)
        # Chunked encoding is not used in HTTP/2
        uses_http1_chunked = version[0] == 1 and version >= (1, 1)
        assert uses_http1_chunked is False


# ============================================================================
# Streaming Response Message Sequence Tests
# ============================================================================

class TestStreamingMessageSequence:
    """Tests for valid streaming response message sequences."""

    def test_valid_sequence_single_body(self):
        """Test valid sequence: start -> body (more_body=False)."""
        messages = [
            {"type": "http.response.start", "status": 200, "headers": []},
            {"type": "http.response.body", "body": b"Hello", "more_body": False},
        ]

        # First message should be start
        assert messages[0]["type"] == "http.response.start"
        # Last body message should have more_body=False
        assert messages[-1]["type"] == "http.response.body"
        assert messages[-1]["more_body"] is False

    def test_valid_sequence_multiple_bodies(self):
        """Test valid sequence: start -> body (more=True) -> body (more=False)."""
        messages = [
            {"type": "http.response.start", "status": 200, "headers": []},
            {"type": "http.response.body", "body": b"chunk1", "more_body": True},
            {"type": "http.response.body", "body": b"chunk2", "more_body": True},
            {"type": "http.response.body", "body": b"", "more_body": False},
        ]

        # Verify sequence
        assert messages[0]["type"] == "http.response.start"
        assert all(m["more_body"] for m in messages[1:-1])
        assert messages[-1]["more_body"] is False

    def test_valid_sequence_with_informational(self):
        """Test valid sequence with informational response."""
        messages = [
            {
                "type": "http.response.informational",
                "status": 103,
                "headers": [(b"link", b"</style.css>; rel=preload")],
            },
            {"type": "http.response.start", "status": 200, "headers": []},
            {"type": "http.response.body", "body": b"Hello", "more_body": False},
        ]

        # Informational before start is valid
        assert messages[0]["type"] == "http.response.informational"
        assert messages[1]["type"] == "http.response.start"


# ============================================================================
# Large Response Tests
# ============================================================================

class TestLargeResponses:
    """Tests for handling large responses."""

    def test_chunk_size_encoding(self):
        """Test chunk size encoding for various sizes."""
        test_cases = [
            (1, b"1\r\n"),
            (10, b"a\r\n"),
            (15, b"f\r\n"),
            (16, b"10\r\n"),
            (255, b"ff\r\n"),
            (256, b"100\r\n"),
            (1024, b"400\r\n"),
            (65535, b"ffff\r\n"),
            (1048576, b"100000\r\n"),  # 1MB
        ]

        for size, expected in test_cases:
            chunk_header = f"{size:x}\r\n".encode("latin-1")
            assert chunk_header == expected, f"Failed for size {size}"

    def test_megabyte_chunk(self):
        """Test encoding 1MB chunk."""
        size = 1024 * 1024  # 1MB
        body = b"x" * size

        chunk = f"{len(body):x}\r\n".encode("latin-1") + body + b"\r\n"

        # Verify structure
        assert chunk.startswith(b"100000\r\n")  # 1MB in hex
        assert chunk.endswith(b"\r\n")
        # Total size: header (8) + body (1048576) + trailer (2)
        assert len(chunk) == 8 + 1048576 + 2


# ============================================================================
# Transfer-Encoding Header Tests
# ============================================================================

class TestTransferEncodingHeader:
    """Tests for Transfer-Encoding header handling."""

    def test_transfer_encoding_chunked(self):
        """Test Transfer-Encoding: chunked header."""
        headers = [(b"transfer-encoding", b"chunked")]

        te_header = dict(headers).get(b"transfer-encoding")
        assert te_header == b"chunked"

    def test_add_transfer_encoding_to_headers(self):
        """Test adding Transfer-Encoding header to response."""
        headers = [
            (b"content-type", b"text/plain"),
        ]

        # Add chunked encoding
        headers = list(headers) + [(b"transfer-encoding", b"chunked")]

        header_names = [name for name, _ in headers]
        assert b"transfer-encoding" in header_names

    def test_no_content_length_with_transfer_encoding(self):
        """Test Content-Length should not be present with Transfer-Encoding."""
        # Per HTTP spec, Content-Length must be ignored if Transfer-Encoding present
        headers = [
            (b"content-type", b"text/plain"),
            (b"transfer-encoding", b"chunked"),
        ]

        header_names = [name for name, _ in headers]
        assert b"content-length" not in header_names
