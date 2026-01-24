#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for routing requests to multiple dirty apps.

This module verifies that when multiple dirty apps are configured,
messages are correctly routed to the appropriate app based on app_path.
"""

import asyncio
import os
import struct
import tempfile
import pytest

from concurrent.futures import ThreadPoolExecutor

from gunicorn.config import Config
from gunicorn.dirty.worker import DirtyWorker
from gunicorn.dirty.arbiter import DirtyArbiter
from gunicorn.dirty.protocol import DirtyProtocol, make_request
from gunicorn.dirty.errors import DirtyAppNotFoundError


# App paths for test apps
COUNTER_APP_PATH = "tests.support_dirty_apps:CounterApp"
ECHO_APP_PATH = "tests.support_dirty_apps:EchoApp"


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

    def critical(self, msg, *args):
        self.messages.append(("critical", msg % args if args else msg))

    def exception(self, msg, *args):
        self.messages.append(("exception", msg % args if args else msg))

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
        self.closed = True

    async def wait_closed(self):
        pass

    def get_extra_info(self, name):
        return None


class TestWorkerMultiAppLoading:
    """Tests for loading multiple apps in a worker."""

    def test_worker_loads_multiple_apps(self):
        """Test that worker loads all configured apps."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[COUNTER_APP_PATH, ECHO_APP_PATH],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            worker.load_apps()

            # Both apps should be loaded
            assert COUNTER_APP_PATH in worker.apps
            assert ECHO_APP_PATH in worker.apps

            # Apps should be initialized
            counter_app = worker.apps[COUNTER_APP_PATH]
            echo_app = worker.apps[ECHO_APP_PATH]
            assert counter_app.initialized is True
            assert echo_app.initialized is True

            worker._cleanup()

    def test_worker_apps_are_distinct_instances(self):
        """Test that each app is a distinct instance."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[COUNTER_APP_PATH, ECHO_APP_PATH],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            worker.load_apps()

            counter_app = worker.apps[COUNTER_APP_PATH]
            echo_app = worker.apps[ECHO_APP_PATH]

            # They should be different instances
            assert counter_app is not echo_app

            # They should be different types
            assert type(counter_app).__name__ == "CounterApp"
            assert type(echo_app).__name__ == "EchoApp"

            worker._cleanup()


class TestWorkerMultiAppRouting:
    """Tests for routing requests to correct app based on app_path."""

    @pytest.mark.asyncio
    async def test_worker_routes_to_counter_app(self):
        """Test that worker routes request to CounterApp correctly."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[COUNTER_APP_PATH, ECHO_APP_PATH],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            worker.load_apps()
            worker._executor = ThreadPoolExecutor(max_workers=1)

            try:
                # Call increment on CounterApp
                result = await worker.execute(
                    COUNTER_APP_PATH, "increment", [], {"amount": 5}
                )
                assert result == 5

                # Call get_value on CounterApp
                result = await worker.execute(
                    COUNTER_APP_PATH, "get_value", [], {}
                )
                assert result == 5
            finally:
                worker._cleanup()

    @pytest.mark.asyncio
    async def test_worker_routes_to_echo_app(self):
        """Test that worker routes request to EchoApp correctly."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[COUNTER_APP_PATH, ECHO_APP_PATH],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            worker.load_apps()
            worker._executor = ThreadPoolExecutor(max_workers=1)

            try:
                # Call echo on EchoApp
                result = await worker.execute(
                    ECHO_APP_PATH, "echo", ["hello"], {}
                )
                assert result == "ECHO: hello"

                # Set new prefix
                result = await worker.execute(
                    ECHO_APP_PATH, "set_prefix", ["TEST>"], {}
                )
                assert result == "TEST>"

                # Echo with new prefix
                result = await worker.execute(
                    ECHO_APP_PATH, "echo", ["world"], {}
                )
                assert result == "TEST> world"
            finally:
                worker._cleanup()

    @pytest.mark.asyncio
    async def test_worker_routes_mixed_requests(self):
        """Test routing interleaved requests to different apps."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[COUNTER_APP_PATH, ECHO_APP_PATH],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            worker.load_apps()
            worker._executor = ThreadPoolExecutor(max_workers=1)

            try:
                # Interleave calls to both apps
                result = await worker.execute(
                    COUNTER_APP_PATH, "increment", [1], {}
                )
                assert result == 1

                result = await worker.execute(
                    ECHO_APP_PATH, "echo", ["first"], {}
                )
                assert result == "ECHO: first"

                result = await worker.execute(
                    COUNTER_APP_PATH, "increment", [2], {}
                )
                assert result == 3

                result = await worker.execute(
                    ECHO_APP_PATH, "echo", ["second"], {}
                )
                assert result == "ECHO: second"

                # Verify final state of each app
                result = await worker.execute(
                    COUNTER_APP_PATH, "get_value", [], {}
                )
                assert result == 3

                result = await worker.execute(
                    ECHO_APP_PATH, "get_echo_count", [], {}
                )
                assert result == 2
            finally:
                worker._cleanup()


