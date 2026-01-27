#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for dirty worker streaming functionality."""

import asyncio
import struct
from unittest import mock

import pytest

from gunicorn.dirty.protocol import (
    DirtyProtocol,
    make_request,
    make_chunk_message,
    make_end_message,
)
from gunicorn.dirty.worker import DirtyWorker


class FakeStreamWriter:
    """Mock StreamWriter that captures written messages."""

    def __init__(self):
        self.messages = []
        self._buffer = b""

    def write(self, data):
        self._buffer += data

    async def drain(self):
        # Decode the buffer to extract messages
        while len(self._buffer) >= DirtyProtocol.HEADER_SIZE:
            length = struct.unpack(
                DirtyProtocol.HEADER_FORMAT,
                self._buffer[:DirtyProtocol.HEADER_SIZE]
            )[0]
            total_size = DirtyProtocol.HEADER_SIZE + length
            if len(self._buffer) >= total_size:
                msg_data = self._buffer[DirtyProtocol.HEADER_SIZE:total_size]
                self._buffer = self._buffer[total_size:]
                self.messages.append(DirtyProtocol.decode(msg_data))
            else:
                break

    def close(self):
        pass

    async def wait_closed(self):
        pass


def create_worker():
    """Create a test worker with mocked components."""
    cfg = mock.Mock()
    cfg.dirty_timeout = 30
    cfg.dirty_threads = 1
    cfg.env = None
    cfg.uid = None
    cfg.gid = None
    cfg.initgroups = False
    cfg.dirty_worker_init = mock.Mock()
    cfg.umask = 0o22

    log = mock.Mock()

    with mock.patch('gunicorn.dirty.worker.WorkerTmp'):
        worker = DirtyWorker(
            age=1,
            ppid=1,
            app_paths=["test:App"],
            cfg=cfg,
            log=log,
            socket_path="/tmp/test.sock"
        )

    worker.apps = {}
    worker._executor = None  # Use default executor for sync generator tests
    worker.tmp = mock.Mock()

    return worker


class TestWorkerSyncGeneratorStreaming:
    """Tests for sync generator streaming."""

    @pytest.mark.asyncio
    async def test_sync_generator_sends_chunks_and_end(self):
        """Test that sync generator sends chunk messages then end message."""
        def generate_tokens():
            yield "Hello"
            yield " "
            yield "World"

        worker = create_worker()
        writer = FakeStreamWriter()

        # Mock execute to return the sync generator directly
        async def mock_execute(app_path, action, args, kwargs):
            return generate_tokens()

        with mock.patch.object(worker, 'execute', side_effect=mock_execute):
            request = make_request("req-123", "test:App", "generate")
            await worker.handle_request(request, writer)

        # Should have 3 chunks + 1 end message
        assert len(writer.messages) == 4

        # Check chunk messages
        assert writer.messages[0]["type"] == "chunk"
        assert writer.messages[0]["id"] == "req-123"
        assert writer.messages[0]["data"] == "Hello"

        assert writer.messages[1]["type"] == "chunk"
        assert writer.messages[1]["data"] == " "

        assert writer.messages[2]["type"] == "chunk"
        assert writer.messages[2]["data"] == "World"

        # Check end message
        assert writer.messages[3]["type"] == "end"
        assert writer.messages[3]["id"] == "req-123"

    @pytest.mark.asyncio
    async def test_sync_generator_error_mid_stream(self):
        """Test that error during streaming sends error message."""
        def generate_with_error():
            yield "First"
            raise ValueError("Something went wrong")

        worker = create_worker()
        writer = FakeStreamWriter()

        async def mock_execute(app_path, action, args, kwargs):
            return generate_with_error()

        with mock.patch.object(worker, 'execute', side_effect=mock_execute):
            request = make_request("req-123", "test:App", "generate")
            await worker.handle_request(request, writer)

        # Should have 1 chunk + 1 error message
        assert len(writer.messages) == 2

        assert writer.messages[0]["type"] == "chunk"
        assert writer.messages[0]["data"] == "First"

        assert writer.messages[1]["type"] == "error"
        assert "Something went wrong" in writer.messages[1]["error"]["message"]


