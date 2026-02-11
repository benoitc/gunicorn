#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for dirty arbiter streaming functionality."""

import asyncio
import struct
from unittest import mock

import pytest

from gunicorn.dirty.protocol import (
    DirtyProtocol,
    BinaryProtocol,
    make_request,
    make_response,
    make_chunk_message,
    make_end_message,
    make_error_response,
    HEADER_SIZE,
)
from gunicorn.dirty.arbiter import DirtyArbiter
from gunicorn.dirty.errors import DirtyError


class MockStreamWriter:
    """Mock StreamWriter that captures written messages."""

    def __init__(self):
        self.messages = []
        self._buffer = b""
        self.closed = False

    def write(self, data):
        self._buffer += data

    async def drain(self):
        # Decode the buffer to extract messages using binary protocol
        while len(self._buffer) >= HEADER_SIZE:
            # Decode header to get payload length
            _, _, length = BinaryProtocol.decode_header(
                self._buffer[:HEADER_SIZE]
            )
            total_size = HEADER_SIZE + length
            if len(self._buffer) >= total_size:
                msg_data = self._buffer[:total_size]
                self._buffer = self._buffer[total_size:]
                # decode_message returns (msg_type_str, request_id, payload_dict)
                msg_type_str, request_id, payload_dict = BinaryProtocol.decode_message(msg_data)
                # Reconstruct the dict format for backwards compatibility
                result = {"type": msg_type_str, "id": request_id}
                result.update(payload_dict)
                self.messages.append(result)
            else:
                break

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass

    def get_extra_info(self, name):
        return None


class MockStreamReader:
    """Mock StreamReader that yields predefined messages."""

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


def create_arbiter():
    """Create a test arbiter with mocked components."""
    cfg = mock.Mock()
    cfg.dirty_timeout = 30
    cfg.dirty_workers = 1
    cfg.dirty_apps = []
    cfg.dirty_graceful_timeout = 30
    cfg.on_dirty_starting = mock.Mock()
    cfg.dirty_post_fork = mock.Mock()
    cfg.dirty_worker_exit = mock.Mock()

    log = mock.Mock()

    with mock.patch('tempfile.mkdtemp', return_value='/tmp/test-dirty'):
        arbiter = DirtyArbiter(cfg, log)

    arbiter.alive = True
    arbiter.workers = {1234: mock.Mock()}  # Fake worker
    arbiter.worker_sockets = {1234: '/tmp/worker.sock'}

    return arbiter


class TestArbiterStreamingForwarding:
    """Tests for arbiter streaming message forwarding."""

    @pytest.mark.asyncio
    async def test_forwards_chunk_messages(self):
        """Test that arbiter forwards chunk messages to client."""
        arbiter = create_arbiter()
        client_writer = MockStreamWriter()

        # Mock worker connection that returns chunks
        chunk1 = make_chunk_message(123, "Hello")
        chunk2 = make_chunk_message(123, " World")
        end = make_end_message(123)

        mock_reader = MockStreamReader([chunk1, chunk2, end])

        async def mock_get_connection(pid):
            return mock_reader, MockStreamWriter()

        arbiter._get_worker_connection = mock_get_connection

        request = make_request(123, "test:App", "generate")
        await arbiter._execute_on_worker(1234, request, client_writer)

        # Should have forwarded all messages
        assert len(client_writer.messages) == 3
        assert client_writer.messages[0]["type"] == "chunk"
        assert client_writer.messages[0]["data"] == "Hello"
        assert client_writer.messages[1]["type"] == "chunk"
        assert client_writer.messages[1]["data"] == " World"
        assert client_writer.messages[2]["type"] == "end"

    @pytest.mark.asyncio
    async def test_forwards_regular_response(self):
        """Test that arbiter forwards regular response to client."""
        arbiter = create_arbiter()
        client_writer = MockStreamWriter()

        response = make_response(123, {"result": 42})
        mock_reader = MockStreamReader([response])

        async def mock_get_connection(pid):
            return mock_reader, MockStreamWriter()

        arbiter._get_worker_connection = mock_get_connection

        request = make_request(123, "test:App", "compute")
        await arbiter._execute_on_worker(1234, request, client_writer)

        assert len(client_writer.messages) == 1
        assert client_writer.messages[0]["type"] == "response"
        assert client_writer.messages[0]["result"] == {"result": 42}

    @pytest.mark.asyncio
    async def test_forwards_error_mid_stream(self):
        """Test that arbiter forwards error during streaming."""
        arbiter = create_arbiter()
        client_writer = MockStreamWriter()

        chunk = make_chunk_message(123, "First")
        error = make_error_response(123, DirtyError("Something broke"))

        mock_reader = MockStreamReader([chunk, error])

        async def mock_get_connection(pid):
            return mock_reader, MockStreamWriter()

        arbiter._get_worker_connection = mock_get_connection

        request = make_request(123, "test:App", "generate")
        await arbiter._execute_on_worker(1234, request, client_writer)

        assert len(client_writer.messages) == 2
        assert client_writer.messages[0]["type"] == "chunk"
        assert client_writer.messages[1]["type"] == "error"

    @pytest.mark.asyncio
    async def test_timeout_during_streaming(self):
        """Test that timeout during streaming sends error."""
        arbiter = create_arbiter()
        arbiter.cfg.dirty_timeout = 0.01  # Very short timeout
        client_writer = MockStreamWriter()

        # Reader that times out
        class TimeoutReader:
            async def readexactly(self, n):
                await asyncio.sleep(1)  # Longer than timeout

        async def mock_get_connection(pid):
            return TimeoutReader(), MockStreamWriter()

        arbiter._get_worker_connection = mock_get_connection

        request = make_request(123, "test:App", "generate")
        await arbiter._execute_on_worker(1234, request, client_writer)

        assert len(client_writer.messages) == 1
        assert client_writer.messages[0]["type"] == "error"
        assert "timeout" in client_writer.messages[0]["error"]["message"].lower()


