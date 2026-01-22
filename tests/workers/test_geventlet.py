#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import pytest
import sys
from unittest import mock


def test_import():
    """Test that the eventlet worker module can be imported."""
    try:
        import eventlet
    except AttributeError:
        if (3, 13) > sys.version_info >= (3, 12):
            pytest.skip("Ignoring eventlet failures on Python 3.12")
        raise
    __import__('gunicorn.workers.geventlet')


class TestVersionRequirement:
    """Tests for eventlet version requirement checks."""

    def test_import_error_message(self):
        """Test that ImportError gives correct version message."""
        with mock.patch.dict('sys.modules', {'eventlet': None}):
            # Clear cached module if present
            sys.modules.pop('gunicorn.workers.geventlet', None)
            with pytest.raises(RuntimeError, match="eventlet 0.40.3"):
                import importlib
                import gunicorn.workers.geventlet
                importlib.reload(gunicorn.workers.geventlet)

    def test_version_check_requires_0_40_3(self):
        """Test that version check requires eventlet 0.40.3 or higher."""
        try:
            import eventlet
        except (ImportError, AttributeError):
            pytest.skip("eventlet not available")

        from packaging.version import parse as parse_version
        min_version = parse_version('0.40.3')
        current_version = parse_version(eventlet.__version__)

        # If we got this far, the import succeeded, meaning version is sufficient
        assert current_version >= min_version


@pytest.fixture
def eventlet_worker():
    """Fixture to create an EventletWorker instance for testing."""
    try:
        import eventlet
    except (ImportError, AttributeError):
        pytest.skip("eventlet not available")

    from gunicorn.workers.geventlet import EventletWorker

    # Create a minimal mock config
    cfg = mock.MagicMock()
    cfg.keepalive = 2
    cfg.graceful_timeout = 30
    cfg.is_ssl = False
    cfg.worker_connections = 1000

    # Create worker with mocked dependencies
    worker = EventletWorker.__new__(EventletWorker)
    worker.cfg = cfg
    worker.alive = True
    worker.sockets = []
    worker.log = mock.MagicMock()

    return worker


class TestEventletWorker:
    """Tests for EventletWorker class."""

    def test_worker_class_exists(self):
        """Test that EventletWorker class is properly defined."""
        try:
            import eventlet
        except (ImportError, AttributeError):
            pytest.skip("eventlet not available")

        from gunicorn.workers.geventlet import EventletWorker
        from gunicorn.workers.base_async import AsyncWorker

        assert issubclass(EventletWorker, AsyncWorker)

    def test_patch_method_calls_use_hub(self, eventlet_worker):
        """Test that patch() calls hubs.use_hub().

        hubs.use_hub() must be called in patch() (after fork) because it creates
        OS resources like kqueue that don't survive fork.
        """
        from eventlet import hubs

        with mock.patch.object(hubs, 'use_hub') as mock_use_hub:
            with mock.patch('gunicorn.workers.geventlet.patch_sendfile'):
                eventlet_worker.patch()

        mock_use_hub.assert_called_once()

    def test_patch_method_calls_patch_sendfile(self, eventlet_worker):
        """Test that patch() calls patch_sendfile()."""
        from eventlet import hubs

        with mock.patch.object(hubs, 'use_hub'):
            with mock.patch('gunicorn.workers.geventlet.patch_sendfile') as mock_sf:
                eventlet_worker.patch()

        mock_sf.assert_called_once()

    def test_monkey_patch_called_at_import_time(self):
        """Test that monkey_patch is called at module import time.

        Note: hubs.use_hub() and eventlet.monkey_patch() are called at module
        import time (not in patch()) to ensure all imports are properly patched.
        This test verifies the module was patched by checking eventlet state.
        """
        try:
            import eventlet
        except (ImportError, AttributeError):
            pytest.skip("eventlet not available")

        # Verify eventlet has been patched by checking that socket is patched
        import socket
        from eventlet.greenio import GreenSocket

        # After monkey patching, socket.socket should be GreenSocket
        assert socket.socket is GreenSocket

    def test_timeout_ctx_returns_eventlet_timeout(self, eventlet_worker):
        """Test that timeout_ctx() returns an eventlet.Timeout."""
        import eventlet

        timeout = eventlet_worker.timeout_ctx()
        assert isinstance(timeout, eventlet.Timeout)

    def test_timeout_ctx_uses_keepalive_config(self, eventlet_worker):
        """Test that timeout_ctx() uses cfg.keepalive value."""
        import eventlet

        eventlet_worker.cfg.keepalive = 5
        with mock.patch.object(eventlet, 'Timeout') as mock_timeout:
            eventlet_worker.timeout_ctx()

        mock_timeout.assert_called_once_with(5, False)

    def test_timeout_ctx_with_no_keepalive(self, eventlet_worker):
        """Test that timeout_ctx() handles no keepalive (None or 0)."""
        import eventlet

        eventlet_worker.cfg.keepalive = 0
        with mock.patch.object(eventlet, 'Timeout') as mock_timeout:
            eventlet_worker.timeout_ctx()

        mock_timeout.assert_called_once_with(None, False)

    def test_handle_quit_spawns_greenthread(self, eventlet_worker):
        """Test that handle_quit() spawns a greenthread."""
        import eventlet

        with mock.patch.object(eventlet, 'spawn') as mock_spawn:
            eventlet_worker.handle_quit(None, None)

        mock_spawn.assert_called_once()

    def test_handle_usr1_spawns_greenthread(self, eventlet_worker):
        """Test that handle_usr1() spawns a greenthread."""
        import eventlet

        with mock.patch.object(eventlet, 'spawn') as mock_spawn:
            eventlet_worker.handle_usr1(None, None)

        mock_spawn.assert_called_once()

    def test_handle_wraps_ssl_when_configured(self, eventlet_worker):
        """Test that handle() wraps socket with SSL when is_ssl is True."""
        from gunicorn.workers import geventlet

        eventlet_worker.cfg.is_ssl = True
        mock_client = mock.MagicMock()
        mock_listener = mock.MagicMock()

        with mock.patch.object(geventlet, 'ssl_wrap_socket') as mock_ssl:
            mock_ssl.return_value = mock_client
            with mock.patch('gunicorn.workers.base_async.AsyncWorker.handle'):
                eventlet_worker.handle(mock_listener, mock_client, ('127.0.0.1', 8000))

        mock_ssl.assert_called_once_with(mock_client, eventlet_worker.cfg)

    def test_handle_no_ssl_when_not_configured(self, eventlet_worker):
        """Test that handle() does not wrap SSL when is_ssl is False."""
        from gunicorn.workers import geventlet

        eventlet_worker.cfg.is_ssl = False
        mock_client = mock.MagicMock()
        mock_listener = mock.MagicMock()

        with mock.patch.object(geventlet, 'ssl_wrap_socket') as mock_ssl:
            with mock.patch('gunicorn.workers.base_async.AsyncWorker.handle'):
                eventlet_worker.handle(mock_listener, mock_client, ('127.0.0.1', 8000))

        mock_ssl.assert_not_called()


