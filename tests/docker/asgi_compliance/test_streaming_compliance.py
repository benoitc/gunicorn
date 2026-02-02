#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Streaming compliance integration tests for ASGI.

Tests chunked transfer encoding, Server-Sent Events (SSE),
and streaming response handling.
"""

import json
import time

import pytest

pytestmark = [
    pytest.mark.docker,
    pytest.mark.asgi,
    pytest.mark.streaming,
    pytest.mark.integration,
]


# ============================================================================
# Basic Streaming Tests
# ============================================================================

class TestBasicStreaming:
    """Test basic streaming response functionality."""

    def test_streaming_endpoint(self, http_client, gunicorn_url):
        """Test basic streaming endpoint."""
        response = http_client.get(f"{gunicorn_url}/stream/streaming")
        assert response.status_code == 200
        assert "Chunk" in response.text

    def test_streaming_multiple_chunks(self, http_client, gunicorn_url):
        """Test streaming returns multiple chunks."""
        response = http_client.get(f"{gunicorn_url}/stream/streaming?chunks=5")
        assert response.status_code == 200
        lines = response.text.strip().split("\n")
        assert len(lines) == 5
        assert "Chunk 1 of 5" in lines[0]
        assert "Chunk 5 of 5" in lines[4]

    def test_streaming_single_chunk(self, http_client, gunicorn_url):
        """Test streaming with single chunk."""
        response = http_client.get(f"{gunicorn_url}/stream/streaming?chunks=1")
        assert response.status_code == 200
        assert "Chunk 1 of 1" in response.text


class TestChunkedStreaming:
    """Test chunked streaming with the streaming client."""

    def test_stream_chunks_received(self, streaming_client, gunicorn_url):
        """Test that chunks are received incrementally."""
        chunks = list(streaming_client.stream_chunks(f"{gunicorn_url}/stream/streaming?chunks=3"))
        assert len(chunks) >= 1
        full_content = b"".join(chunks).decode("utf-8")
        assert "Chunk 1" in full_content
        assert "Chunk 3" in full_content

    def test_stream_variable_chunk_sizes(self, streaming_client, gunicorn_url):
        """Test streaming with variable chunk sizes."""
        chunks = list(streaming_client.stream_chunks(
            f"{gunicorn_url}/stream/chunked?sizes=100,500,200"
        ))
        total_size = sum(len(c) for c in chunks)
        assert total_size == 800  # 100 + 500 + 200

    def test_stream_lines(self, streaming_client, gunicorn_url):
        """Test streaming response line by line."""
        lines = list(streaming_client.stream_lines(f"{gunicorn_url}/stream/streaming?chunks=5"))
        non_empty_lines = [l for l in lines if l.strip()]
        assert len(non_empty_lines) == 5


# ============================================================================
# Server-Sent Events (SSE) Tests
# ============================================================================

class TestServerSentEvents:
    """Test Server-Sent Events functionality."""

    def test_sse_content_type(self, http_client, gunicorn_url):
        """Test SSE has correct content type."""
        response = http_client.get(f"{gunicorn_url}/stream/sse?events=1")
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

    def test_sse_event_format(self, http_client, gunicorn_url):
        """Test SSE event format."""
        response = http_client.get(f"{gunicorn_url}/stream/sse?events=3&delay=0.1")
        assert response.status_code == 200

        # Parse SSE events
        events = []
        for event_text in response.text.split("\n\n"):
            if event_text.strip():
                event = {}
                for line in event_text.strip().split("\n"):
                    if line.startswith("id: "):
                        event["id"] = line[4:]
                    elif line.startswith("event: "):
                        event["event"] = line[7:]
                    elif line.startswith("data: "):
                        event["data"] = line[6:]
                if event:
                    events.append(event)

        assert len(events) == 3
        assert events[0]["id"] == "1"
        assert events[0]["event"] == "message"

    def test_sse_data_is_json(self, http_client, gunicorn_url):
        """Test SSE data contains valid JSON."""
        response = http_client.get(f"{gunicorn_url}/stream/sse?events=1")
        assert response.status_code == 200

        # Find data line
        for line in response.text.split("\n"):
            if line.startswith("data: "):
                data = json.loads(line[6:])
                assert "id" in data
                assert "timestamp" in data
                break

    def test_sse_multiple_events(self, http_client, gunicorn_url):
        """Test receiving multiple SSE events."""
        response = http_client.get(f"{gunicorn_url}/stream/sse?events=5&delay=0.05")
        assert response.status_code == 200

        # Count events by counting "id:" lines
        id_count = response.text.count("id: ")
        assert id_count == 5


class TestSSEClient:
    """Test SSE with dedicated SSE client."""

    def test_sse_client_receives_events(self, sse_client, gunicorn_url):
        """Test SSE client receives events."""
        events = list(sse_client.stream(f"{gunicorn_url}/stream/sse?events=3&delay=0.1"))
        assert len(events) == 3

    def test_sse_client_parses_data(self, sse_client, gunicorn_url):
        """Test SSE client parses event data."""
        events = list(sse_client.stream(f"{gunicorn_url}/stream/sse?events=2&delay=0.1"))

        for event in events:
            assert event["event"] == "message"
            assert event["data"] is not None
            data = json.loads(event["data"])
            assert "id" in data


# ============================================================================
# NDJSON Streaming Tests
# ============================================================================

class TestNDJSONStreaming:
    """Test Newline-Delimited JSON streaming."""

    def test_ndjson_content_type(self, http_client, gunicorn_url):
        """Test NDJSON has correct content type."""
        response = http_client.get(f"{gunicorn_url}/stream/ndjson?records=1")
        assert response.status_code == 200
        assert "application/x-ndjson" in response.headers.get("content-type", "")

    def test_ndjson_format(self, http_client, gunicorn_url):
        """Test NDJSON line format."""
        response = http_client.get(f"{gunicorn_url}/stream/ndjson?records=3&delay=0")
        assert response.status_code == 200

        lines = response.text.strip().split("\n")
        assert len(lines) == 3

        for i, line in enumerate(lines):
            record = json.loads(line)
            assert record["id"] == i + 1
            assert "timestamp" in record
            assert "data" in record

    def test_ndjson_streaming(self, streaming_client, gunicorn_url):
        """Test NDJSON received as stream."""
        lines = list(streaming_client.stream_lines(
            f"{gunicorn_url}/stream/ndjson?records=5&delay=0.1"
        ))
        non_empty = [l for l in lines if l.strip()]
        assert len(non_empty) == 5


# ============================================================================
# Slow Streaming Tests
# ============================================================================

class TestSlowStreaming:
    """Test slow/delayed streaming responses."""

    def test_slow_stream_completes(self, http_client, gunicorn_url):
        """Test slow stream eventually completes."""
        start = time.time()
        response = http_client.get(f"{gunicorn_url}/stream/slow-stream?chunks=3&delay=0.2")
        elapsed = time.time() - start

        assert response.status_code == 200
        assert elapsed >= 0.4  # At least 2 delays
        assert "Slow chunk 3/3" in response.text

    def test_slow_stream_chunks_timed(self, streaming_client, gunicorn_url):
        """Test slow stream chunks arrive at intervals."""
        chunks = []
        times = []

        for chunk in streaming_client.stream_chunks(
            f"{gunicorn_url}/stream/slow-stream?chunks=3&delay=0.3"
        ):
            chunks.append(chunk)
            times.append(time.time())

        # Should have some time between chunks
        if len(times) >= 2:
            assert times[-1] - times[0] >= 0.3


# ============================================================================
# Large Streaming Tests
# ============================================================================

class TestLargeStreaming:
    """Test large streaming responses."""

    def test_large_stream_size(self, http_client, gunicorn_url):
        """Test large streaming response has correct size."""
        size = 1024 * 1024  # 1MB
        response = http_client.get(f"{gunicorn_url}/stream/large-stream?size={size}")
        assert response.status_code == 200
        assert len(response.content) == size

    def test_large_stream_chunked(self, streaming_client, gunicorn_url):
        """Test large streaming response arrives in chunks."""
        size = 512 * 1024  # 512KB
        chunk_size = 64 * 1024  # 64KB chunks

        chunks = list(streaming_client.stream_chunks(
            f"{gunicorn_url}/stream/large-stream?size={size}&chunk={chunk_size}"
        ))

        total_size = sum(len(c) for c in chunks)
        assert total_size == size
        # Should have multiple chunks
        assert len(chunks) >= 2


# ============================================================================
# Echo Stream Tests
# ============================================================================

class TestEchoStreaming:
    """Test streaming echo endpoint."""

    def test_echo_stream_response(self, http_client, gunicorn_url):
        """Test echo stream returns chunked response."""
        body = b"Hello, streaming world!"
        response = http_client.post(
            f"{gunicorn_url}/stream/echo-stream",
            content=body
        )
        assert response.status_code == 200
        assert b"chunk" in response.content.lower()

    def test_echo_stream_large_body(self, http_client, gunicorn_url):
        """Test echo stream with large body."""
        body = b"x" * (100 * 1024)  # 100KB
        response = http_client.post(
            f"{gunicorn_url}/stream/echo-stream",
            content=body
        )
        assert response.status_code == 200
        assert b"Total chunks received" in response.content


# ============================================================================
# Transfer-Encoding Tests
# ============================================================================

class TestTransferEncoding:
    """Test Transfer-Encoding header handling."""

    def test_chunked_encoding_header(self, http_client, gunicorn_url):
        """Test response uses chunked transfer encoding."""
        response = http_client.get(f"{gunicorn_url}/stream/streaming?chunks=3")
        assert response.status_code == 200
        # Note: httpx may decompress/dechunk, so we check the response completed
        assert "Chunk" in response.text

    def test_no_content_length_in_stream(self, http_client, gunicorn_url):
        """Test streaming response may not have Content-Length."""
        # This is implementation-dependent; chunked encoding doesn't require it
        response = http_client.get(f"{gunicorn_url}/stream/streaming?chunks=3")
        assert response.status_code == 200
        # The response should complete successfully regardless


# ============================================================================
# Proxy Streaming Tests
# ============================================================================

class TestProxyStreaming:
    """Test streaming through nginx proxy."""

    def test_proxy_streaming(self, http_client, nginx_url):
        """Test streaming through proxy."""
        response = http_client.get(f"{nginx_url}/stream/streaming?chunks=3")
        assert response.status_code == 200
        assert "Chunk" in response.text

    def test_proxy_sse(self, http_client, nginx_url):
        """Test SSE through proxy."""
        response = http_client.get(f"{nginx_url}/stream/sse?events=3&delay=0.1")
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        assert "id: 1" in response.text

    def test_proxy_large_stream(self, http_client, nginx_url):
        """Test large streaming through proxy."""
        size = 512 * 1024
        response = http_client.get(f"{nginx_url}/stream/large-stream?size={size}")
        assert response.status_code == 200
        assert len(response.content) == size

    def test_proxy_slow_stream(self, streaming_client, nginx_url):
        """Test slow streaming through proxy."""
        chunks = list(streaming_client.stream_chunks(
            f"{nginx_url}/stream/slow-stream?chunks=3&delay=0.2"
        ))
        full_content = b"".join(chunks).decode("utf-8")
        assert "Slow chunk 3/3" in full_content


# ============================================================================
# HTTPS Streaming Tests
# ============================================================================

@pytest.mark.ssl
class TestHTTPSStreaming:
    """Test streaming over HTTPS."""

    def test_https_streaming(self, http_client, gunicorn_ssl_url):
        """Test streaming over HTTPS."""
        response = http_client.get(f"{gunicorn_ssl_url}/stream/streaming?chunks=3")
        assert response.status_code == 200
        assert "Chunk" in response.text

    def test_https_sse(self, http_client, gunicorn_ssl_url):
        """Test SSE over HTTPS."""
        response = http_client.get(f"{gunicorn_ssl_url}/stream/sse?events=2&delay=0.1")
        assert response.status_code == 200
        assert "id: 1" in response.text

    def test_https_proxy_streaming(self, http_client, nginx_ssl_url):
        """Test streaming through HTTPS proxy."""
        response = http_client.get(f"{nginx_ssl_url}/stream/streaming?chunks=3")
        assert response.status_code == 200


# ============================================================================
# Async Streaming Tests
# ============================================================================

@pytest.mark.asyncio
class TestAsyncStreaming:
    """Test streaming with async client."""

    async def test_async_streaming(self, async_http_client_factory, gunicorn_url):
        """Test async streaming."""
        async with await async_http_client_factory() as client:
            response = await client.get(f"{gunicorn_url}/stream/streaming?chunks=3")
            assert response.status_code == 200
            assert "Chunk" in response.text

    async def test_async_stream_chunks(self, async_http_client_factory, gunicorn_url):
        """Test async streaming with iter_bytes."""
        async with await async_http_client_factory() as client:
            chunks = []
            async with client.stream("GET", f"{gunicorn_url}/stream/streaming?chunks=5") as response:
                async for chunk in response.aiter_bytes():
                    if chunk:
                        chunks.append(chunk)

            full_content = b"".join(chunks).decode("utf-8")
            assert "Chunk 5 of 5" in full_content

    async def test_async_sse(self, async_http_client_factory, gunicorn_url):
        """Test async SSE streaming."""
        async with await async_http_client_factory() as client:
            events = []
            async with client.stream(
                "GET",
                f"{gunicorn_url}/stream/sse?events=3&delay=0.1"
            ) as response:
                buffer = ""
                async for chunk in response.aiter_text():
                    buffer += chunk
                    while "\n\n" in buffer:
                        event_text, buffer = buffer.split("\n\n", 1)
                        if event_text.strip():
                            events.append(event_text)

            assert len(events) == 3


# ============================================================================
# Edge Cases
# ============================================================================

class TestStreamingEdgeCases:
    """Test streaming edge cases."""

    def test_empty_stream(self, http_client, gunicorn_url):
        """Test streaming with zero chunks."""
        response = http_client.get(f"{gunicorn_url}/stream/streaming?chunks=0")
        assert response.status_code == 200
        # Should complete without error

    def test_single_byte_chunks(self, streaming_client, gunicorn_url):
        """Test with very small chunks."""
        response_chunks = list(streaming_client.stream_chunks(
            f"{gunicorn_url}/stream/chunked?sizes=1,1,1,1,1"
        ))
        total_size = sum(len(c) for c in response_chunks)
        assert total_size == 5

    def test_sse_no_delay(self, http_client, gunicorn_url):
        """Test SSE with no delay between events."""
        response = http_client.get(f"{gunicorn_url}/stream/sse?events=10&delay=0")
        assert response.status_code == 200
        assert response.text.count("id:") == 10
