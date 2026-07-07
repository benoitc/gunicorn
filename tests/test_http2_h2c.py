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
from gunicorn.http.parser import RequestParser
from gunicorn.workers import gthread


def make_conn(cfg, client_data=None):
    """Build a TConn around one end of a socketpair.

    Returns (conn, client_sock). Bytes in client_data are sent before
    TConn.init() runs, mimicking a client that talks first.
    """
    server_sock, client_sock = socket.socketpair()
    if client_data:
        client_sock.sendall(client_data)
    conn = gthread.TConn(cfg, server_sock, ("127.0.0.1", 0), None)
    return conn, client_sock


def h2c_config():
    cfg = Config()
    cfg.set("http_protocols", "h2,h1")
    cfg.set("h2c", True)
    return cfg


class TestH2CConfig:
    def test_disabled_by_default(self):
        assert Config().h2c is False

    def test_can_be_enabled(self):
        cfg = Config()
        cfg.set("h2c", True)
        assert cfg.h2c is True


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
        cfg.set("h2c", True)  # http_protocols left at default "h1"
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


class TestH2CFallback:
    def test_http1_request_falls_back_and_parses(self):
        """A plain HTTP/1.1 request must be served untouched, including
        the bytes consumed while sniffing the preface."""
        request = b"GET /ping HTTP/1.1\r\nHost: example.com\r\n\r\n"
        conn, client = make_conn(h2c_config(), request)
        try:
            conn.init()
            assert conn.is_http2 is False
            req = next(conn.parser)
            assert req.method == "GET"
            assert req.path == "/ping"
        finally:
            conn.sock.close()
            client.close()

    def test_diverging_bytes_fall_back_immediately(self):
        """First byte differs from the preface: no waiting occurs."""
        request = b"XGET /nope HTTP/1.1\r\n"
        conn, client = make_conn(h2c_config(), request)
        try:
            start = time.monotonic()
            conn.init()
            assert time.monotonic() - start < gthread.H2C_PREFACE_TIMEOUT
            assert conn.is_http2 is False
        finally:
            conn.sock.close()
            client.close()

    def test_partial_preface_times_out_to_http1(self, monkeypatch):
        """A client that stalls mid-preface ends up on HTTP/1.x."""
        monkeypatch.setattr(gthread, "H2C_PREFACE_TIMEOUT", 0.05)
        conn, client = make_conn(h2c_config(), gthread.H2C_PREFACE[:10])
        try:
            conn.init()
            assert conn.is_http2 is False
            # The consumed bytes were handed back to the HTTP/1.x parser
            assert conn.parser.unreader.buf.getvalue() == gthread.H2C_PREFACE[:10]
        finally:
            conn.sock.close()
            client.close()

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
