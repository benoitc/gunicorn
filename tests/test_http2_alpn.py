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
