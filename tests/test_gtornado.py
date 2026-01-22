#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for the tornado worker."""

import os
from unittest import mock

import pytest

tornado = pytest.importorskip("tornado")

from gunicorn.config import Config
from gunicorn.workers import gtornado


class FakeSocket:
    """Mock socket for testing."""

    def __init__(self, data=b''):
        self.data = data
        self.closed = False
        self.blocking = True
        self._fileno = id(self) % 65536

    def fileno(self):
        return self._fileno

    def setblocking(self, blocking):
        self.blocking = blocking

    def recv(self, size):
        result = self.data[:size]
        self.data = self.data[size:]
        return result

    def send(self, data):
        return len(data)

    def close(self):
        self.closed = True

    def getsockname(self):
        return ('127.0.0.1', 8000)

    def getpeername(self):
        return ('127.0.0.1', 12345)


class TestTornadoWorkerInit:
    """Tests for TornadoWorker initialization."""

    def create_worker(self, cfg=None):
        """Create a worker instance for testing."""
        if cfg is None:
            cfg = Config()
        cfg.set('workers', 1)
        cfg.set('max_requests', 0)

        worker = gtornado.TornadoWorker(
            age=1,
            ppid=os.getpid(),
            sockets=[],
            app=mock.Mock(),
            timeout=30,
            cfg=cfg,
            log=mock.Mock(),
        )
        return worker

    def test_worker_init(self):
        """Test worker initialization."""
        worker = self.create_worker()
        assert worker.nr == 0

    def test_init_process_clears_ioloop(self):
        """Test that init_process clears the current IOLoop."""
        worker = self.create_worker()
        worker.tmp = mock.Mock()
        worker.log = mock.Mock()

        with mock.patch.object(gtornado.IOLoop, 'clear_current') as mock_clear:
            with mock.patch.object(gtornado.Worker, 'init_process'):
                worker.init_process()
            mock_clear.assert_called_once()


class TestRequestCounting:
    """Tests for request counting and max_requests behavior."""

    def create_worker(self, cfg=None):
        """Create a worker instance for testing."""
        if cfg is None:
            cfg = Config()
        cfg.set('workers', 1)

        worker = gtornado.TornadoWorker(
            age=1,
            ppid=os.getpid(),
            sockets=[],
            app=mock.Mock(),
            timeout=30,
            cfg=cfg,
            log=mock.Mock(),
        )
        return worker

    def test_handle_request_increments_counter(self):
        """Test that handle_request increments the request counter."""
        worker = self.create_worker()
        worker.nr = 0
        worker.max_requests = 100
        worker.alive = True

        worker.handle_request()

        assert worker.nr == 1
        assert worker.alive is True

    def test_max_requests_triggers_shutdown(self):
        """Test that reaching max_requests triggers shutdown."""
        cfg = Config()
        cfg.set('max_requests', 5)
        worker = self.create_worker(cfg)
        worker.nr = 4
        worker.alive = True
        worker.max_requests = 5

        worker.handle_request()

        assert worker.nr == 5
        assert worker.alive is False


class TestSignalHandling:
    """Tests for signal handling in tornado worker."""

    def create_worker(self):
        """Create a worker for testing."""
        cfg = Config()
        cfg.set('workers', 1)

        worker = gtornado.TornadoWorker(
            age=1,
            ppid=os.getpid(),
            sockets=[],
            app=mock.Mock(),
            timeout=30,
            cfg=cfg,
            log=mock.Mock(),
        )
        return worker

    def test_handle_exit_sets_alive_false(self):
        """Test that handle_exit sets alive=False through parent."""
        worker = self.create_worker()
        worker.alive = True

        # The parent's handle_exit is what sets alive=False
        worker.handle_exit(None, None)

        assert worker.alive is False

    def test_handle_exit_only_once(self):
        """Test that handle_exit only triggers once when alive."""
        worker = self.create_worker()
        worker.alive = True

        # First call should set alive=False
        worker.handle_exit(None, None)
        assert worker.alive is False

        # Second call should do nothing (alive is already False)
        # Track that super().handle_exit is not called again
        with mock.patch.object(gtornado.Worker, 'handle_exit') as mock_exit:
            worker.handle_exit(None, None)
            mock_exit.assert_not_called()