class TestWorkerAsyncGeneratorStreaming:
    """Tests for async generator streaming."""

    @pytest.mark.asyncio
    async def test_async_generator_sends_chunks_and_end(self):
        """Test that async generator sends chunk messages then end message."""
        async def async_generate_tokens():
            yield "Hello"
            yield " "
            yield "World"

        worker = create_worker()
        writer = FakeStreamWriter()

        async def mock_execute(app_path, action, args, kwargs):
            return async_generate_tokens()

        with mock.patch.object(worker, 'execute', side_effect=mock_execute):
            request = make_request("req-123", "test:App", "generate")
            await worker.handle_request(request, writer)

        # Should have 3 chunks + 1 end message
        assert len(writer.messages) == 4

        # Check chunk messages
        assert writer.messages[0]["type"] == "chunk"
        assert writer.messages[0]["id"] == "req-123"
        assert writer.messages[0]["data"] == "Hello"

        assert writer.messages[1]["type"] == "chunk"
        assert writer.messages[1]["data"] == " "

        assert writer.messages[2]["type"] == "chunk"
        assert writer.messages[2]["data"] == "World"

        # Check end message
        assert writer.messages[3]["type"] == "end"
        assert writer.messages[3]["id"] == "req-123"

    @pytest.mark.asyncio
    async def test_async_generator_error_mid_stream(self):
        """Test that error during async streaming sends error message."""
        async def async_generate_with_error():
            yield "First"
            raise ValueError("Async error")

        worker = create_worker()
        writer = FakeStreamWriter()

        async def mock_execute(app_path, action, args, kwargs):
            return async_generate_with_error()

        with mock.patch.object(worker, 'execute', side_effect=mock_execute):
            request = make_request("req-123", "test:App", "generate")
            await worker.handle_request(request, writer)

        # Should have 1 chunk + 1 error message
        assert len(writer.messages) == 2

        assert writer.messages[0]["type"] == "chunk"
        assert writer.messages[0]["data"] == "First"

        assert writer.messages[1]["type"] == "error"
        assert "Async error" in writer.messages[1]["error"]["message"]


class TestWorkerNonStreamingBackwardCompat:
    """Tests for backward compatibility with non-streaming responses."""

    @pytest.mark.asyncio
    async def test_non_generator_returns_response(self):
        """Test that non-generator method returns regular response."""
        worker = create_worker()
        writer = FakeStreamWriter()

        async def mock_execute(app_path, action, args, kwargs):
            return args[0] + args[1]

        with mock.patch.object(worker, 'execute', side_effect=mock_execute):
            request = make_request("req-123", "test:App", "compute", args=(2, 3))
            await worker.handle_request(request, writer)

        # Should have 1 response message
        assert len(writer.messages) == 1
        assert writer.messages[0]["type"] == "response"
        assert writer.messages[0]["id"] == "req-123"
        assert writer.messages[0]["result"] == 5

    @pytest.mark.asyncio
    async def test_list_result_not_treated_as_streaming(self):
        """Test that list result is not treated as streaming."""
        worker = create_worker()
        writer = FakeStreamWriter()

        async def mock_execute(app_path, action, args, kwargs):
            return [1, 2, 3, 4, 5]

        with mock.patch.object(worker, 'execute', side_effect=mock_execute):
            request = make_request("req-123", "test:App", "get_list")
            await worker.handle_request(request, writer)

        # Should have 1 response message (not 5 chunks)
        assert len(writer.messages) == 1
        assert writer.messages[0]["type"] == "response"
        assert writer.messages[0]["result"] == [1, 2, 3, 4, 5]

    @pytest.mark.asyncio
    async def test_error_in_execute_sends_error(self):
        """Test that error in execute sends error response."""
        worker = create_worker()
        writer = FakeStreamWriter()

        async def mock_execute(app_path, action, args, kwargs):
            raise RuntimeError("Failed!")

        with mock.patch.object(worker, 'execute', side_effect=mock_execute):
            request = make_request("req-123", "test:App", "fail")
            await worker.handle_request(request, writer)

        # Should have 1 error message
        assert len(writer.messages) == 1
        assert writer.messages[0]["type"] == "error"
        assert "Failed!" in writer.messages[0]["error"]["message"]

    @pytest.mark.asyncio
    async def test_none_result(self):
        """Test that None result works correctly."""
        worker = create_worker()
        writer = FakeStreamWriter()

        async def mock_execute(app_path, action, args, kwargs):
            return None

        with mock.patch.object(worker, 'execute', side_effect=mock_execute):
            request = make_request("req-123", "test:App", "void")
            await worker.handle_request(request, writer)

        # Should have 1 response message
        assert len(writer.messages) == 1
        assert writer.messages[0]["type"] == "response"
        assert writer.messages[0]["result"] is None