class TestArbiterRouteRequestStreaming:
    """Tests for route_request with streaming support."""

    @pytest.mark.asyncio
    async def test_route_request_no_workers(self):
        """Test route_request when no workers available."""
        arbiter = create_arbiter()
        arbiter.workers = {}  # No workers
        client_writer = MockStreamWriter()

        request = make_request(123, "test:App", "generate")
        await arbiter.route_request(request, client_writer)

        assert len(client_writer.messages) == 1
        assert client_writer.messages[0]["type"] == "error"
        assert "No dirty workers" in client_writer.messages[0]["error"]["message"]

    @pytest.mark.asyncio
    async def test_route_request_starts_consumer(self):
        """Test that route_request starts consumer if needed."""
        arbiter = create_arbiter()

        # Mock _execute_on_worker to complete immediately
        async def mock_execute(pid, request, client_writer):
            response = make_response(123, "result")
            await DirtyProtocol.write_message_async(client_writer, response)

        arbiter._execute_on_worker = mock_execute

        client_writer = MockStreamWriter()
        request = make_request(123, "test:App", "compute")

        # Worker queue should be created
        assert 1234 not in arbiter.worker_queues

        await arbiter.route_request(request, client_writer)

        # Consumer should have been started
        assert 1234 in arbiter.worker_queues
        assert 1234 in arbiter.worker_consumers

        # Clean up
        arbiter.worker_consumers[1234].cancel()


class TestArbiterStreamingManyChunks:
    """Tests for streaming with many chunks."""

    @pytest.mark.asyncio
    async def test_forwards_many_chunks(self):
        """Test that arbiter forwards many chunks correctly."""
        arbiter = create_arbiter()
        client_writer = MockStreamWriter()

        # Generate 50 chunks + end
        messages = []
        for i in range(50):
            messages.append(make_chunk_message(123, f"chunk-{i}"))
        messages.append(make_end_message(123))

        mock_reader = MockStreamReader(messages)

        async def mock_get_connection(pid):
            return mock_reader, MockStreamWriter()

        arbiter._get_worker_connection = mock_get_connection

        request = make_request(123, "test:App", "generate")
        await arbiter._execute_on_worker(1234, request, client_writer)

        assert len(client_writer.messages) == 51
        assert client_writer.messages[0]["data"] == "chunk-0"
        assert client_writer.messages[49]["data"] == "chunk-49"
        assert client_writer.messages[50]["type"] == "end"


class TestArbiterBackwardCompatibility:
    """Tests for backward compatibility with non-streaming."""

    @pytest.mark.asyncio
    async def test_handles_regular_response(self):
        """Test that regular (non-streaming) responses still work."""
        arbiter = create_arbiter()
        client_writer = MockStreamWriter()

        response = make_response(123, [1, 2, 3, 4, 5])
        mock_reader = MockStreamReader([response])

        async def mock_get_connection(pid):
            return mock_reader, MockStreamWriter()

        arbiter._get_worker_connection = mock_get_connection

        request = make_request(123, "test:App", "get_list")
        await arbiter._execute_on_worker(1234, request, client_writer)

        assert len(client_writer.messages) == 1
        assert client_writer.messages[0]["type"] == "response"
        assert client_writer.messages[0]["result"] == [1, 2, 3, 4, 5]

    @pytest.mark.asyncio
    async def test_handles_error_response(self):
        """Test that error responses still work."""
        arbiter = create_arbiter()
        client_writer = MockStreamWriter()

        error = make_error_response(123, DirtyError("Something failed"))
        mock_reader = MockStreamReader([error])

        async def mock_get_connection(pid):
            return mock_reader, MockStreamWriter()

        arbiter._get_worker_connection = mock_get_connection

        request = make_request(123, "test:App", "fail")
        await arbiter._execute_on_worker(1234, request, client_writer)

        assert len(client_writer.messages) == 1
        assert client_writer.messages[0]["type"] == "error"
