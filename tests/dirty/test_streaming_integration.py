#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Integration tests for dirty streaming functionality.

These tests verify the full streaming pipeline:
client -> arbiter -> worker -> generator -> chunks -> client
"""

import asyncio
import os
import struct
import tempfile
import pytest
from unittest import mock

from gunicorn.config import Config
from gunicorn.dirty.protocol import (
    DirtyProtocol,
    BinaryProtocol,
    make_request,
    make_chunk_message,
    make_end_message,
    make_response,
    make_error_response,
    HEADER_SIZE,
)
from gunicorn.dirty.worker import DirtyWorker
from gunicorn.dirty.arbiter import DirtyArbiter
from gunicorn.dirty.client import DirtyClient
from gunicorn.dirty.errors import DirtyError


class MockLog:
    """Mock logger for testing."""

    def __init__(self):
        self.messages = []

    def debug(self, msg, *args):
        self.messages.append(("debug", msg % args if args else msg))

    def info(self, msg, *args):
        self.messages.append(("info", msg % args if args else msg))

    def warning(self, msg, *args):
        self.messages.append(("warning", msg % args if args else msg))

    def error(self, msg, *args):
        self.messages.append(("error", msg % args if args else msg))

    def close_on_exec(self):
        pass

    def reopen_files(self):
        pass


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


class TestStreamingEndToEnd:
    """End-to-end streaming tests using mocked components."""

    @pytest.mark.asyncio
    async def test_sync_generator_end_to_end(self):
        """Test complete flow: sync generator -> worker -> arbiter -> client."""
        # Simulate what a worker would produce for a sync generator
        worker_messages = [
            make_chunk_message(123, "Hello"),
            make_chunk_message(123, " "),
            make_chunk_message(123, "World"),
            make_end_message(123),
        ]

        # Create an arbiter with mocked worker connection
        cfg = Config()
        cfg.set("dirty_timeout", 30)
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.alive = True
        arbiter.workers = {1234: mock.Mock()}
        arbiter.worker_sockets = {1234: '/tmp/worker.sock'}

        # Mock worker connection
        mock_reader = MockStreamReader(worker_messages)
        async def mock_get_connection(pid):
            return mock_reader, MockStreamWriter()
        arbiter._get_worker_connection = mock_get_connection

        # Create client writer to capture messages
        client_writer = MockStreamWriter()

        # Execute request through arbiter
        request = make_request(123, "test:App", "generate")
        await arbiter._execute_on_worker(1234, request, client_writer)

        # Verify all messages were forwarded
        assert len(client_writer.messages) == 4
        assert client_writer.messages[0]["type"] == "chunk"
        assert client_writer.messages[0]["data"] == "Hello"
        assert client_writer.messages[1]["data"] == " "
        assert client_writer.messages[2]["data"] == "World"
        assert client_writer.messages[3]["type"] == "end"

        arbiter._cleanup_sync()

    @pytest.mark.asyncio
    async def test_async_generator_end_to_end(self):
        """Test complete flow: async generator -> worker -> arbiter -> client."""
        worker_messages = [
            make_chunk_message(456, "Async"),
            make_chunk_message(456, " "),
            make_chunk_message(456, "Stream"),
            make_end_message(456),
        ]

        cfg = Config()
        cfg.set("dirty_timeout", 30)
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.alive = True
        arbiter.workers = {1234: mock.Mock()}
        arbiter.worker_sockets = {1234: '/tmp/worker.sock'}

        mock_reader = MockStreamReader(worker_messages)
        async def mock_get_connection(pid):
            return mock_reader, MockStreamWriter()
        arbiter._get_worker_connection = mock_get_connection

        client_writer = MockStreamWriter()

        request = make_request(456, "test:App", "async_generate")
        await arbiter._execute_on_worker(1234, request, client_writer)

        assert len(client_writer.messages) == 4
        assert client_writer.messages[0]["data"] == "Async"
        assert client_writer.messages[3]["type"] == "end"

        arbiter._cleanup_sync()


class TestStreamingErrorHandling:
    """Tests for error handling during streaming."""

    @pytest.mark.asyncio
    async def test_error_mid_stream(self):
        """Test that errors during streaming are properly forwarded."""
        worker_messages = [
            make_chunk_message(789, "First"),
            make_chunk_message(789, "Second"),
            make_error_response(789, DirtyError("Stream failed")),
        ]

        cfg = Config()
        cfg.set("dirty_timeout", 30)
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.alive = True
        arbiter.workers = {1234: mock.Mock()}
        arbiter.worker_sockets = {1234: '/tmp/worker.sock'}

        mock_reader = MockStreamReader(worker_messages)
        async def mock_get_connection(pid):
            return mock_reader, MockStreamWriter()
        arbiter._get_worker_connection = mock_get_connection

        client_writer = MockStreamWriter()

        request = make_request(789, "test:App", "generate_with_error")
        await arbiter._execute_on_worker(1234, request, client_writer)

        # Should have 2 chunks + 1 error
        assert len(client_writer.messages) == 3
        assert client_writer.messages[0]["type"] == "chunk"
        assert client_writer.messages[1]["type"] == "chunk"
        assert client_writer.messages[2]["type"] == "error"
        assert "Stream failed" in client_writer.messages[2]["error"]["message"]

        arbiter._cleanup_sync()


class TestStreamingBackwardCompatibility:
    """Tests for backward compatibility with non-streaming responses."""

    @pytest.mark.asyncio
    async def test_non_streaming_response_still_works(self):
        """Test that regular (non-streaming) responses still work."""
        worker_messages = [
            make_response("req-abc", {"result": 42, "data": [1, 2, 3]}),
        ]

        cfg = Config()
        cfg.set("dirty_timeout", 30)
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.alive = True
        arbiter.workers = {1234: mock.Mock()}
        arbiter.worker_sockets = {1234: '/tmp/worker.sock'}

        mock_reader = MockStreamReader(worker_messages)
        async def mock_get_connection(pid):
            return mock_reader, MockStreamWriter()
        arbiter._get_worker_connection = mock_get_connection

        client_writer = MockStreamWriter()

        request = make_request("req-abc", "test:App", "compute")
        await arbiter._execute_on_worker(1234, request, client_writer)

        # Should have 1 response
        assert len(client_writer.messages) == 1
        assert client_writer.messages[0]["type"] == "response"
        assert client_writer.messages[0]["result"]["result"] == 42

        arbiter._cleanup_sync()

    @pytest.mark.asyncio
    async def test_error_response_still_works(self):
        """Test that error responses still work."""
        worker_messages = [
            make_error_response("req-def", DirtyError("Something failed")),
        ]

        cfg = Config()
        cfg.set("dirty_timeout", 30)
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.alive = True
        arbiter.workers = {1234: mock.Mock()}
        arbiter.worker_sockets = {1234: '/tmp/worker.sock'}

        mock_reader = MockStreamReader(worker_messages)
        async def mock_get_connection(pid):
            return mock_reader, MockStreamWriter()
        arbiter._get_worker_connection = mock_get_connection

        client_writer = MockStreamWriter()

        request = make_request("req-def", "test:App", "fail")
        await arbiter._execute_on_worker(1234, request, client_writer)

        assert len(client_writer.messages) == 1
        assert client_writer.messages[0]["type"] == "error"

        arbiter._cleanup_sync()


class TestStreamingWorkerIntegration:
    """Integration tests for worker streaming with execute."""

    @pytest.mark.asyncio
    async def test_worker_handles_sync_generator(self):
        """Test worker properly handles sync generator from execute."""
        cfg = Config()
        cfg.set("dirty_timeout", 300)
        log = MockLog()

        with mock.patch('gunicorn.dirty.worker.WorkerTmp'):
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=["test:App"],
                cfg=cfg,
                log=log,
                socket_path="/tmp/test.sock"
            )

        worker.apps = {}
        worker._executor = None
        worker.tmp = mock.Mock()

        writer = MockStreamWriter()

        # Mock execute to return a sync generator
        def sync_gen():
            yield "one"
            yield "two"
            yield "three"

        async def mock_execute(app_path, action, args, kwargs):
            return sync_gen()

        with mock.patch.object(worker, 'execute', side_effect=mock_execute):
            request = make_request(123, "test:App", "generate")
            await worker.handle_request(request, writer)

        # Should have 3 chunks + 1 end
        assert len(writer.messages) == 4
        assert writer.messages[0]["data"] == "one"
        assert writer.messages[1]["data"] == "two"
        assert writer.messages[2]["data"] == "three"
        assert writer.messages[3]["type"] == "end"

    @pytest.mark.asyncio
    async def test_worker_handles_async_generator(self):
        """Test worker properly handles async generator from execute."""
        cfg = Config()
        cfg.set("dirty_timeout", 300)
        log = MockLog()

        with mock.patch('gunicorn.dirty.worker.WorkerTmp'):
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=["test:App"],
                cfg=cfg,
                log=log,
                socket_path="/tmp/test.sock"
            )

        worker.apps = {}
        worker._executor = None
        worker.tmp = mock.Mock()

        writer = MockStreamWriter()

        # Mock execute to return an async generator
        async def async_gen():
            yield "async_one"
            yield "async_two"

        async def mock_execute(app_path, action, args, kwargs):
            return async_gen()

        with mock.patch.object(worker, 'execute', side_effect=mock_execute):
            request = make_request(456, "test:App", "async_generate")
            await worker.handle_request(request, writer)

        # Should have 2 chunks + 1 end
        assert len(writer.messages) == 3
        assert writer.messages[0]["data"] == "async_one"
        assert writer.messages[1]["data"] == "async_two"
        assert writer.messages[2]["type"] == "end"


class TestStreamingMixedScenarios:
    """Tests for mixed streaming scenarios."""

    @pytest.mark.asyncio
    async def test_large_stream(self):
        """Test streaming with many chunks."""
        worker_messages = []
        for i in range(500):
            worker_messages.append(make_chunk_message("req-large", f"chunk-{i}"))
        worker_messages.append(make_end_message("req-large"))

        cfg = Config()
        cfg.set("dirty_timeout", 30)
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.alive = True
        arbiter.workers = {1234: mock.Mock()}
        arbiter.worker_sockets = {1234: '/tmp/worker.sock'}

        mock_reader = MockStreamReader(worker_messages)
        async def mock_get_connection(pid):
            return mock_reader, MockStreamWriter()
        arbiter._get_worker_connection = mock_get_connection

        client_writer = MockStreamWriter()

        request = make_request("req-large", "test:App", "large_stream")
        await arbiter._execute_on_worker(1234, request, client_writer)

        # Should have 500 chunks + 1 end
        assert len(client_writer.messages) == 501
        assert client_writer.messages[0]["data"] == "chunk-0"
        assert client_writer.messages[499]["data"] == "chunk-499"
        assert client_writer.messages[500]["type"] == "end"

        arbiter._cleanup_sync()

    @pytest.mark.asyncio
    async def test_stream_with_complex_data(self):
        """Test streaming with complex JSON-serializable data."""
        worker_messages = [
            make_chunk_message("req-complex", {
                "token": "Hello",
                "scores": [0.1, 0.2, 0.3],
                "metadata": {"position": 0}
            }),
            make_chunk_message("req-complex", {
                "token": "World",
                "scores": [0.4, 0.5],
                "metadata": {"position": 1}
            }),
            make_end_message("req-complex"),
        ]

        cfg = Config()
        cfg.set("dirty_timeout", 30)
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.alive = True
        arbiter.workers = {1234: mock.Mock()}
        arbiter.worker_sockets = {1234: '/tmp/worker.sock'}

        mock_reader = MockStreamReader(worker_messages)
        async def mock_get_connection(pid):
            return mock_reader, MockStreamWriter()
        arbiter._get_worker_connection = mock_get_connection

        client_writer = MockStreamWriter()

        request = make_request("req-complex", "test:App", "complex_stream")
        await arbiter._execute_on_worker(1234, request, client_writer)

        assert len(client_writer.messages) == 3
        assert client_writer.messages[0]["data"]["token"] == "Hello"
        assert client_writer.messages[0]["data"]["scores"] == [0.1, 0.2, 0.3]
        assert client_writer.messages[1]["data"]["metadata"]["position"] == 1

        arbiter._cleanup_sync()
