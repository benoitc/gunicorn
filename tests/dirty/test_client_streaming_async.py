#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for dirty client async streaming functionality."""

import asyncio
import struct
import pytest

from gunicorn.dirty.protocol import (
    DirtyProtocol,
    BinaryProtocol,
    make_chunk_message,
    make_end_message,
    make_error_response,
    HEADER_SIZE,
)
from gunicorn.dirty.client import DirtyClient, DirtyAsyncStreamIterator
from gunicorn.dirty.errors import DirtyError, DirtyTimeoutError


class MockAsyncReader:
    """Mock async reader that returns predefined messages."""

    def __init__(self, messages):
        self._data = b''
        for msg in messages:
            self._data += BinaryProtocol._encode_from_dict(msg)
        self._pos = 0

    async def readexactly(self, n):
        if self._pos + n > len(self._data):
            raise asyncio.IncompleteReadError(self._data[self._pos:], n)
        result = self._data[self._pos:self._pos + n]
        self._pos += n
        return result


class MockAsyncWriter:
    """Mock async writer that captures sent data."""

    def __init__(self):
        self._sent = []
        self.closed = False

    def write(self, data):
        self._sent.append(data)

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass


def create_async_client_with_mocks(messages):
    """Create a client with mock async reader/writer."""
    client = DirtyClient("/tmp/test.sock")
    client._reader = MockAsyncReader(messages)
    client._writer = MockAsyncWriter()
    return client


class TestDirtyAsyncStreamIterator:
    """Tests for DirtyAsyncStreamIterator."""

    def test_stream_async_returns_async_iterator(self):
        """Test that stream_async() returns an async iterator."""
        client = DirtyClient("/tmp/test.sock")
        result = client.stream_async("test:App", "generate")
        assert isinstance(result, DirtyAsyncStreamIterator)

    @pytest.mark.asyncio
    async def test_async_stream_yields_chunks(self):
        """Test that async stream iterator yields chunks correctly."""
        messages = [
            make_chunk_message(123, "Hello"),
            make_chunk_message(123, " "),
            make_chunk_message(123, "World"),
            make_end_message(123),
        ]
        client = create_async_client_with_mocks(messages)

        chunks = []
        async for chunk in client.stream_async("test:App", "generate"):
            chunks.append(chunk)

        assert chunks == ["Hello", " ", "World"]

    @pytest.mark.asyncio
    async def test_async_stream_yields_complex_chunks(self):
        """Test that async stream iterator yields complex data types."""
        messages = [
            make_chunk_message(123, {"token": "Hello", "score": 0.9}),
            make_chunk_message(123, {"token": "World", "score": 0.8}),
            make_end_message(123),
        ]
        client = create_async_client_with_mocks(messages)

        chunks = []
        async for chunk in client.stream_async("test:App", "generate"):
            chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0]["token"] == "Hello"
        assert chunks[1]["token"] == "World"

    @pytest.mark.asyncio
    async def test_async_stream_handles_error(self):
        """Test that async stream iterator raises on error message."""
        messages = [
            make_chunk_message(123, "First"),
            make_error_response(123, DirtyError("Something broke")),
        ]
        client = create_async_client_with_mocks(messages)

        iterator = client.stream_async("test:App", "generate")

        # First chunk should work
        chunk = await iterator.__anext__()
        assert chunk == "First"

        # Second should raise error
        with pytest.raises(DirtyError) as exc_info:
            await iterator.__anext__()
        assert "Something broke" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_async_stream_empty_stream(self):
        """Test that empty stream (just end) works."""
        messages = [make_end_message(123)]
        client = create_async_client_with_mocks(messages)

        chunks = []
        async for chunk in client.stream_async("test:App", "generate"):
            chunks.append(chunk)

        assert chunks == []

    @pytest.mark.asyncio
    async def test_async_stream_stops_after_exhausted(self):
        """Test that async iterator stays exhausted after StopAsyncIteration."""
        messages = [
            make_chunk_message(123, "Only"),
            make_end_message(123),
        ]
        client = create_async_client_with_mocks(messages)

        iterator = client.stream_async("test:App", "generate")

        # Get the chunk
        chunk = await iterator.__anext__()
        assert chunk == "Only"

        # Should stop
        with pytest.raises(StopAsyncIteration):
            await iterator.__anext__()

        # Should stay stopped
        with pytest.raises(StopAsyncIteration):
            await iterator.__anext__()

    @pytest.mark.asyncio
    async def test_async_stream_sends_request_on_first_iteration(self):
        """Test that request is sent on first async iteration."""
        messages = [
            make_chunk_message(123, "data"),
            make_end_message(123),
        ]
        client = create_async_client_with_mocks(messages)

        iterator = client.stream_async("test:App", "generate", "prompt_arg")

        # Before iteration, no request sent
        assert len(client._writer._sent) == 0

        # First iteration sends request
        await iterator.__anext__()
        assert len(client._writer._sent) == 1

        # Decode sent request
        sent_data = client._writer._sent[0]
        _, _, length = BinaryProtocol.decode_header(sent_data[:HEADER_SIZE])
        msg_type_str, request_id, payload = BinaryProtocol.decode_message(
            sent_data[:HEADER_SIZE + length]
        )

        assert msg_type_str == "request"
        assert payload["app_path"] == "test:App"
        assert payload["action"] == "generate"
        assert payload["args"] == ["prompt_arg"]


class TestDirtyAsyncStreamIteratorEdgeCases:
    """Edge cases for async streaming."""

    @pytest.mark.asyncio
    async def test_async_stream_many_chunks(self):
        """Test async streaming with many chunks."""
        messages = []
        for i in range(100):
            messages.append(make_chunk_message(123, f"chunk-{i}"))
        messages.append(make_end_message(123))

        client = create_async_client_with_mocks(messages)

        chunks = []
        async for chunk in client.stream_async("test:App", "generate"):
            chunks.append(chunk)

        assert len(chunks) == 100
        assert chunks[0] == "chunk-0"
        assert chunks[99] == "chunk-99"

    @pytest.mark.asyncio
    async def test_async_stream_with_kwargs(self):
        """Test async streaming with keyword arguments."""
        messages = [
            make_chunk_message(123, "data"),
            make_end_message(123),
        ]
        client = create_async_client_with_mocks(messages)

        # Use kwargs
        chunks = []
        async for chunk in client.stream_async("test:App", "generate", "arg1", key="value"):
            chunks.append(chunk)

        # Check the sent request includes kwargs
        sent_data = client._writer._sent[0]
        _, _, length = BinaryProtocol.decode_header(sent_data[:HEADER_SIZE])
        msg_type_str, request_id, payload = BinaryProtocol.decode_message(
            sent_data[:HEADER_SIZE + length]
        )

        assert payload["args"] == ["arg1"]
        assert payload["kwargs"] == {"key": "value"}


class TestDirtyAsyncStreamTimeout:
    """Tests for async streaming timeout handling."""

    @pytest.mark.asyncio
    async def test_async_stream_timeout(self):
        """Test that timeout during async streaming raises DirtyTimeoutError."""
        client = DirtyClient("/tmp/test.sock", timeout=0.01)

        # Create a reader that times out
        class SlowReader:
            async def readexactly(self, n):
                await asyncio.sleep(1)  # Longer than timeout

        client._reader = SlowReader()
        client._writer = MockAsyncWriter()

        iterator = client.stream_async("test:App", "generate")

        with pytest.raises(DirtyTimeoutError):
            await iterator.__anext__()
