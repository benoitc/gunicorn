#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from unittest import mock

import pytest

try:
    import gevent
    HAS_GEVENT = True
except ImportError:
    HAS_GEVENT = False

pytestmark = pytest.mark.skipif(not HAS_GEVENT, reason="gevent not installed")


def test_import():
    __import__('gunicorn.workers.ggevent')


def test_version_requirement():
    """Test that gevent 23.9.0+ is required."""
    from gunicorn.workers import ggevent
    from packaging.version import parse as parse_version
    assert parse_version(gevent.__version__) >= parse_version('23.9.0')


class TestGeventWorkerInit:
    """Test GeventWorker initialization."""

    def test_worker_has_no_server_class(self):
        """Test that GeventWorker has no server_class by default."""
        from gunicorn.workers.ggevent import GeventWorker
        assert GeventWorker.server_class is None

    def test_worker_has_no_wsgi_handler(self):
        """Test that GeventWorker has no wsgi_handler by default."""
        from gunicorn.workers.ggevent import GeventWorker
        assert GeventWorker.wsgi_handler is None

    def test_init_process_patches_and_reinits(self):
        """Test that init_process calls patch and reinits the hub."""
        from gunicorn.workers.ggevent import GeventWorker

        worker = mock.Mock(spec=GeventWorker)
        worker.sockets = []

        with mock.patch('gunicorn.workers.ggevent.hub') as mock_hub, \
             mock.patch.object(GeventWorker.__bases__[0], 'init_process'):
            GeventWorker.init_process(worker)

            # Verify patch was called
            worker.patch.assert_called_once()
            mock_hub.reinit.assert_called_once()


class TestGeventWorkerRun:
    """Test GeventWorker run method."""

    def test_run_creates_stream_servers(self):
        """Test that run creates StreamServer instances for each socket."""
        from gunicorn.workers.ggevent import GeventWorker

        worker = mock.Mock(spec=GeventWorker)
        worker.sockets = [mock.Mock()]
        worker.cfg = mock.Mock(is_ssl=False, workers=1, graceful_timeout=30)
        worker.server_class = None
        worker.worker_connections = 1000

        # Make alive return True once, then False to exit the loop
        worker.alive = False

        with mock.patch('gunicorn.workers.ggevent.Pool') as mock_pool, \
             mock.patch('gunicorn.workers.ggevent.StreamServer') as mock_server_cls, \
             mock.patch('gunicorn.workers.ggevent.gevent') as mock_gevent:

            mock_server = mock.Mock()
            mock_server.pool = mock.Mock()
            mock_server.pool.free_count.return_value = mock_server.pool.size
            mock_server_cls.return_value = mock_server

            GeventWorker.run(worker)

            mock_server_cls.assert_called_once()
            mock_server.start.assert_called_once()
            mock_server.close.assert_called_once()

    def test_run_with_ssl(self):
        """Test that run configures SSL context when is_ssl is True."""
        from gunicorn.workers.ggevent import GeventWorker

        worker = mock.Mock(spec=GeventWorker)
        worker.sockets = [mock.Mock()]
        worker.cfg = mock.Mock(is_ssl=True, workers=1, graceful_timeout=30)
        worker.server_class = None
        worker.worker_connections = 1000
        worker.alive = False

        with mock.patch('gunicorn.workers.ggevent.Pool'), \
             mock.patch('gunicorn.workers.ggevent.StreamServer') as mock_server_cls, \
             mock.patch('gunicorn.workers.ggevent.gevent'), \
             mock.patch('gunicorn.workers.ggevent.ssl_context') as mock_ssl_ctx:

            mock_server = mock.Mock()
            mock_server.pool = mock.Mock()
            mock_server.pool.free_count.return_value = mock_server.pool.size
            mock_server_cls.return_value = mock_server
            mock_ssl_ctx.return_value = mock.Mock()

            GeventWorker.run(worker)

            mock_ssl_ctx.assert_called_once_with(worker.cfg)
            # Verify ssl_context was passed to StreamServer
            call_kwargs = mock_server_cls.call_args[1]
            assert 'ssl_context' in call_kwargs