class TestAlreadyHandled:
    """Tests for is_already_handled() method."""

    def test_is_already_handled_new_style(self, eventlet_worker):
        """Test is_already_handled with eventlet >= 0.30.3 (WSGI_LOCAL)."""
        from gunicorn.workers import geventlet

        # Mock the new-style WSGI_LOCAL.already_handled
        mock_wsgi_local = mock.MagicMock()
        mock_wsgi_local.already_handled = True

        with mock.patch.object(geventlet, 'EVENTLET_WSGI_LOCAL', mock_wsgi_local):
            with pytest.raises(StopIteration):
                eventlet_worker.is_already_handled(mock.MagicMock())

    def test_is_already_handled_old_style(self, eventlet_worker):
        """Test is_already_handled with eventlet < 0.30.3 (ALREADY_HANDLED)."""
        from gunicorn.workers import geventlet

        sentinel = object()

        with mock.patch.object(geventlet, 'EVENTLET_WSGI_LOCAL', None):
            with mock.patch.object(geventlet, 'EVENTLET_ALREADY_HANDLED', sentinel):
                with pytest.raises(StopIteration):
                    eventlet_worker.is_already_handled(sentinel)

    def test_is_already_handled_returns_parent_result(self, eventlet_worker):
        """Test is_already_handled falls through to parent when not handled."""
        from gunicorn.workers import geventlet

        with mock.patch.object(geventlet, 'EVENTLET_WSGI_LOCAL', None):
            with mock.patch.object(geventlet, 'EVENTLET_ALREADY_HANDLED', None):
                with mock.patch('gunicorn.workers.base_async.AsyncWorker.is_already_handled') as mock_parent:
                    mock_parent.return_value = False
                    result = eventlet_worker.is_already_handled(mock.MagicMock())

        assert result is False
        mock_parent.assert_called_once()