class TestAppStateSeparation:
    """Tests for verifying apps maintain independent state."""

    @pytest.mark.asyncio
    async def test_apps_maintain_separate_state(self):
        """Test that multiple apps maintain independent state."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[COUNTER_APP_PATH, ECHO_APP_PATH],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            worker.load_apps()
            worker._executor = ThreadPoolExecutor(max_workers=1)

            try:
                # Modify CounterApp state
                await worker.execute(COUNTER_APP_PATH, "increment", [10], {})
                await worker.execute(COUNTER_APP_PATH, "increment", [5], {})

                # Modify EchoApp state
                await worker.execute(ECHO_APP_PATH, "set_prefix", ["CUSTOM:"], {})
                await worker.execute(ECHO_APP_PATH, "echo", ["msg1"], {})
                await worker.execute(ECHO_APP_PATH, "echo", ["msg2"], {})

                # Verify CounterApp state is independent
                counter_val = await worker.execute(
                    COUNTER_APP_PATH, "get_value", [], {}
                )
                assert counter_val == 15

                # Verify EchoApp state is independent
                prefix = await worker.execute(
                    ECHO_APP_PATH, "get_prefix", [], {}
                )
                assert prefix == "CUSTOM:"

                echo_count = await worker.execute(
                    ECHO_APP_PATH, "get_echo_count", [], {}
                )
                assert echo_count == 2

                # Reset CounterApp and verify EchoApp unaffected
                await worker.execute(COUNTER_APP_PATH, "reset", [], {})

                counter_val = await worker.execute(
                    COUNTER_APP_PATH, "get_value", [], {}
                )
                assert counter_val == 0

                # EchoApp should be unaffected
                echo_count = await worker.execute(
                    ECHO_APP_PATH, "get_echo_count", [], {}
                )
                assert echo_count == 2
            finally:
                worker._cleanup()


class TestUnknownAppPath:
    """Tests for handling unknown app paths."""

    @pytest.mark.asyncio
    async def test_unknown_app_path_raises_error(self):
        """Test that unknown app_path raises DirtyAppNotFoundError."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[COUNTER_APP_PATH, ECHO_APP_PATH],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            worker.load_apps()
            worker._executor = ThreadPoolExecutor(max_workers=1)

            try:
                with pytest.raises(DirtyAppNotFoundError):
                    await worker.execute(
                        "nonexistent:App", "action", [], {}
                    )
            finally:
                worker._cleanup()

    @pytest.mark.asyncio
    async def test_handle_request_unknown_app_returns_error(self):
        """Test that handle_request returns error for unknown app."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[COUNTER_APP_PATH],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            worker.load_apps()
            worker._executor = ThreadPoolExecutor(max_workers=1)

            try:
                request = make_request(
                    request_id="test-unknown",
                    app_path="unknown:App",
                    action="test"
                )

                writer = MockStreamWriter()
                await worker.handle_request(request, writer)

                assert len(writer.messages) == 1
                response = writer.messages[0]
                assert response["type"] == DirtyProtocol.MSG_TYPE_ERROR
                assert "unknown:App" in response["error"]["message"]
            finally:
                worker._cleanup()


class TestConcurrentMultiAppRequests:
    """Tests for concurrent requests to different apps."""

    @pytest.mark.asyncio
    async def test_concurrent_requests_to_different_apps(self):
        """Test concurrent requests routed to different apps."""
        cfg = Config()
        cfg.set("dirty_threads", 4)  # Allow concurrent execution
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[COUNTER_APP_PATH, ECHO_APP_PATH],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            worker.load_apps()
            worker._executor = ThreadPoolExecutor(max_workers=4)

            try:
                # Create concurrent tasks for both apps
                tasks = [
                    worker.execute(COUNTER_APP_PATH, "increment", [1], {}),
                    worker.execute(ECHO_APP_PATH, "echo", ["msg1"], {}),
                    worker.execute(COUNTER_APP_PATH, "increment", [2], {}),
                    worker.execute(ECHO_APP_PATH, "echo", ["msg2"], {}),
                    worker.execute(COUNTER_APP_PATH, "increment", [3], {}),
                    worker.execute(ECHO_APP_PATH, "echo", ["msg3"], {}),
                ]

                results = await asyncio.gather(*tasks)

                # Verify echo results are correct (regardless of order)
                echo_results = [r for r in results if isinstance(r, str)]
                assert len(echo_results) == 3
                assert all(r.startswith("ECHO:") for r in echo_results)

                # Counter results will vary based on execution order
                # but final state should reflect all increments
                counter_val = await worker.execute(
                    COUNTER_APP_PATH, "get_value", [], {}
                )
                assert counter_val == 6  # 1 + 2 + 3
            finally:
                worker._cleanup()


class TestMultiAppProtocolHandling:
    """Tests for protocol-level handling of multi-app requests."""

    @pytest.mark.asyncio
    async def test_handle_request_routes_correctly(self):
        """Test handle_request routes to correct app via protocol."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[COUNTER_APP_PATH, ECHO_APP_PATH],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            worker.load_apps()
            worker._executor = ThreadPoolExecutor(max_workers=1)

            try:
                # Request to CounterApp
                request1 = make_request(
                    request_id="req-counter",
                    app_path=COUNTER_APP_PATH,
                    action="increment",
                    args=[5]
                )
                writer1 = MockStreamWriter()
                await worker.handle_request(request1, writer1)

                assert len(writer1.messages) == 1
                assert writer1.messages[0]["type"] == DirtyProtocol.MSG_TYPE_RESPONSE
                assert writer1.messages[0]["result"] == 5

                # Request to EchoApp
                request2 = make_request(
                    request_id="req-echo",
                    app_path=ECHO_APP_PATH,
                    action="echo",
                    args=["test message"]
                )
                writer2 = MockStreamWriter()
                await worker.handle_request(request2, writer2)

                assert len(writer2.messages) == 1
                assert writer2.messages[0]["type"] == DirtyProtocol.MSG_TYPE_RESPONSE
                assert writer2.messages[0]["result"] == "ECHO: test message"
            finally:
                worker._cleanup()


