#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for dirty client sync streaming functionality."""

import socket
import struct
import pytest
from unittest import mock

from gunicorn.dirty.protocol import (
    DirtyProtocol,
    BinaryProtocol,
    make_chunk_message,
    make_end_message,
    make_response,
    make_error_response,
    HEADER_SIZE,
)
from gunicorn.dirty.client import DirtyClient, DirtyStreamIterator
from gunicorn.dirty.errors import DirtyError, DirtyConnectionError


class MockSocket:
    """Mock socket that returns predefined messages."""

    def __init__(self, messages):
        self._data = b''
        for msg in messages:
            self._data += BinaryProtocol._encode_from_dict(msg)
        self._pos = 0
        self._sent = []
        self.closed = False
        self._timeout = None

    def sendall(self, data):
        self._sent.append(data)

    def recv(self, n, flags=0):
        if self._pos >= len(self._data):
            return b''
        end = min(self._pos + n, len(self._data))
        result = self._data[self._pos:end]
        self._pos = end
        return result

    def settimeout(self, timeout):
        self._timeout = timeout

    def close(self):
        self.closed = True


def create_client_with_mock_socket(messages):
    """Create a client with a mock socket returning the given messages."""
    client = DirtyClient("/tmp/test.sock")
    client._sock = MockSocket(messages)
    return client


class TestDirtyStreamIterator:
    """Tests for DirtyStreamIterator."""

    def test_stream_returns_iterator(self):
        """Test that stream() returns an iterator."""
        client = DirtyClient("/tmp/test.sock")
        result = client.stream("test:App", "generate")
        assert isinstance(result, DirtyStreamIterator)

    def test_stream_iterator_yields_chunks(self):
        """Test that stream iterator yields chunks correctly."""
        messages = [
            make_chunk_message(123, "Hello"),
            make_chunk_message(123, " "),
            make_chunk_message(123, "World"),
            make_end_message(123),
        ]
        client = create_client_with_mock_socket(messages)

        chunks = list(client.stream("test:App", "generate"))

        assert chunks == ["Hello", " ", "World"]

    def test_stream_iterator_yields_complex_chunks(self):
        """Test that stream iterator yields complex data types."""
        messages = [
            make_chunk_message(123, {"token": "Hello", "score": 0.9}),
            make_chunk_message(123, {"token": "World", "score": 0.8}),
            make_end_message(123),
        ]
        client = create_client_with_mock_socket(messages)

        chunks = list(client.stream("test:App", "generate"))

        assert len(chunks) == 2
        assert chunks[0]["token"] == "Hello"
        assert chunks[1]["token"] == "World"

    def test_stream_iterator_handles_error(self):
        """Test that stream iterator raises on error message."""
        messages = [
            make_chunk_message(123, "First"),
            make_error_response(123, DirtyError("Something broke")),
        ]
        client = create_client_with_mock_socket(messages)

        iterator = client.stream("test:App", "generate")

        # First chunk should work
        chunk = next(iterator)
        assert chunk == "First"

        # Second should raise error
        with pytest.raises(DirtyError) as exc_info:
            next(iterator)
        assert "Something broke" in str(exc_info.value)

    def test_stream_iterator_empty_stream(self):
        """Test that empty stream (just end) works."""
        messages = [make_end_message(123)]
        client = create_client_with_mock_socket(messages)

        chunks = list(client.stream("test:App", "generate"))
        assert chunks == []

    def test_stream_iterator_stops_after_exhausted(self):
        """Test that iterator stays exhausted after StopIteration."""
        messages = [
            make_chunk_message(123, "Only"),
            make_end_message(123),
        ]
        client = create_client_with_mock_socket(messages)

        iterator = client.stream("test:App", "generate")

        # Get the chunk
        chunk = next(iterator)
        assert chunk == "Only"

        # Should stop
        with pytest.raises(StopIteration):
            next(iterator)

        # Should stay stopped
        with pytest.raises(StopIteration):
            next(iterator)

    def test_stream_iterator_with_for_loop(self):
        """Test stream iterator works in for loop."""
        messages = [
            make_chunk_message(123, "a"),
            make_chunk_message(123, "b"),
            make_chunk_message(123, "c"),
            make_end_message(123),
        ]
        client = create_client_with_mock_socket(messages)

        result = ""
        for chunk in client.stream("test:App", "generate"):
            result += chunk

        assert result == "abc"

    def test_stream_sends_request_on_first_iteration(self):
        """Test that request is sent on first next() call."""
        messages = [
            make_chunk_message(123, "data"),
            make_end_message(123),
        ]
        client = create_client_with_mock_socket(messages)

        iterator = client.stream("test:App", "generate", "prompt_arg")

        # Before iteration, no request sent
        assert len(client._sock._sent) == 0

        # First iteration sends request
        next(iterator)
        assert len(client._sock._sent) == 1

        # Decode sent request
        sent_data = client._sock._sent[0]
        _, _, length = BinaryProtocol.decode_header(sent_data[:HEADER_SIZE])
        msg_type_str, request_id, payload = BinaryProtocol.decode_message(
            sent_data[:HEADER_SIZE + length]
        )

        assert msg_type_str == "request"
        assert payload["app_path"] == "test:App"
        assert payload["action"] == "generate"
        assert payload["args"] == ["prompt_arg"]


class TestDirtyStreamIteratorEdgeCases:
    """Edge cases for streaming."""

    def test_stream_many_chunks(self):
        """Test streaming with many chunks."""
        messages = []
        for i in range(100):
            messages.append(make_chunk_message(123, f"chunk-{i}"))
        messages.append(make_end_message(123))

        client = create_client_with_mock_socket(messages)

        chunks = list(client.stream("test:App", "generate"))

        assert len(chunks) == 100
        assert chunks[0] == "chunk-0"
        assert chunks[99] == "chunk-99"

    def test_stream_with_kwargs(self):
        """Test streaming with keyword arguments."""
        messages = [
            make_chunk_message(123, "data"),
            make_end_message(123),
        ]
        client = create_client_with_mock_socket(messages)

        # Use kwargs
        list(client.stream("test:App", "generate", "arg1", key="value"))

        # Check the sent request includes kwargs
        sent_data = client._sock._sent[0]
        _, _, length = BinaryProtocol.decode_header(sent_data[:HEADER_SIZE])
        msg_type_str, request_id, payload = BinaryProtocol.decode_message(
            sent_data[:HEADER_SIZE + length]
        )

        assert payload["args"] == ["arg1"]
        assert payload["kwargs"] == {"key": "value"}
