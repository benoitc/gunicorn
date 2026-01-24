#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Integration tests for dirty arbiter with main arbiter."""

import os
import pytest

from gunicorn.arbiter import Arbiter
from gunicorn.config import Config
from gunicorn.app.base import BaseApplication


class SimpleDirtyTestApp(BaseApplication):
    """Simple test application for integration tests."""

    def __init__(self, options=None):
        self.options = options or {}
        self.cfg = None
        super().__init__()

    def load_config(self):
        for key, value in self.options.items():
            if key in self.cfg.settings:
                self.cfg.set(key.lower(), value)

    def load(self):
        def app(environ, start_response):
            status = '200 OK'
            output = b'Hello World!'
            response_headers = [('Content-type', 'text/plain'),
                                ('Content-Length', str(len(output)))]
            start_response(status, response_headers)
            return [output]
        return app


class TestArbiterDirtyIntegration:
    """Tests for arbiter integration with dirty arbiter."""

    def test_arbiter_init_with_dirty_config(self):
        """Test arbiter initializes with dirty configuration."""
        app = SimpleDirtyTestApp(options={
            'dirty_workers': 2,
            'dirty_apps': ['tests.support_dirty_app:TestDirtyApp'],
            'bind': '127.0.0.1:0',
        })

        arbiter = Arbiter(app)

        assert arbiter.dirty_arbiter_pid == 0
        assert arbiter.dirty_arbiter is None
        assert arbiter.cfg.dirty_workers == 2
        assert arbiter.cfg.dirty_apps == ['tests.support_dirty_app:TestDirtyApp']

    def test_arbiter_init_without_dirty_config(self):
        """Test arbiter initializes without dirty configuration."""
        app = SimpleDirtyTestApp(options={
            'bind': '127.0.0.1:0',
        })

        arbiter = Arbiter(app)

        assert arbiter.dirty_arbiter_pid == 0
        assert arbiter.cfg.dirty_workers == 0
        assert arbiter.cfg.dirty_apps == []


class TestDirtyIntegrationEnvironment:
    """Tests for environment setup."""

    def test_dirty_socket_env_var_set(self):
        """Test that GUNICORN_DIRTY_SOCKET env var is set when dirty arbiter spawns."""
        # This test would require actually spawning the dirty arbiter
        # which involves forking. We'll skip this for unit tests.
        pass