class TestMultiAppCleanup:
    """Tests for cleanup of multiple apps."""

    def test_cleanup_closes_all_apps(self):
        """Test that cleanup closes all loaded apps."""
        cfg = Config()
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=[COUNTER_APP_PATH, ECHO_APP_PATH],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )

            worker.load_apps()

            counter_app = worker.apps[COUNTER_APP_PATH]
            echo_app = worker.apps[ECHO_APP_PATH]

            assert counter_app.closed is False
            assert echo_app.closed is False

            worker._cleanup()

            assert counter_app.closed is True
            assert echo_app.closed is True


class TestMultiAppArbiterIntegration:
    """Tests for arbiter routing with multiple apps configured."""

    @pytest.mark.asyncio
    async def test_arbiter_routes_no_workers_error(self):
        """Test arbiter returns error when no workers for multi-app config."""
        cfg = Config()
        cfg.set("dirty_workers", 0)
        cfg.set("dirty_apps", [COUNTER_APP_PATH, ECHO_APP_PATH])
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.pid = os.getpid()

        try:
            # Request to CounterApp - should fail (no workers)
            request = make_request(
                request_id="test-counter",
                app_path=COUNTER_APP_PATH,
                action="increment"
            )

            writer = MockStreamWriter()
            await arbiter.route_request(request, writer)

            assert len(writer.messages) == 1
            response = writer.messages[0]
            assert response["type"] == DirtyProtocol.MSG_TYPE_ERROR
            assert "No dirty workers available" in response["error"]["message"]
        finally:
            arbiter._cleanup_sync()

    def test_arbiter_config_has_multiple_apps(self):
        """Test arbiter config correctly stores multiple apps."""
        cfg = Config()
        cfg.set("dirty_apps", [COUNTER_APP_PATH, ECHO_APP_PATH])
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)

        try:
            app_paths = arbiter.cfg.dirty_apps
            assert COUNTER_APP_PATH in app_paths
            assert ECHO_APP_PATH in app_paths
            assert len(app_paths) == 2
        finally:
            arbiter._cleanup_sync()
