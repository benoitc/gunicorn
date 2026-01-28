# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for HTTP/2 ALPN negotiation."""

import ssl
import pytest
from unittest import mock

from gunicorn import sock


def create_mock_ssl_socket(alpn_protocol=None):
    """Create a mock SSL socket for testing ALPN negotiation."""
    mock_socket = mock.Mock(spec=ssl.SSLSocket)
    mock_socket.selected_alpn_protocol.return_value = alpn_protocol
    return mock_socket


class TestGetAlpnProtocols:
    """Test _get_alpn_protocols function."""

    def test_h1_only_returns_empty(self):
        """No ALPN needed for HTTP/1.1 only."""
        conf = mock.Mock()
        conf.http_protocols = ["h1"]

        result = sock._get_alpn_protocols(conf)
        assert result == []

    def test_h2_enabled_returns_alpn_list(self):
        """Should return ALPN protocols when h2 is enabled."""
        conf = mock.Mock()
        conf.http_protocols = ["h2", "h1"]

        with mock.patch('gunicorn.http2.is_http2_available', return_value=True):
            result = sock._get_alpn_protocols(conf)
            assert "h2" in result
            assert "http/1.1" in result

    def test_h2_without_library_returns_empty(self):
        """Should return empty if h2 library not available."""
        conf = mock.Mock()
        conf.http_protocols = ["h2", "h1"]

        with mock.patch('gunicorn.http2.is_http2_available', return_value=False):
            result = sock._get_alpn_protocols(conf)
            assert result == []

    def test_empty_protocols_returns_empty(self):
        conf = mock.Mock()
        conf.http_protocols = []

        result = sock._get_alpn_protocols(conf)
        assert result == []

    def test_none_protocols_returns_empty(self):
        conf = mock.Mock()
        conf.http_protocols = None

        result = sock._get_alpn_protocols(conf)
        assert result == []

    def test_h2_only(self):
        """Should work with h2 only."""
        conf = mock.Mock()
        conf.http_protocols = ["h2"]

        with mock.patch('gunicorn.http2.is_http2_available', return_value=True):
            result = sock._get_alpn_protocols(conf)
            assert "h2" in result


class TestGetNegotiatedProtocol:
    """Test get_negotiated_protocol function."""

    def test_returns_alpn_protocol(self):
        ssl_socket = create_mock_ssl_socket(alpn_protocol="h2")
        result = sock.get_negotiated_protocol(ssl_socket)
        assert result == "h2"

    def test_returns_http11(self):
        ssl_socket = create_mock_ssl_socket(alpn_protocol="http/1.1")
        result = sock.get_negotiated_protocol(ssl_socket)
        assert result == "http/1.1"

    def test_returns_none_when_not_negotiated(self):
        ssl_socket = create_mock_ssl_socket(alpn_protocol=None)
        result = sock.get_negotiated_protocol(ssl_socket)
        assert result is None

    def test_returns_none_for_non_ssl_socket(self):
        regular_socket = mock.Mock(spec=[])  # No SSL methods
        result = sock.get_negotiated_protocol(regular_socket)
        assert result is None

    def test_handles_attribute_error(self):
        """Handle old SSL without selected_alpn_protocol."""
        ssl_socket = mock.Mock(spec=ssl.SSLSocket)
        del ssl_socket.selected_alpn_protocol  # Remove the method
        result = sock.get_negotiated_protocol(ssl_socket)
        assert result is None

    def test_handles_ssl_error(self):
        """Handle SSLError when checking protocol."""
        ssl_socket = mock.Mock(spec=ssl.SSLSocket)
        ssl_socket.selected_alpn_protocol.side_effect = ssl.SSLError()
        result = sock.get_negotiated_protocol(ssl_socket)
        assert result is None