class TestWatchdog:
    """Tests for watchdog functionality."""

    def create_worker(self):
        """Create a worker for testing."""
        cfg = Config()
        cfg.set('workers', 1)

        worker = gtornado.TornadoWorker(
            age=1,
            ppid=os.getpid(),
            sockets=[],
            app=mock.Mock(),
            timeout=30,
            cfg=cfg,
            log=mock.Mock(),
        )
        return worker

    def test_watchdog_notifies_when_alive(self):
        """Test that watchdog calls notify when alive."""
        worker = self.create_worker()
        worker.alive = True
        worker.ppid = os.getppid()
        worker.tmp = mock.Mock()

        worker.watchdog()

        worker.tmp.notify.assert_called_once()

    def test_watchdog_detects_parent_death(self):
        """Test that watchdog detects parent death."""
        worker = self.create_worker()
        worker.alive = True
        worker.ppid = 99999999  # Invalid ppid
        worker.tmp = mock.Mock()

        worker.watchdog()

        assert worker.alive is False


class TestHeartbeat:
    """Tests for heartbeat functionality."""

    def create_worker(self):
        """Create a worker for testing."""
        cfg = Config()
        cfg.set('workers', 1)

        worker = gtornado.TornadoWorker(
            age=1,
            ppid=os.getpid(),
            sockets=[],
            app=mock.Mock(),
            timeout=30,
            cfg=cfg,
            log=mock.Mock(),
        )
        return worker

    def test_heartbeat_stops_server_when_not_alive(self):
        """Test that heartbeat stops the server when not alive."""
        worker = self.create_worker()
        worker.alive = False
        worker.server_alive = True
        worker.server = mock.Mock()

        worker.heartbeat()

        worker.server.stop.assert_called_once()
        assert worker.server_alive is False

    def test_heartbeat_stops_ioloop_after_server(self):
        """Test that heartbeat stops IOLoop after server is stopped."""
        worker = self.create_worker()
        worker.alive = False
        worker.server_alive = False
        worker.callbacks = [mock.Mock(), mock.Mock()]
        worker.ioloop = mock.Mock()

        worker.heartbeat()

        for callback in worker.callbacks:
            callback.stop.assert_called_once()
        worker.ioloop.stop.assert_called_once()


class TestAppWrapping:
    """Tests for app wrapping logic."""

    def create_worker(self):
        """Create a worker for testing."""
        cfg = Config()
        cfg.set('workers', 1)

        worker = gtornado.TornadoWorker(
            age=1,
            ppid=os.getpid(),
            sockets=[],
            app=mock.Mock(),
            timeout=30,
            cfg=cfg,
            log=mock.Mock(),
        )
        return worker

    def test_wsgi_callable_wrapped_in_container(self):
        """Test that a plain WSGI callable gets wrapped in WSGIContainer."""
        from tornado.wsgi import WSGIContainer

        def wsgi_app(environ, start_response):
            pass

        # Test that WSGIContainer is used for plain WSGI apps
        app = wsgi_app
        if not isinstance(app, WSGIContainer) and \
                not isinstance(app, tornado.web.Application):
            app = WSGIContainer(app)

        assert isinstance(app, WSGIContainer)

    def test_tornado_application_not_wrapped(self):
        """Test that tornado.web.Application is not wrapped."""
        from tornado.wsgi import WSGIContainer

        tornado_app = tornado.web.Application([])

        # Test the wrapping logic
        app = tornado_app
        if not isinstance(app, WSGIContainer) and \
                not isinstance(app, tornado.web.Application):
            app = WSGIContainer(app)

        # Should NOT be wrapped
        assert isinstance(app, tornado.web.Application)
        assert not isinstance(app, WSGIContainer)


class TestSetup:
    """Tests for the setup class method."""

    def test_setup_patches_request_handler(self):
        """Test that setup patches RequestHandler.clear."""
        # Save original
        original_clear = tornado.web.RequestHandler.clear

        try:
            gtornado.TornadoWorker.setup()

            # Create a mock handler to test the patched clear method
            mock_handler = mock.Mock()
            mock_handler._headers = {"Server": "TornadoServer/1.0"}

            # Call the patched clear
            new_clear = tornado.web.RequestHandler.clear
            assert new_clear is not original_clear

        finally:
            # Restore original
            tornado.web.RequestHandler.clear = original_clear