class TestWorkerStreamingComplexData:
    """Tests for streaming with complex data types."""

    @pytest.mark.asyncio
    async def test_streaming_dict_chunks(self):
        """Test streaming chunks that are dictionaries."""
        async def generate_tokens():
            yield {"token": "Hello", "score": 0.9}
            yield {"token": "World", "score": 0.8}

        worker = create_worker()
        writer = FakeStreamWriter()

        async def mock_execute(app_path, action, args, kwargs):
            return generate_tokens()

        with mock.patch.object(worker, 'execute', side_effect=mock_execute):
            request = make_request("req-123", "test:App", "generate")
            await worker.handle_request(request, writer)

        assert len(writer.messages) == 3  # 2 chunks + 1 end

        assert writer.messages[0]["data"]["token"] == "Hello"
        assert writer.messages[0]["data"]["score"] == 0.9
        assert writer.messages[1]["data"]["token"] == "World"

    @pytest.mark.asyncio
    async def test_streaming_empty_generator(self):
        """Test streaming with empty generator."""
        async def empty_generate():
            return
            yield  # Make it a generator

        worker = create_worker()
        writer = FakeStreamWriter()

        async def mock_execute(app_path, action, args, kwargs):
            return empty_generate()

        with mock.patch.object(worker, 'execute', side_effect=mock_execute):
            request = make_request("req-123", "test:App", "generate")
            await worker.handle_request(request, writer)

        # Should have just 1 end message
        assert len(writer.messages) == 1
        assert writer.messages[0]["type"] == "end"

    @pytest.mark.asyncio
    async def test_streaming_many_chunks(self):
        """Test streaming with many chunks."""
        async def generate_many():
            for i in range(100):
                yield f"chunk-{i}"

        worker = create_worker()
        writer = FakeStreamWriter()

        async def mock_execute(app_path, action, args, kwargs):
            return generate_many()

        with mock.patch.object(worker, 'execute', side_effect=mock_execute):
            request = make_request("req-123", "test:App", "generate")
            await worker.handle_request(request, writer)

        # Should have 100 chunks + 1 end message
        assert len(writer.messages) == 101
        assert writer.messages[0]["data"] == "chunk-0"
        assert writer.messages[99]["data"] == "chunk-99"
        assert writer.messages[100]["type"] == "end"


class TestWorkerStreamingHeartbeat:
    """Tests for heartbeat updates during streaming."""

    @pytest.mark.asyncio
    async def test_heartbeat_updated_during_streaming(self):
        """Test that heartbeat is updated during streaming."""
        async def generate_tokens():
            yield "Hello"
            yield "World"

        worker = create_worker()
        writer = FakeStreamWriter()

        # Track notify calls
        notify_count = [0]
        original_notify = worker.notify

        def counting_notify():
            notify_count[0] += 1
            return original_notify() if callable(original_notify) else None

        worker.notify = counting_notify

        async def mock_execute(app_path, action, args, kwargs):
            return generate_tokens()

        with mock.patch.object(worker, 'execute', side_effect=mock_execute):
            request = make_request("req-123", "test:App", "generate")
            await worker.handle_request(request, writer)

        # Should have been notified at least once per chunk + initial
        assert notify_count[0] >= 2  # At least one per chunk


class TestWorkerMessageTypeValidation:
    """Tests for message type validation."""

    @pytest.mark.asyncio
    async def test_unknown_message_type_sends_error(self):
        """Test that unknown message type sends error response."""
        worker = create_worker()
        writer = FakeStreamWriter()

        # Send a message with unknown type
        message = {"type": "unknown", "id": "req-123"}
        await worker.handle_request(message, writer)

        assert len(writer.messages) == 1
        assert writer.messages[0]["type"] == "error"
        assert "Unknown message type" in writer.messages[0]["error"]["message"]