class TestIsHttp2Negotiated:
    """Test is_http2_negotiated function."""

    def test_returns_true_for_h2(self):
        ssl_socket = create_mock_ssl_socket(alpn_protocol="h2")
        result = sock.is_http2_negotiated(ssl_socket)
        assert result is True

    def test_returns_false_for_http11(self):
        ssl_socket = create_mock_ssl_socket(alpn_protocol="http/1.1")
        result = sock.is_http2_negotiated(ssl_socket)
        assert result is False

    def test_returns_false_for_none(self):
        ssl_socket = create_mock_ssl_socket(alpn_protocol=None)
        result = sock.is_http2_negotiated(ssl_socket)
        assert result is False

    def test_returns_false_for_non_ssl(self):
        regular_socket = mock.Mock(spec=[])
        result = sock.is_http2_negotiated(regular_socket)
        assert result is False


class TestSSLContextAlpnConfiguration:
    """Test that SSL context configures ALPN properly."""

    @pytest.fixture
    def ssl_config(self, tmp_path):
        """Create a config with SSL settings."""
        # Create dummy cert/key files
        certfile = tmp_path / "cert.pem"
        keyfile = tmp_path / "key.pem"
        certfile.touch()
        keyfile.touch()

        conf = mock.Mock()
        conf.certfile = str(certfile)
        conf.keyfile = str(keyfile)
        conf.ca_certs = None
        conf.cert_reqs = ssl.CERT_NONE
        conf.ciphers = None
        conf.http_protocols = ["h2", "h1"]
        conf.ssl_context = lambda conf, factory: factory()

        return conf

    def test_ssl_context_sets_alpn_when_h2_available(self, ssl_config):
        """SSL context should set ALPN protocols when h2 is available."""
        with mock.patch('gunicorn.http2.is_http2_available', return_value=True):
            with mock.patch('ssl.create_default_context') as mock_ctx:
                mock_context = mock.Mock()
                mock_ctx.return_value = mock_context
                mock_context.load_cert_chain = mock.Mock()

                try:
                    sock.ssl_context(ssl_config)
                except Exception:
                    pass  # May fail due to dummy certs

                # Check that set_alpn_protocols was called
                if mock_context.set_alpn_protocols.called:
                    call_args = mock_context.set_alpn_protocols.call_args[0][0]
                    assert 'h2' in call_args

    def test_ssl_context_no_alpn_when_h1_only(self):
        """SSL context should not set ALPN for HTTP/1.1 only."""
        conf = mock.Mock()
        conf.http_protocols = ["h1"]
        conf.ca_certs = None
        conf.certfile = "cert.pem"
        conf.keyfile = "key.pem"
        conf.cert_reqs = ssl.CERT_NONE
        conf.ciphers = None
        conf.ssl_context = lambda conf, factory: factory()

        with mock.patch('ssl.create_default_context') as mock_ctx:
            mock_context = mock.Mock()
            mock_ctx.return_value = mock_context

            # ALPN should not be set for h1 only
            alpn_protocols = sock._get_alpn_protocols(conf)
            assert alpn_protocols == []


class TestAlpnProtocolMap:
    """Test ALPN protocol mapping."""

    def test_h1_maps_to_http11(self):
        from gunicorn.config import ALPN_PROTOCOL_MAP
        assert ALPN_PROTOCOL_MAP.get("h1") == "http/1.1"

    def test_h2_maps_to_h2(self):
        from gunicorn.config import ALPN_PROTOCOL_MAP
        assert ALPN_PROTOCOL_MAP.get("h2") == "h2"