class TestPatchSendfile:
    """Tests for patch_sendfile() function."""

    def test_patch_sendfile_adds_method_when_missing(self):
        """Test that patch_sendfile adds sendfile to GreenSocket if missing."""
        try:
            import eventlet
        except (ImportError, AttributeError):
            pytest.skip("eventlet not available")

        from gunicorn.workers.geventlet import patch_sendfile, _eventlet_socket_sendfile
        from eventlet.greenio import GreenSocket

        # Remove sendfile if it exists
        original = getattr(GreenSocket, 'sendfile', None)
        if hasattr(GreenSocket, 'sendfile'):
            delattr(GreenSocket, 'sendfile')

        try:
            patch_sendfile()
            assert hasattr(GreenSocket, 'sendfile')
            assert GreenSocket.sendfile == _eventlet_socket_sendfile
        finally:
            # Restore original state
            if original is not None:
                GreenSocket.sendfile = original
            elif hasattr(GreenSocket, 'sendfile'):
                delattr(GreenSocket, 'sendfile')

    def test_patch_sendfile_preserves_existing_method(self):
        """Test that patch_sendfile does not override existing sendfile."""
        try:
            import eventlet
        except (ImportError, AttributeError):
            pytest.skip("eventlet not available")

        from gunicorn.workers.geventlet import patch_sendfile
        from eventlet.greenio import GreenSocket

        # If sendfile exists, it should be preserved
        if hasattr(GreenSocket, 'sendfile'):
            original = GreenSocket.sendfile
            patch_sendfile()
            assert GreenSocket.sendfile == original


class TestEventletSocketSendfile:
    """Tests for _eventlet_socket_sendfile() function."""

    def test_sendfile_raises_on_non_blocking(self):
        """Test that sendfile raises ValueError for non-blocking sockets."""
        try:
            import eventlet
        except (ImportError, AttributeError):
            pytest.skip("eventlet not available")

        from gunicorn.workers.geventlet import _eventlet_socket_sendfile

        mock_socket = mock.MagicMock()
        mock_socket.gettimeout.return_value = 0

        with pytest.raises(ValueError, match="non-blocking"):
            _eventlet_socket_sendfile(mock_socket, mock.MagicMock())

    def test_sendfile_seeks_to_offset(self):
        """Test that sendfile seeks to offset if provided."""
        try:
            import eventlet
        except (ImportError, AttributeError):
            pytest.skip("eventlet not available")

        from gunicorn.workers.geventlet import _eventlet_socket_sendfile

        mock_socket = mock.MagicMock()
        mock_socket.gettimeout.return_value = 1
        mock_file = mock.MagicMock()
        mock_file.read.return_value = b''

        _eventlet_socket_sendfile(mock_socket, mock_file, offset=100)

        mock_file.seek.assert_any_call(100)

    def test_sendfile_returns_total_sent(self):
        """Test that sendfile returns the total bytes sent."""
        try:
            import eventlet
        except (ImportError, AttributeError):
            pytest.skip("eventlet not available")

        from gunicorn.workers.geventlet import _eventlet_socket_sendfile

        mock_socket = mock.MagicMock()
        mock_socket.gettimeout.return_value = 1
        mock_socket.send.return_value = 10

        mock_file = mock.MagicMock()
        mock_file.read.side_effect = [b'x' * 10, b'']

        result = _eventlet_socket_sendfile(mock_socket, mock_file)

        assert result == 10


class TestEventletServe:
    """Tests for _eventlet_serve() function."""

    def test_serve_creates_green_pool(self):
        """Test that _eventlet_serve creates a GreenPool."""
        try:
            import eventlet
        except (ImportError, AttributeError):
            pytest.skip("eventlet not available")

        from gunicorn.workers.geventlet import _eventlet_serve

        mock_sock = mock.MagicMock()
        mock_sock.accept.side_effect = eventlet.StopServe()

        with mock.patch.object(eventlet.greenpool, 'GreenPool') as mock_pool:
            mock_pool_instance = mock.MagicMock()
            mock_pool.return_value = mock_pool_instance
            mock_pool_instance.waitall.return_value = None

            _eventlet_serve(mock_sock, mock.MagicMock(), 100)

        mock_pool.assert_called_once_with(100)


class TestEventletStop:
    """Tests for _eventlet_stop() function."""

    def test_stop_waits_for_client(self):
        """Test that _eventlet_stop waits for the client greenlet."""
        try:
            import eventlet
        except (ImportError, AttributeError):
            pytest.skip("eventlet not available")

        from gunicorn.workers.geventlet import _eventlet_stop

        mock_client = mock.MagicMock()
        mock_server = mock.MagicMock()
        mock_conn = mock.MagicMock()

        _eventlet_stop(mock_client, mock_server, mock_conn)

        mock_client.wait.assert_called_once()
        mock_conn.close.assert_called_once()

    def test_stop_closes_connection_on_greenlet_exit(self):
        """Test that connection is closed even on GreenletExit."""
        try:
            import eventlet
            import greenlet
        except (ImportError, AttributeError):
            pytest.skip("eventlet not available")

        from gunicorn.workers.geventlet import _eventlet_stop

        mock_client = mock.MagicMock()
        mock_client.wait.side_effect = greenlet.GreenletExit()
        mock_server = mock.MagicMock()
        mock_conn = mock.MagicMock()

        # Should not raise
        _eventlet_stop(mock_client, mock_server, mock_conn)

        mock_conn.close.assert_called_once()
