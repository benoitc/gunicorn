# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for HTTP/2 cleartext (h2c) prior-knowledge support."""

import socket
import threading
import time

import pytest

# Check if h2 is available
try:
    import h2.connection  # pylint: disable=unused-import
    H2_AVAILABLE = True
except ImportError:
    H2_AVAILABLE = False

from gunicorn.config import Config
from gunicorn.http.errors import InvalidH2CPreface
from gunicorn.http.parser import RequestParser
from gunicorn.workers import gthread

# An address inside the default forwarded_allow_ips ("127.0.0.1,::1").
TRUSTED_ADDR = ("127.0.0.1", 0)
# TEST-NET-3 (RFC 5737), never inside the default trust list.
UNTRUSTED_ADDR = ("203.0.113.7", 0)


def make_conn(cfg, client_data=None, addr=TRUSTED_ADDR):
    """Build a TConn around one end of a socketpair.

    Returns (conn, client_sock). Bytes in client_data are sent before
    TConn.init() runs, mimicking a client that talks first.
    """
    server_sock, client_sock = socket.socketpair()
    if client_data:
        client_sock.sendall(client_data)
    conn = gthread.TConn(cfg, server_sock, addr, None)
    return conn, client_sock


def h2c_config():
    cfg = Config()
    cfg.set("http_protocols", "h2,h1")
    cfg.set("http2_prior_knowledge", True)
    return cfg


class TestH2CConfig:
    def test_disabled_by_default(self):
        assert Config().http2_prior_knowledge is False

    def test_can_be_enabled(self):
        cfg = Config()
        cfg.set("http2_prior_knowledge", True)
        assert cfg.http2_prior_knowledge is True


class TestH2CDisabled:
    def test_preface_ignored_when_h2c_off(self):
        """Without the flag, a preface-sending client gets HTTP/1.x."""
        cfg = Config()
        cfg.set("http_protocols", "h2,h1")
        conn, client = make_conn(cfg, gthread.H2C_PREFACE)
        try:
            conn.init()
            assert conn.is_http2 is False
            assert isinstance(conn.parser, RequestParser)
        finally:
            conn.sock.close()
            client.close()

    def test_no_peek_when_h2_not_in_protocols(self):
        """h2c flag alone is not enough; h2 must be an enabled protocol."""
        cfg = Config()
        # http_protocols left at default "h1"
        cfg.set("http2_prior_knowledge", True)
        conn, client = make_conn(cfg, gthread.H2C_PREFACE)
        try:
            conn.init()
            assert conn.is_http2 is False
        finally:
            conn.sock.close()
            client.close()


@pytest.mark.skipif(not H2_AVAILABLE, reason="h2 library not available")
class TestH2CPriorKnowledge:
    def test_preface_selects_http2(self):
        from gunicorn.http2.connection import HTTP2ServerConnection

        conn, client = make_conn(h2c_config(), gthread.H2C_PREFACE)
        try:
            conn.init()
            assert conn.is_http2 is True
            assert isinstance(conn.parser, HTTP2ServerConnection)
            # initiate_connection() must have sent the server SETTINGS frame
            client.settimeout(1.0)
            assert client.recv(1024)
        finally:
            conn.sock.close()
            client.close()

    def test_split_preface_selects_http2(self):
        """Preface arriving in two segments is still recognized."""
        conn, client = make_conn(h2c_config(), gthread.H2C_PREFACE[:10])
        sender = threading.Timer(
            0.05, client.sendall, args=(gthread.H2C_PREFACE[10:],)
        )
        sender.start()
        try:
            conn.init()
            assert conn.is_http2 is True
        finally:
            sender.join()
            conn.sock.close()
            client.close()


class TestH2CTrustedPeerRejection:
    """A trusted peer on a prior-knowledge port must speak HTTP/2.

    Anything else is rejected with InvalidH2CPreface (mapped to a 400 by
    the worker) instead of being silently downgraded to HTTP/1.x.
    """

    def test_http1_request_rejected(self):
        request = b"GET /ping HTTP/1.1\r\nHost: example.com\r\n\r\n"
        conn, client = make_conn(h2c_config(), request)
        try:
            with pytest.raises(InvalidH2CPreface):
                conn.init()
        finally:
            conn.sock.close()
            client.close()

    def test_diverging_bytes_rejected_immediately(self):
        """First byte differs from the preface: no waiting occurs."""
        request = b"XGET /nope HTTP/1.1\r\n"
        conn, client = make_conn(h2c_config(), request)
        try:
            start = time.monotonic()
            with pytest.raises(InvalidH2CPreface):
                conn.init()
            assert time.monotonic() - start < gthread.H2C_PREFACE_TIMEOUT
        finally:
            conn.sock.close()
            client.close()

    def test_partial_preface_times_out_rejected(self, monkeypatch):
        """A client that stalls mid-preface is rejected, not downgraded."""
        monkeypatch.setattr(gthread, "H2C_PREFACE_TIMEOUT", 0.05)
        conn, client = make_conn(h2c_config(), gthread.H2C_PREFACE[:10])
        try:
            with pytest.raises(InvalidH2CPreface):
                conn.init()
        finally:
            conn.sock.close()
            client.close()


class TestH2CUntrustedPeer:
    """Peers outside forwarded_allow_ips never get the preface sniffed."""

    def test_preface_from_untrusted_peer_gets_http1(self):
        conn, client = make_conn(
            h2c_config(), gthread.H2C_PREFACE, addr=UNTRUSTED_ADDR
        )
        try:
            conn.init()
            assert conn.is_http2 is False
            assert isinstance(conn.parser, RequestParser)
        finally:
            conn.sock.close()
            client.close()

    def test_http1_from_untrusted_peer_parses(self):
        """Untrusted h1 traffic is byte-for-byte unaffected by the flag."""
        request = b"GET /ping HTTP/1.1\r\nHost: example.com\r\n\r\n"
        conn, client = make_conn(h2c_config(), request, addr=UNTRUSTED_ADDR)
        try:
            conn.init()
            assert conn.is_http2 is False
            req = next(conn.parser)
            assert req.method == "GET"
            assert req.path == "/ping"
        finally:
            conn.sock.close()
            client.close()

    @pytest.mark.skipif(not H2_AVAILABLE, reason="h2 library not available")
    def test_wildcard_allow_list_trusts_any_peer(self):
        cfg = h2c_config()
        cfg.set("forwarded_allow_ips", "*")
        conn, client = make_conn(cfg, gthread.H2C_PREFACE, addr=UNTRUSTED_ADDR)
        try:
            conn.init()
            assert conn.is_http2 is True
        finally:
            conn.sock.close()
            client.close()

    @pytest.mark.skipif(not H2_AVAILABLE, reason="h2 library not available")
    def test_unix_socket_peer_is_trusted(self):
        """Non-tuple peer addresses (unix sockets) follow the
        forwarded-header policy and are trusted."""
        conn, client = make_conn(h2c_config(), gthread.H2C_PREFACE, addr="")
        try:
            conn.init()
            assert conn.is_http2 is True
        finally:
            conn.sock.close()
            client.close()


class TestH2CProtocolGuard:
    def test_uwsgi_protocol_not_sniffed(self):
        """The uwsgi protocol has its own parser; h2c must not touch it."""
        cfg = h2c_config()
        cfg.set("protocol", "uwsgi")
        conn, client = make_conn(cfg, gthread.H2C_PREFACE)
        try:
            conn.init()
            assert conn.is_http2 is False
        finally:
            conn.sock.close()
            client.close()