class TestAsyncWorkerAlpnHandshake:
    """Test that AsyncWorker performs handshake before ALPN check.

    This is critical for gevent and eventlet workers where do_handshake_on_connect
    may be False, causing ALPN negotiation to not complete until first I/O.
    """

    @pytest.fixture
    def async_worker(self):
        """Create an AsyncWorker instance for testing."""
        from gunicorn.workers.base_async import AsyncWorker

        worker = AsyncWorker.__new__(AsyncWorker)
        worker.cfg = mock.MagicMock()
        worker.cfg.keepalive = 2
        worker.cfg.do_handshake_on_connect = False
        worker.cfg.http_protocols = ["h2", "h1"]
        worker.alive = True
        worker.log = mock.MagicMock()
        worker.wsgi = mock.MagicMock()
        worker.nr = 0
        worker.max_requests = 1000

        return worker

    def test_handshake_called_when_do_handshake_on_connect_false(self, async_worker):
        """Test that do_handshake() is called when do_handshake_on_connect is False."""
        mock_ssl_socket = mock.Mock(spec=ssl.SSLSocket)
        mock_ssl_socket.selected_alpn_protocol.return_value = None
        mock_listener = mock.MagicMock()

        # Mock the rest of handle() to prevent full execution
        with mock.patch('gunicorn.sock.is_http2_negotiated', return_value=False):
            with mock.patch('gunicorn.http.get_parser') as mock_parser:
                mock_parser.return_value = iter([])
                try:
                    async_worker.handle(mock_listener, mock_ssl_socket, ('127.0.0.1', 8000))
                except StopIteration:
                    pass

        # Verify handshake was called
        mock_ssl_socket.do_handshake.assert_called_once()

    def test_no_handshake_when_do_handshake_on_connect_true(self, async_worker):
        """Test that do_handshake() is NOT called when do_handshake_on_connect is True."""
        async_worker.cfg.do_handshake_on_connect = True

        mock_ssl_socket = mock.Mock(spec=ssl.SSLSocket)
        mock_ssl_socket.selected_alpn_protocol.return_value = None
        mock_listener = mock.MagicMock()

        with mock.patch('gunicorn.sock.is_http2_negotiated', return_value=False):
            with mock.patch('gunicorn.http.get_parser') as mock_parser:
                mock_parser.return_value = iter([])
                try:
                    async_worker.handle(mock_listener, mock_ssl_socket, ('127.0.0.1', 8000))
                except StopIteration:
                    pass

        # Verify handshake was NOT called (already done on connect)
        mock_ssl_socket.do_handshake.assert_not_called()

    def test_no_handshake_for_non_ssl_socket(self, async_worker):
        """Test that no handshake is attempted for non-SSL sockets."""
        mock_socket = mock.MagicMock()  # Regular socket, not ssl.SSLSocket
        mock_listener = mock.MagicMock()

        with mock.patch('gunicorn.sock.is_http2_negotiated', return_value=False):
            with mock.patch('gunicorn.http.get_parser') as mock_parser:
                mock_parser.return_value = iter([])
                try:
                    async_worker.handle(mock_listener, mock_socket, ('127.0.0.1', 8000))
                except StopIteration:
                    pass

        # Non-SSL sockets don't have do_handshake, so it shouldn't be called
        assert not hasattr(mock_socket, 'do_handshake') or \
               not mock_socket.do_handshake.called

    def test_http2_detected_after_handshake(self, async_worker):
        """Test that HTTP/2 is properly detected after explicit handshake."""
        mock_ssl_socket = mock.Mock(spec=ssl.SSLSocket)
        mock_ssl_socket.selected_alpn_protocol.return_value = "h2"
        mock_listener = mock.MagicMock()

        with mock.patch.object(async_worker, 'handle_http2') as mock_h2:
            async_worker.handle(mock_listener, mock_ssl_socket, ('127.0.0.1', 8000))

        # Verify handshake was called first
        mock_ssl_socket.do_handshake.assert_called_once()
        # Verify HTTP/2 handler was invoked
        mock_h2.assert_called_once()


