"""
Streaming Response Tests

Tests chunked streaming and Server-Sent Events across frameworks.
"""

import asyncio
import json

import pytest


pytestmark = pytest.mark.streaming


class TestChunkedStreaming:
    """Test chunked transfer encoding responses."""

    async def test_streaming_response(self, http_client):
        """Streaming endpoint returns chunked response."""
        response = await http_client.get("/streaming")
        assert response.status_code == 200
        # Check we got all chunks
        content = response.text
        for i in range(10):
            assert f"chunk-{i}" in content

    async def test_streaming_content_type(self, http_client):
        """Streaming response has correct content type."""
        response = await http_client.get("/streaming")
        assert "text/plain" in response.headers.get("content-type", "")

    async def test_streaming_order_preserved(self, http_client):
        """Chunks arrive in correct order."""
        response = await http_client.get("/streaming")
        lines = [l for l in response.text.strip().split("\n") if l]
        for i, line in enumerate(lines):
            assert line == f"chunk-{i}"


class TestServerSentEvents:
    """Test Server-Sent Events (SSE) responses."""

    async def test_sse_response(self, http_client):
        """SSE endpoint returns event stream."""
        response = await http_client.get("/sse")
        assert response.status_code == 200
        content = response.text
        assert "event:" in content
        assert "data:" in content

    async def test_sse_content_type(self, http_client):
        """SSE response has correct content type."""
        response = await http_client.get("/sse")
        content_type = response.headers.get("content-type", "")
        assert "text/event-stream" in content_type

    async def test_sse_event_format(self, http_client):
        """SSE events have correct format."""
        response = await http_client.get("/sse")
        content = response.text

        # Check for message events
        assert "event: message" in content

        # Check for done event
        assert "event: done" in content

    async def test_sse_data_is_json(self, http_client):
        """SSE data fields contain valid JSON."""
        response = await http_client.get("/sse")
        lines = response.text.split("\n")

        data_lines = [l for l in lines if l.startswith("data:")]
        for line in data_lines:
            data_str = line[5:].strip()  # Remove "data:" prefix
            data = json.loads(data_str)
            assert isinstance(data, dict)

    async def test_sse_message_count(self, http_client):
        """Correct number of SSE messages received."""
        response = await http_client.get("/sse")
        lines = response.text.split("\n")

        message_events = [l for l in lines if l == "event: message"]
        # Should have 5 message events
        assert len(message_events) == 5


class TestStreamingLargeData:
    """Test streaming with large data."""

    async def test_large_streaming_response(self, http_client):
        """Large response body streams correctly."""
        size = 5 * 1024 * 1024  # 5MB
        response = await http_client.get(f"/large?size={size}")
        assert response.status_code == 200
        assert len(response.content) == size