class TestSignalHandling:
    """Test signal handling in GeventWorker."""

    def test_handle_quit_spawns_greenlet(self):
        """Test that handle_quit spawns a greenlet instead of blocking."""
        from gunicorn.workers.ggevent import GeventWorker

        worker = mock.Mock(spec=GeventWorker)

        with mock.patch('gunicorn.workers.ggevent.gevent') as mock_gevent:
            GeventWorker.handle_quit(worker, mock.Mock(), mock.Mock())
            mock_gevent.spawn.assert_called_once()

    def test_handle_usr1_spawns_greenlet(self):
        """Test that handle_usr1 spawns a greenlet instead of blocking."""
        from gunicorn.workers.ggevent import GeventWorker

        worker = mock.Mock(spec=GeventWorker)

        with mock.patch('gunicorn.workers.ggevent.gevent') as mock_gevent:
            GeventWorker.handle_usr1(worker, mock.Mock(), mock.Mock())
            mock_gevent.spawn.assert_called_once()

    def test_notify_exits_on_parent_change(self):
        """Test that notify exits when parent PID changes."""
        from gunicorn.workers.ggevent import GeventWorker

        worker = mock.Mock(spec=GeventWorker)
        worker.ppid = 1234
        worker.log = mock.Mock()

        with mock.patch('gunicorn.workers.ggevent.os') as mock_os, \
             mock.patch.object(GeventWorker.__bases__[0], 'notify'):
            mock_os.getppid.return_value = 5678  # Different PID

            with pytest.raises(SystemExit):
                GeventWorker.notify(worker)


class TestPyWSGIWorker:
    """Test PyWSGI-based worker classes."""

    def test_pywsgi_worker_has_server_class(self):
        """Test that GeventPyWSGIWorker has proper server_class."""
        from gunicorn.workers.ggevent import GeventPyWSGIWorker, PyWSGIServer
        assert GeventPyWSGIWorker.server_class is PyWSGIServer

    def test_pywsgi_worker_has_handler(self):
        """Test that GeventPyWSGIWorker has proper wsgi_handler."""
        from gunicorn.workers.ggevent import GeventPyWSGIWorker, PyWSGIHandler
        assert GeventPyWSGIWorker.wsgi_handler is PyWSGIHandler

    def test_pywsgi_handler_get_environ(self):
        """Test that PyWSGIHandler adds gunicorn-specific environ keys."""
        from gunicorn.workers.ggevent import PyWSGIHandler

        handler = mock.Mock(spec=PyWSGIHandler)
        handler.socket = mock.Mock()
        handler.path = '/test/path'

        # Mock the parent get_environ
        with mock.patch.object(PyWSGIHandler.__bases__[0], 'get_environ', return_value={}):
            env = PyWSGIHandler.get_environ(handler)
            assert env['gunicorn.sock'] == handler.socket
            assert env['RAW_URI'] == '/test/path'


class TestGeventResponse:
    """Test GeventResponse helper class."""

    def test_response_attributes(self):
        """Test GeventResponse stores status, headers, and sent."""
        from gunicorn.workers.ggevent import GeventResponse

        resp = GeventResponse('200 OK', {'Content-Type': 'text/html'}, 1024)
        assert resp.status == '200 OK'
        assert resp.headers == {'Content-Type': 'text/html'}
        assert resp.sent == 1024


class TestTimeoutContext:
    """Test timeout context manager."""

    def test_timeout_ctx_uses_keepalive(self):
        """Test that timeout_ctx uses cfg.keepalive."""
        from gunicorn.workers.ggevent import GeventWorker

        worker = mock.Mock(spec=GeventWorker)
        worker.cfg = mock.Mock(keepalive=30)

        with mock.patch('gunicorn.workers.ggevent.gevent') as mock_gevent:
            mock_timeout = mock.Mock()
            mock_gevent.Timeout.return_value = mock_timeout

            result = GeventWorker.timeout_ctx(worker)

            mock_gevent.Timeout.assert_called_once_with(30, False)
            assert result == mock_timeout