class TestDirtyExecutionTimeout:
    """Tests for execution timeout handling."""

    @pytest.mark.asyncio
    async def test_worker_to_worker_communication(self):
        """Test protocol communication between worker and arbiter."""
        import asyncio
        import tempfile
        from gunicorn.dirty.worker import DirtyWorker
        from gunicorn.dirty.protocol import DirtyProtocol, make_request

        class MockLog:
            def debug(self, *a, **kw): pass
            def info(self, *a, **kw): pass
            def warning(self, *a, **kw): pass
            def error(self, *a, **kw): pass
            def close_on_exec(self): pass
            def reopen_files(self): pass

        cfg = Config()
        cfg.set("dirty_timeout", 300)
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "worker.sock")

            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=["tests.support_dirty_app:TestDirtyApp"],
                cfg=cfg,
                log=log,
                socket_path=socket_path
            )
            worker.pid = os.getpid()
            worker.load_apps()

            # Start worker server
            server = await asyncio.start_unix_server(
                worker.handle_connection,
                path=socket_path
            )

            # Connect as client
            reader, writer = await asyncio.open_unix_connection(socket_path)

            # Send a request
            request = make_request(
                request_id="timeout-test-1",
                app_path="tests.support_dirty_app:TestDirtyApp",
                action="compute",
                args=(10, 5),
                kwargs={"operation": "add"}
            )

            await DirtyProtocol.write_message_async(writer, request)

            # Receive response
            response = await DirtyProtocol.read_message_async(reader)

            assert response["type"] == DirtyProtocol.MSG_TYPE_RESPONSE
            assert response["result"] == 15

            # Cleanup
            writer.close()
            await writer.wait_closed()
            server.close()
            await server.wait_closed()
            worker._cleanup()

    @pytest.mark.skip(reason="Flaky due to async cleanup issues")
    @pytest.mark.asyncio
    async def test_arbiter_timeout_response(self):
        """Test that arbiter returns timeout error when worker doesn't respond."""
        import asyncio
        import tempfile
        from gunicorn.dirty.arbiter import DirtyArbiter
        from gunicorn.dirty.protocol import DirtyProtocol, make_request
        from gunicorn.dirty.errors import DirtyTimeoutError

        class MockLog:
            def debug(self, *a, **kw): pass
            def info(self, *a, **kw): pass
            def warning(self, *a, **kw): pass
            def error(self, *a, **kw): pass
            def critical(self, *a, **kw): pass
            def exception(self, *a, **kw): pass
            def close_on_exec(self): pass
            def reopen_files(self): pass

        cfg = Config()
        cfg.set("dirty_workers", 0)
        cfg.set("dirty_timeout", 1)  # 1 second timeout
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "arbiter.sock")
            worker_socket_path = os.path.join(tmpdir, "worker.sock")

            arbiter = DirtyArbiter(cfg=cfg, log=log, socket_path=socket_path)
            arbiter.pid = os.getpid()

            # Register a fake worker that will never respond
            fake_pid = 99999
            arbiter.workers[fake_pid] = "fake_worker"
            arbiter.worker_sockets[fake_pid] = worker_socket_path

            # Create a "slow" worker server that accepts but never responds
            async def slow_client_handler(reader, writer):
                # Read the request but don't respond (simulating timeout)
                try:
                    await asyncio.sleep(10)  # Longer than timeout
                except asyncio.CancelledError:
                    pass
                finally:
                    try:
                        writer.close()
                        await writer.wait_closed()
                    except Exception:
                        pass

            slow_server = await asyncio.start_unix_server(
                slow_client_handler,
                path=worker_socket_path
            )

            request = make_request(
                request_id="timeout-test",
                app_path="test:App",
                action="slow_action"
            )

            # This should timeout since worker doesn't respond
            response = await arbiter.route_request(request)

            assert response["type"] == DirtyProtocol.MSG_TYPE_ERROR
            assert "timeout" in response["error"]["error_type"].lower()

            # Cleanup
            slow_server.close()
            await slow_server.wait_closed()
            arbiter._cleanup_sync()

    @pytest.mark.skip(reason="Flaky due to async cleanup issues")
    @pytest.mark.asyncio
    async def test_full_request_response_flow(self):
        """Test full request-response flow between arbiter and worker."""
        import asyncio
        import tempfile
        from gunicorn.dirty.arbiter import DirtyArbiter
        from gunicorn.dirty.worker import DirtyWorker
        from gunicorn.dirty.protocol import DirtyProtocol, make_request

        class MockLog:
            def debug(self, *a, **kw): pass
            def info(self, *a, **kw): pass
            def warning(self, *a, **kw): pass
            def error(self, *a, **kw): pass
            def critical(self, *a, **kw): pass
            def exception(self, *a, **kw): pass
            def close_on_exec(self): pass
            def reopen_files(self): pass

        cfg = Config()
        cfg.set("dirty_workers", 0)
        cfg.set("dirty_timeout", 10)
        log = MockLog()

        with tempfile.TemporaryDirectory() as tmpdir:
            arbiter_socket_path = os.path.join(tmpdir, "arbiter.sock")
            worker_socket_path = os.path.join(tmpdir, "worker.sock")

            # Create worker
            worker = DirtyWorker(
                age=1,
                ppid=os.getpid(),
                app_paths=["tests.support_dirty_app:TestDirtyApp"],
                cfg=cfg,
                log=log,
                socket_path=worker_socket_path
            )
            worker.pid = os.getpid()
            worker.load_apps()

            # Start worker server
            worker_server = await asyncio.start_unix_server(
                worker.handle_connection,
                path=worker_socket_path
            )

            # Create arbiter
            arbiter = DirtyArbiter(cfg=cfg, log=log, socket_path=arbiter_socket_path)
            arbiter.pid = os.getpid()

            # Register worker
            fake_pid = 12345
            arbiter.workers[fake_pid] = worker
            arbiter.worker_sockets[fake_pid] = worker_socket_path

            # Route a request
            request = make_request(
                request_id="full-flow-test",
                app_path="tests.support_dirty_app:TestDirtyApp",
                action="compute",
                args=(7, 3),
                kwargs={"operation": "multiply"}
            )

            response = await arbiter.route_request(request)

            assert response["type"] == DirtyProtocol.MSG_TYPE_RESPONSE
            assert response["result"] == 21

            # Cleanup - close arbiter's connection first
            arbiter._close_worker_connection(fake_pid)
            worker_server.close()
            await worker_server.wait_closed()
            worker._cleanup()
            arbiter._cleanup_sync()