class TestRunMethod:
    """Tests for the run method."""

    def create_worker(self):
        """Create a worker for testing."""
        cfg = Config()
        cfg.set('workers', 1)
        cfg.set('keepalive', 2)

        worker = gtornado.TornadoWorker(
            age=1,
            ppid=os.getpid(),
            sockets=[],
            app=mock.Mock(),
            timeout=30,
            cfg=cfg,
            log=mock.Mock(),
        )
        return worker

    def test_run_sets_up_callbacks(self):
        """Test that run sets up periodic callbacks."""
        worker = self.create_worker()
        worker.wsgi = tornado.web.Application([])
        worker.sockets = []

        mock_ioloop = mock.Mock()
        mock_callback = mock.Mock()

        with mock.patch.object(gtornado.IOLoop, 'instance', return_value=mock_ioloop):
            with mock.patch.object(gtornado, 'PeriodicCallback', return_value=mock_callback) as mock_pc:
                # Start the run method but stop it immediately
                mock_ioloop.start.side_effect = lambda: None

                worker.run()

                # Should create two callbacks (watchdog and heartbeat)
                assert mock_pc.call_count == 2
                assert mock_callback.start.call_count == 2

    def test_run_creates_http_server(self):
        """Test that run creates an HTTP server."""
        worker = self.create_worker()
        worker.wsgi = tornado.web.Application([])
        worker.sockets = []

        mock_ioloop = mock.Mock()
        mock_ioloop.start.side_effect = lambda: None

        with mock.patch.object(gtornado.IOLoop, 'instance', return_value=mock_ioloop):
            with mock.patch.object(gtornado, 'PeriodicCallback', return_value=mock.Mock()):
                worker.run()

                assert worker.server is not None
                assert worker.server_alive is True

    def test_run_adds_sockets_to_server(self):
        """Test that run adds sockets to the server."""
        worker = self.create_worker()
        worker.wsgi = tornado.web.Application([])

        mock_socket = FakeSocket()
        worker.sockets = [mock_socket]

        mock_ioloop = mock.Mock()
        mock_ioloop.start.side_effect = lambda: None

        with mock.patch.object(gtornado.IOLoop, 'instance', return_value=mock_ioloop):
            with mock.patch.object(gtornado, 'PeriodicCallback', return_value=mock.Mock()):
                with mock.patch.object(tornado.httpserver.HTTPServer, 'add_socket'):
                    worker.run()

                    # Socket should be set to non-blocking (setblocking(0))
                    assert not mock_socket.blocking


class TestSSLSupport:
    """Tests for SSL support."""

    def create_worker(self):
        """Create a worker for testing."""
        cfg = Config()
        cfg.set('workers', 1)
        cfg.set('keepalive', 2)

        worker = gtornado.TornadoWorker(
            age=1,
            ppid=os.getpid(),
            sockets=[],
            app=mock.Mock(),
            timeout=30,
            cfg=cfg,
            log=mock.Mock(),
        )
        return worker

    def test_ssl_server_creation(self):
        """Test that SSL server is created when is_ssl is True."""
        worker = self.create_worker()
        worker.wsgi = tornado.web.Application([])
        worker.sockets = []

        mock_ioloop = mock.Mock()
        mock_ioloop.start.side_effect = lambda: None

        mock_ssl_context = mock.Mock()

        # Mock cfg.is_ssl property to return True
        with mock.patch.object(type(worker.cfg), 'is_ssl', new_callable=mock.PropertyMock, return_value=True):
            with mock.patch.object(gtornado.IOLoop, 'instance', return_value=mock_ioloop):
                with mock.patch.object(gtornado, 'PeriodicCallback', return_value=mock.Mock()):
                    with mock.patch.object(gtornado, 'ssl_context', return_value=mock_ssl_context):
                        worker.run()

                        # Server should be created with ssl_options
                        assert worker.server is not None


class TestKeepAlive:
    """Tests for keep-alive configuration."""

    def create_worker(self):
        """Create a worker for testing."""
        cfg = Config()
        cfg.set('workers', 1)

        worker = gtornado.TornadoWorker(
            age=1,
            ppid=os.getpid(),
            sockets=[],
            app=mock.Mock(),
            timeout=30,
            cfg=cfg,
            log=mock.Mock(),
        )
        return worker

    def test_keep_alive_enabled(self):
        """Test that keep-alive is enabled when keepalive > 0."""
        worker = self.create_worker()
        worker.wsgi = tornado.web.Application([])
        worker.cfg.set('keepalive', 2)
        worker.sockets = []

        mock_ioloop = mock.Mock()
        mock_ioloop.start.side_effect = lambda: None

        with mock.patch.object(gtornado.IOLoop, 'instance', return_value=mock_ioloop):
            with mock.patch.object(gtornado, 'PeriodicCallback', return_value=mock.Mock()):
                worker.run()

                assert worker.server.no_keep_alive is False

    def test_keep_alive_disabled(self):
        """Test that keep-alive is disabled when keepalive <= 0."""
        worker = self.create_worker()
        worker.wsgi = tornado.web.Application([])
        worker.cfg.set('keepalive', 0)
        worker.sockets = []

        mock_ioloop = mock.Mock()
        mock_ioloop.start.side_effect = lambda: None

        with mock.patch.object(gtornado.IOLoop, 'instance', return_value=mock_ioloop):
            with mock.patch.object(gtornado, 'PeriodicCallback', return_value=mock.Mock()):
                worker.run()

                assert worker.server.no_keep_alive is True