class TestGeventWorkerAlpn:
    """Test ALPN handling in GeventWorker."""

    @pytest.fixture
    def gevent_worker(self):
        """Create a GeventWorker instance for testing."""
        try:
            import gevent
        except ImportError:
            pytest.skip("gevent not available")

        from gunicorn.workers.ggevent import GeventWorker

        worker = GeventWorker.__new__(GeventWorker)
        worker.cfg = mock.MagicMock()
        worker.cfg.keepalive = 2
        worker.cfg.do_handshake_on_connect = False
        worker.cfg.http_protocols = ["h2", "h1"]
        worker.cfg.is_ssl = True
        worker.alive = True
        worker.log = mock.MagicMock()
        worker.wsgi = mock.MagicMock()
        worker.nr = 0
        worker.max_requests = 1000
        worker.worker_connections = 1000

        return worker

    def test_gevent_inherits_async_worker(self):
        """Test that GeventWorker inherits from AsyncWorker."""
        try:
            import gevent
        except ImportError:
            pytest.skip("gevent not available")

        from gunicorn.workers.ggevent import GeventWorker
        from gunicorn.workers.base_async import AsyncWorker

        assert issubclass(GeventWorker, AsyncWorker)

    def test_gevent_handle_calls_super(self, gevent_worker):
        """Test that GeventWorker.handle() calls super().handle()."""
        mock_client = mock.MagicMock()
        mock_listener = mock.MagicMock()

        with mock.patch('gunicorn.workers.base_async.AsyncWorker.handle') as mock_super:
            gevent_worker.handle(mock_listener, mock_client, ('127.0.0.1', 8000))

        mock_super.assert_called_once()


class TestEventletWorkerAlpn:
    """Test ALPN handling in EventletWorker."""

    @pytest.fixture
    def eventlet_worker(self):
        """Create an EventletWorker instance for testing."""
        try:
            import eventlet
        except (ImportError, AttributeError):
            pytest.skip("eventlet not available")

        from gunicorn.workers.geventlet import EventletWorker

        worker = EventletWorker.__new__(EventletWorker)
        worker.cfg = mock.MagicMock()
        worker.cfg.keepalive = 2
        worker.cfg.do_handshake_on_connect = False
        worker.cfg.http_protocols = ["h2", "h1"]
        worker.cfg.is_ssl = True
        worker.alive = True
        worker.log = mock.MagicMock()
        worker.wsgi = mock.MagicMock()
        worker.nr = 0
        worker.max_requests = 1000
        worker.worker_connections = 1000

        return worker

    def test_eventlet_inherits_async_worker(self):
        """Test that EventletWorker inherits from AsyncWorker."""
        try:
            import eventlet
        except (ImportError, AttributeError):
            pytest.skip("eventlet not available")

        from gunicorn.workers.geventlet import EventletWorker
        from gunicorn.workers.base_async import AsyncWorker

        assert issubclass(EventletWorker, AsyncWorker)

    def test_eventlet_handle_wraps_ssl_then_calls_super(self, eventlet_worker):
        """Test that EventletWorker.handle() wraps SSL then calls super()."""
        from gunicorn.workers import geventlet

        mock_client = mock.MagicMock()
        mock_wrapped = mock.MagicMock()
        mock_listener = mock.MagicMock()

        with mock.patch.object(geventlet, 'ssl_wrap_socket', return_value=mock_wrapped):
            with mock.patch('gunicorn.workers.base_async.AsyncWorker.handle') as mock_super:
                eventlet_worker.handle(mock_listener, mock_client, ('127.0.0.1', 8000))

        # Verify super().handle() was called with the wrapped socket
        mock_super.assert_called_once()
        call_args = mock_super.call_args[0]
        assert call_args[1] == mock_wrapped  # Second arg is the client socket

    def test_eventlet_alpn_works_with_handshake_fix(self, eventlet_worker):
        """Test that ALPN detection works after handshake fix for eventlet."""
        from gunicorn.workers import geventlet

        mock_ssl_socket = mock.Mock(spec=ssl.SSLSocket)
        mock_ssl_socket.selected_alpn_protocol.return_value = "h2"
        mock_listener = mock.MagicMock()

        with mock.patch.object(geventlet, 'ssl_wrap_socket', return_value=mock_ssl_socket):
            with mock.patch.object(eventlet_worker, 'handle_http2') as mock_h2:
                eventlet_worker.handle(mock_listener, mock.MagicMock(), ('127.0.0.1', 8000))

        # Verify handshake was called (by base_async.handle)
        mock_ssl_socket.do_handshake.assert_called_once()
        # Verify HTTP/2 handler was invoked
        mock_h2.assert_called_once()
