# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for HTTP/2 cleartext (h2c) prior-knowledge support."""

import asyncio
import contextlib
import socket
import threading
from unittest import mock
import time

import pytest

# Check if h2 is available
try:
    import h2.connection  # pylint: disable=unused-import
    H2_AVAILABLE = True
except ImportError:
    H2_AVAILABLE = False

# The fast parser is an optional extra; FreeBSD CI has no wheel for it.
try:
    import gunicorn_h1c  # pylint: disable=unused-import
    H1C_AVAILABLE = True
except ImportError:
    H1C_AVAILABLE = False

PARSERS = [
    pytest.param("fast", marks=pytest.mark.skipif(
        not H1C_AVAILABLE, reason="gunicorn_h1c not available")),
    "python",
]

from gunicorn.config import Config
from gunicorn.http.errors import InvalidH2CPreface
from gunicorn.http.parser import RequestParser
from gunicorn.http2 import negotiation
from gunicorn.workers import base_async
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
    cfg.set("http2_cleartext", "prior-knowledge")
    return cfg


class TestH2CConfig:
    def test_disabled_by_default(self):
        assert Config().http2_cleartext == "off"

    def test_can_be_enabled(self):
        cfg = Config()
        cfg.set("http2_cleartext", "prior-knowledge")
        assert cfg.http2_cleartext == "prior-knowledge"


class TestH2CDisabled:
    def test_preface_ignored_when_h2c_off(self):
        """Without the flag, a preface-sending client gets HTTP/1.x."""
        cfg = Config()
        cfg.set("http_protocols", "h2,h1")
        conn, client = make_conn(cfg, negotiation.H2C_PREFACE)
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
        cfg.set("http2_cleartext", "prior-knowledge")
        conn, client = make_conn(cfg, negotiation.H2C_PREFACE)
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

        conn, client = make_conn(h2c_config(), negotiation.H2C_PREFACE)
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
        conn, client = make_conn(h2c_config(), negotiation.H2C_PREFACE[:10])
        sender = threading.Timer(
            0.05, client.sendall, args=(negotiation.H2C_PREFACE[10:],)
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
            assert time.monotonic() - start < negotiation.H2C_PREFACE_TIMEOUT
        finally:
            conn.sock.close()
            client.close()

    def test_partial_preface_times_out_rejected(self, monkeypatch):
        """A client that stalls mid-preface is rejected, not downgraded."""
        monkeypatch.setattr(negotiation, "H2C_PREFACE_TIMEOUT", 0.05)
        conn, client = make_conn(h2c_config(), negotiation.H2C_PREFACE[:10])
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
            h2c_config(), negotiation.H2C_PREFACE, addr=UNTRUSTED_ADDR
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
        conn, client = make_conn(cfg, negotiation.H2C_PREFACE, addr=UNTRUSTED_ADDR)
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
        conn, client = make_conn(h2c_config(), negotiation.H2C_PREFACE, addr="")
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
        conn, client = make_conn(cfg, negotiation.H2C_PREFACE)
        try:
            conn.init()
            assert conn.is_http2 is False
        finally:
            conn.sock.close()
            client.close()


class TestPrefaceMatch:
    """The pure matcher, shared by the blocking and push-based paths."""

    def test_complete_preface(self):
        assert negotiation.preface_match(negotiation.H2C_PREFACE) == negotiation.MATCH

    def test_prefix_is_partial(self):
        for n in range(1, len(negotiation.H2C_PREFACE)):
            assert negotiation.preface_match(
                negotiation.H2C_PREFACE[:n]) == negotiation.PARTIAL

    def test_empty_is_partial(self):
        assert negotiation.preface_match(b"") == negotiation.PARTIAL

    def test_divergence_is_mismatch(self):
        assert negotiation.preface_match(b"GET / HT") == negotiation.MISMATCH

    def test_trailing_bytes_after_preface_still_match(self):
        assert negotiation.preface_match(
            negotiation.H2C_PREFACE + b"\x00\x00\x00\x04") == negotiation.MATCH


class TestNegotiationPredicates:
    """Prior knowledge and upgrade are enabled separately."""

    def _cfg(self, mode):
        cfg = h2c_config()
        cfg.set("http2_cleartext", mode)
        return cfg

    TRUSTED = ("127.0.0.1", 1234)

    def test_prior_knowledge_only(self):
        cfg = self._cfg("prior-knowledge")
        assert negotiation.prior_knowledge_allowed(cfg, self.TRUSTED)
        assert not negotiation.upgrade_allowed(cfg, self.TRUSTED)

    def test_upgrade_only(self):
        cfg = self._cfg("upgrade")
        assert not negotiation.prior_knowledge_allowed(cfg, self.TRUSTED)
        assert negotiation.upgrade_allowed(cfg, self.TRUSTED)

    def test_both(self):
        cfg = self._cfg("both")
        assert negotiation.prior_knowledge_allowed(cfg, self.TRUSTED)
        assert negotiation.upgrade_allowed(cfg, self.TRUSTED)

    def test_off(self):
        cfg = self._cfg("off")
        assert not negotiation.prior_knowledge_allowed(cfg, self.TRUSTED)
        assert not negotiation.upgrade_allowed(cfg, self.TRUSTED)

    def test_untrusted_peer_never_negotiates(self):
        cfg = self._cfg("both")
        untrusted = ("203.0.113.9", 4444)
        assert not negotiation.prior_knowledge_allowed(cfg, untrusted)
        assert not negotiation.upgrade_allowed(cfg, untrusted)


class TestPrefaceDisconnect:
    """A peer that closes mid-preface is not a match, and does not hang."""

    def test_eof_before_the_preface_completes(self):
        server, client = socket.socketpair()
        try:
            client.sendall(negotiation.H2C_PREFACE[:8])
            client.close()
            matched, buf = negotiation.read_preface_blocking(server)
            assert not matched
            assert buf == negotiation.H2C_PREFACE[:8]
        finally:
            server.close()


class TestPrefaceDeadline:
    """The preface budget covers the whole preface, not each read."""

    def test_trickling_client_cannot_extend_the_budget(self, monkeypatch):
        monkeypatch.setattr(negotiation, "H2C_PREFACE_TIMEOUT", 0.25)
        server, client = socket.socketpair()
        stop = threading.Event()

        def trickle():
            # One byte every 0.1s: each read alone stays inside the budget,
            # so a per-read timeout would let this run for 24 intervals.
            for byte in negotiation.H2C_PREFACE:
                if stop.is_set():
                    return
                try:
                    client.sendall(bytes([byte]))
                except OSError:
                    return
                time.sleep(0.1)

        t = threading.Thread(target=trickle, daemon=True)
        t.start()
        try:
            started = time.monotonic()
            matched, _ = negotiation.read_preface_blocking(server)
            elapsed = time.monotonic() - started
            assert matched is False
            assert elapsed < 1.0, "budget was applied per read, not overall"
        finally:
            stop.set()
            server.close()
            client.close()
            t.join(timeout=2)


class _StubAsyncWorker(base_async.AsyncWorker):
    """AsyncWorker with everything but handle() stubbed out.

    handle() is the only method under test here; the rest would need a
    running arbiter.
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self.alive = True
        self.nr = 0
        self.log = mock.Mock()
        self.http2_calls = []
        self.upgrades = []
        self.errors = []

    def handle_http2(self, listener, client, addr, preface=b"", upgrade=None):
        self.http2_calls.append(preface)
        self.upgrades.append(upgrade)

    def handle_request(self, listener_name, req, sock, addr):
        pass

    def handle_error(self, req, client, addr, exc):
        self.errors.append(exc)

    def timeout_ctx(self):
        return contextlib.nullcontext()


def run_async_handle(cfg, client_data, addr=TRUSTED_ADDR, close_client=True):
    """Drive AsyncWorker.handle() over a socketpair. Returns the worker.

    ``close_client`` gives the HTTP/1 path an EOF to stop on. An upgrade
    needs the peer left open: the 101 is written before the handover, and a
    closed peer turns that write into an EPIPE.
    """
    server_sock, client_sock = socket.socketpair()
    listener = mock.Mock()
    listener.getsockname.return_value = ("127.0.0.1", 8000)
    worker = _StubAsyncWorker(cfg)
    try:
        if client_data:
            client_sock.sendall(client_data)
        if close_client:
            client_sock.close()
        worker.handle(listener, server_sock, addr)
    finally:
        server_sock.close()
        try:
            client_sock.close()
        except OSError:
            pass
    return worker


class TestH2CGevent:
    """The gevent/async worker negotiates the same way as gthread."""

    def test_preface_selects_http2(self):
        worker = run_async_handle(h2c_config(), negotiation.H2C_PREFACE)
        assert worker.http2_calls == [negotiation.H2C_PREFACE]
        assert worker.errors == []

    def test_http1_from_trusted_peer_rejected(self):
        worker = run_async_handle(h2c_config(), b"GET / HTTP/1.1\r\n\r\n")
        assert worker.http2_calls == []
        assert len(worker.errors) == 1
        assert isinstance(worker.errors[0], InvalidH2CPreface)

    def test_untrusted_peer_is_not_sniffed(self):
        # Not negotiated, so the preface reaches the HTTP/1 parser and is
        # refused there as a bad version: exactly what happens with the
        # feature off, and not the h2c rejection.
        worker = run_async_handle(
            h2c_config(), negotiation.H2C_PREFACE, addr=UNTRUSTED_ADDR)
        assert worker.http2_calls == []
        assert not any(isinstance(e, InvalidH2CPreface) for e in worker.errors)

    def test_untrusted_peer_still_serves_http1(self):
        worker = run_async_handle(
            h2c_config(), b"GET / HTTP/1.1\r\nHost: a\r\n\r\n",
            addr=UNTRUSTED_ADDR)
        assert worker.http2_calls == []
        assert worker.errors == []

    def test_disabled_by_default_changes_nothing(self):
        cfg = Config()
        cfg.set("http_protocols", "h2,h1")
        worker = run_async_handle(cfg, negotiation.H2C_PREFACE)
        assert worker.http2_calls == []
        assert not any(isinstance(e, InvalidH2CPreface) for e in worker.errors)

    def test_trusted_peer_serves_http1_when_disabled(self):
        cfg = Config()
        cfg.set("http_protocols", "h2,h1")
        worker = run_async_handle(cfg, b"GET / HTTP/1.1\r\nHost: a\r\n\r\n")
        assert worker.http2_calls == []
        assert worker.errors == []


class _FakeTransport:
    """Minimal asyncio transport for driving ASGIProtocol directly."""

    def __init__(self, peername=TRUSTED_ADDR):
        self.written = b""
        self.closed = False
        self._peername = peername

    def get_extra_info(self, name, default=None):
        if name == "peername":
            return self._peername
        if name == "sockname":
            return ("127.0.0.1", 8000)
        return default

    def write(self, data):
        self.written += data

    def close(self):
        self.closed = True

    def is_closing(self):
        return self.closed

    def can_write_eof(self):
        return True

    def write_eof(self):
        pass

    def set_write_buffer_limits(self, high=None, low=None):
        pass

    def pause_reading(self):
        pass

    def resume_reading(self):
        pass


def drain_task(loop, task):
    """Cancel a protocol task and let the loop deliver the cancellation.

    Closing the loop on a task suspended mid-await leaves the coroutine to be
    collected later, which surfaces as an unraisable GeneratorExit.
    """
    if task is None or task.done():
        return
    task.cancel()
    # Bounded: the HTTP/2 receive loop runs against a mock worker whose
    # `alive` is always truthy, so it need not stop, only observe the cancel.
    with contextlib.suppress(BaseException):
        loop.run_until_complete(asyncio.wait([task], timeout=0.5))


def make_asgi_protocol(cfg, loop):
    from gunicorn.asgi.protocol import ASGIProtocol

    worker = mock.Mock()
    worker.cfg = cfg
    worker.log = mock.Mock()
    worker.asgi = mock.Mock()
    worker.loop = loop
    worker.nr_conns = 0
    return ASGIProtocol(worker)


class TestH2CASGI:
    """The ASGI worker cannot read in connection_made, so it buffers."""

    def _connect(self, cfg, peername=TRUSTED_ADDR):
        loop = asyncio.new_event_loop()
        # StreamReader and create_task need the loop to be current, which it
        # is in production because data_received runs inside it.
        asyncio.set_event_loop(loop)
        proto = make_asgi_protocol(cfg, loop)
        transport = _FakeTransport(peername)
        proto.connection_made(transport)
        return proto, transport, loop

    def test_undecided_until_the_preface_resolves(self):
        proto, transport, loop = self._connect(h2c_config())
        try:
            assert proto._h2c_buffer == b""
            assert proto._callback_parser is None
            assert proto.reader is None
            # a prefix keeps it undecided, nothing is committed
            proto.data_received(negotiation.H2C_PREFACE[:8])
            assert proto._h2c_buffer == negotiation.H2C_PREFACE[:8]
            assert proto.reader is None
            assert not transport.closed
        finally:
            proto._h2c_cancel_timer()
            loop.close()
            asyncio.set_event_loop(None)

    def test_full_preface_commits_to_http2(self):
        proto, transport, loop = self._connect(h2c_config())
        try:
            proto.data_received(negotiation.H2C_PREFACE)
            assert proto._h2c_buffer is None
            assert proto.reader is not None
            assert not transport.closed
        finally:
            proto._h2c_cancel_timer()
            loop.close()
            asyncio.set_event_loop(None)

    def test_preface_split_across_reads(self):
        proto, transport, loop = self._connect(h2c_config())
        try:
            for byte in negotiation.H2C_PREFACE:
                proto.data_received(bytes([byte]))
            assert proto.reader is not None
            assert not transport.closed
        finally:
            proto._h2c_cancel_timer()
            loop.close()
            asyncio.set_event_loop(None)

    def test_http1_from_trusted_peer_is_refused(self):
        proto, transport, loop = self._connect(h2c_config())
        try:
            proto.data_received(b"GET / HTTP/1.1\r\n")
            assert proto.reader is None
            assert b"400" in transport.written
            assert transport.closed
        finally:
            proto._h2c_cancel_timer()
            loop.close()
            asyncio.set_event_loop(None)

    def test_untrusted_peer_takes_the_http1_path(self):
        proto, transport, loop = self._connect(
            h2c_config(), peername=UNTRUSTED_ADDR)
        try:
            assert proto._h2c_buffer is None
            assert proto._callback_parser is not None
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    def test_disabled_takes_the_http1_path(self):
        cfg = Config()
        cfg.set("http_protocols", "h2,h1")
        proto, transport, loop = self._connect(cfg)
        try:
            assert proto._h2c_buffer is None
            assert proto._callback_parser is not None
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    def test_stalled_preface_times_out(self):
        proto, transport, loop = self._connect(h2c_config())
        try:
            proto.data_received(negotiation.H2C_PREFACE[:4])
            assert proto._h2c_buffer is not None
            proto._h2c_undecided_timeout()          # what call_later would do
            assert proto.reader is None
            assert b"400" in transport.written
            assert transport.closed
        finally:
            proto._h2c_cancel_timer()
            loop.close()
            asyncio.set_event_loop(None)

    def test_buffer_cannot_grow_past_the_preface(self):
        proto, transport, loop = self._connect(h2c_config())
        try:
            # A large first chunk that is not a preface is refused at once,
            # it is never accumulated.
            proto.data_received(b"x" * 100_000)
            assert proto._h2c_buffer is None
            assert b"400" in transport.written
        finally:
            proto._h2c_cancel_timer()
            loop.close()
            asyncio.set_event_loop(None)

    def test_bytes_after_the_preface_reach_http2(self):
        proto, transport, loop = self._connect(h2c_config())
        try:
            trailing = b"\x00\x00\x00\x04\x00\x00\x00\x00\x00"   # SETTINGS
            proto.data_received(negotiation.H2C_PREFACE + trailing)
            assert proto._h2c_buffer is None
            assert proto.reader is not None
            # everything read while undecided is handed on, not dropped
            assert proto.reader._buffer == negotiation.H2C_PREFACE + trailing
        finally:
            proto._h2c_cancel_timer()
            loop.close()
            asyncio.set_event_loop(None)

    def test_connection_lost_while_undecided_clears_state(self):
        proto, transport, loop = self._connect(h2c_config())
        try:
            proto.data_received(negotiation.H2C_PREFACE[:6])
            assert proto._h2c_buffer is not None
            proto.connection_lost(None)
            assert proto._h2c_buffer is None
            assert proto._h2c_timer is None
        finally:
            loop.close()
            asyncio.set_event_loop(None)


class TestUpgradeDetection:
    """RFC 7540 3.2: what counts as an upgrade request."""

    def _req(self, headers):
        r = mock.Mock()
        r.headers = headers
        return r

    VALID = [("UPGRADE", "h2c"), ("HTTP2-SETTINGS", "AAMAAABk"),
             ("CONNECTION", "Upgrade, HTTP2-Settings")]

    def test_valid_upgrade(self):
        assert negotiation.upgrade_settings(self._req(self.VALID)) == b"AAMAAABk"

    def test_case_insensitive(self):
        headers = [("UPGRADE", "H2C"), ("HTTP2-SETTINGS", "AAMAAABk"),
                   ("CONNECTION", "upgrade, http2-settings")]
        assert negotiation.upgrade_settings(self._req(headers)) == b"AAMAAABk"

    def test_no_upgrade_header(self):
        assert negotiation.upgrade_settings(
            self._req([("CONNECTION", "keep-alive")])) is None

    def test_wrong_protocol(self):
        headers = [("UPGRADE", "websocket")] + self.VALID[1:]
        assert negotiation.upgrade_settings(self._req(headers)) is None

    def test_two_settings_headers_are_ambiguous(self):
        headers = [("UPGRADE", "h2c"), ("HTTP2-SETTINGS", "a"),
                   ("HTTP2-SETTINGS", "b"),
                   ("CONNECTION", "Upgrade, HTTP2-Settings")]
        assert negotiation.upgrade_settings(self._req(headers)) is None

    def test_settings_not_named_in_connection(self):
        headers = [("UPGRADE", "h2c"), ("HTTP2-SETTINGS", "a"),
                   ("CONNECTION", "Upgrade")]
        assert negotiation.upgrade_settings(self._req(headers)) is None


class TestMismatchPolicy:
    """A non-preface is only an error when prior knowledge stands alone."""

    def _cfg(self, mode):
        cfg = h2c_config()
        cfg.set("http2_cleartext", mode)
        return cfg

    def test_prior_knowledge_only_refuses(self):
        assert negotiation.mismatch_is_error(self._cfg("prior-knowledge"))

    def test_both_allows_http1_through(self):
        # otherwise the HTTP/1 request carrying an upgrade would be refused
        assert not negotiation.mismatch_is_error(self._cfg("both"))

    def test_upgrade_allows_http1_through(self):
        assert not negotiation.mismatch_is_error(self._cfg("upgrade"))


class _StubThreadWorker(gthread.ThreadWorker):
    """Enough of a gthread worker to drive handle_h2c_upgrade()."""

    def __init__(self, cfg):  # pylint: disable=super-init-not-called
        self.cfg = cfg
        self.log = mock.Mock()
        self.alive = True
        self.nr = 0
        self.max_requests = 1000
        self.served = []

    def handle_http2_request(self, req, conn, h2_conn):
        self.served.append(req)

    def handle_http2(self, conn):
        return False


@pytest.mark.skipif(not H2_AVAILABLE, reason="h2 library not available")
class TestUpgradeWithBody:
    """A payload on the upgrade request is body, not HTTP/2 frames.

    The payload and the frames behind it share one buffer. Collecting the
    frames before draining the payload hands it to the HTTP/2 state machine,
    which rejects it as a bad preamble.
    """

    REQUEST = (
        b"POST /p HTTP/1.1\r\nHost: x\r\nUpgrade: h2c\r\n"
        b"Connection: Upgrade, HTTP2-Settings\r\n"
        b"HTTP2-Settings: AAMAAABkAAQAoAAAAAIAAAAA\r\n"
        b"Content-Length: 11\r\n\r\nhello=world" + negotiation.H2C_PREFACE
    )

    def test_gthread(self):
        cfg = h2c_config()
        cfg.set("http2_cleartext", "upgrade")
        conn, client = make_conn(cfg, self.REQUEST)
        try:
            conn.init()
            # Without the fix the payload is collected as frames and the body
            # read blocks on a socket that will never carry it again. Fail
            # instead of hanging CI.
            conn.sock.settimeout(5)
            req = next(conn.parser)
            settings = negotiation.upgrade_settings(req)
            assert settings is not None

            worker = _StubThreadWorker(cfg)
            worker.handle_h2c_upgrade(conn, req, settings)

            assert len(worker.served) == 1
            assert worker.served[0].body.read() == b"hello=world"
            assert not worker.log.exception.called
        finally:
            client.close()
            conn.sock.close()

    def test_gevent_ignores_a_plain_request(self):
        cfg = h2c_config()
        cfg.set("http2_cleartext", "upgrade")
        worker = run_async_handle(cfg, b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
        assert worker.upgrades == []
        assert worker.http2_calls == []
        assert not worker.errors

    def test_gevent(self):
        cfg = h2c_config()
        cfg.set("http2_cleartext", "upgrade")
        worker = run_async_handle(cfg, self.REQUEST, close_client=False)

        assert len(worker.upgrades) == 1
        _settings, _req, body = worker.upgrades[0]
        assert body == b"hello=world"
        # only the frames are replayed into HTTP/2, never the payload
        assert worker.http2_calls == [negotiation.H2C_PREFACE]
        assert not worker.errors


UPGRADE_HEADERS = (
    b"Host: x\r\nUpgrade: h2c\r\n"
    b"Connection: Upgrade, HTTP2-Settings\r\n"
    b"HTTP2-Settings: AAMAAABkAAQAoAAAAAIAAAAA\r\n"
)


def upgrade_request(body=b"", chunked=False):
    """An Upgrade: h2c request, optionally carrying a payload."""
    if chunked:
        framing = b"Transfer-Encoding: chunked\r\n"
        payload = b"%x\r\n%s\r\n0\r\n\r\n" % (len(body), body) if body else b"0\r\n\r\n"
    elif body:
        framing = b"Content-Length: %d\r\n" % len(body)
        payload = body
    else:
        framing = b""
        payload = b""
    method = b"POST" if body else b"GET"
    return (method + b" /p HTTP/1.1\r\n" + UPGRADE_HEADERS + framing
            + b"\r\n" + payload)


def asgi_upgrade_config(parser="fast", mode="upgrade"):
    cfg = h2c_config()
    cfg.set("http2_cleartext", mode)
    cfg.set("http_parser", parser)
    return cfg


@pytest.mark.parametrize("parser", PARSERS)
class TestH2CASGIUpgrade:
    """Upgrade: h2c on the ASGI worker, over either callback parser.

    The two parsers split an upgrade request differently: the Python one
    delivers the payload through on_body, the fast one stops at the end of
    the headers and leaves it in front of the bytes that follow. The worker
    has to end up in the same place either way.
    """

    def _connect(self, cfg, peername=TRUSTED_ADDR):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        proto = make_asgi_protocol(cfg, loop)
        transport = _FakeTransport(peername)
        proto.connection_made(transport)
        return proto, transport, loop

    @contextlib.contextmanager
    def _protocol(self, cfg, peername=TRUSTED_ADDR):
        proto, transport, loop = self._connect(cfg, peername)
        try:
            yield proto, transport
        finally:
            proto._h2c_cancel_timer()
            drain_task(loop, proto._task)
            loop.close()
            asyncio.set_event_loop(None)

    def test_handover_takes_the_frames_and_leaves_nothing_behind(self, parser):
        with self._protocol(asgi_upgrade_config(parser)) as (proto, transport):
            proto.data_received(upgrade_request() + negotiation.H2C_PREFACE)
            assert proto._h2c_upgrade_settings == b"AAMAAABkAAQAoAAAAAIAAAAA"
            # the HTTP/1 parser is out of the way before the frames arrive
            assert proto._callback_parser is None
            assert bytes(proto.reader._buffer) == negotiation.H2C_PREFACE
            assert not transport.closed

    def test_payload_is_body_not_frames(self, parser):
        with self._protocol(asgi_upgrade_config(parser)) as (proto, transport):
            proto.data_received(
                upgrade_request(b"hello=world") + negotiation.H2C_PREFACE)
            assert bytes(proto._h2c_upgrade_body) == b"hello=world"
            assert bytes(proto.reader._buffer) == negotiation.H2C_PREFACE

    def test_waits_for_the_whole_payload(self, parser):
        with self._protocol(asgi_upgrade_config(parser)) as (proto, transport):
            whole = upgrade_request(b"hello=world") + negotiation.H2C_PREFACE
            proto.data_received(whole[:-30])
            # payload still incomplete: nothing may be handed over yet
            assert proto._callback_parser is not None
            assert proto.reader is None
            proto.data_received(whole[-30:])
            assert bytes(proto._h2c_upgrade_body) == b"hello=world"
            assert bytes(proto.reader._buffer) == negotiation.H2C_PREFACE

    def test_chunked_payload_is_decoded(self, parser):
        with self._protocol(asgi_upgrade_config(parser)) as (proto, transport):
            proto.data_received(upgrade_request(b"hello", chunked=True)
                                + negotiation.H2C_PREFACE)
            assert bytes(proto._h2c_upgrade_body) == b"hello"
            assert bytes(proto.reader._buffer) == negotiation.H2C_PREFACE

    def test_ordinary_request_is_untouched(self, parser):
        with self._protocol(asgi_upgrade_config(parser)) as (proto, transport):
            proto.data_received(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
            assert proto._h2c_upgrade_settings is None
            assert proto._callback_parser is not None
            assert proto.reader is None

    def test_untrusted_peer_is_not_upgraded(self, parser):
        with self._protocol(asgi_upgrade_config(parser),
                            peername=UNTRUSTED_ADDR) as (proto, transport):
            assert proto._h2c_upgrade_ok is False
            proto.data_received(upgrade_request() + negotiation.H2C_PREFACE)
            assert proto._h2c_upgrade_settings is None
            assert proto._callback_parser is not None

    def test_disabled_does_not_upgrade(self, parser):
        cfg = asgi_upgrade_config(parser, mode="prior-knowledge")
        # prior-knowledge alone: sniffing is on, upgrade is not
        with self._protocol(cfg) as (proto, transport):
            assert proto._h2c_upgrade_ok is False


class TestH2CASGIBothModes:
    """With both mechanisms on, a non-preface is not an error.

    The sniffer sees the HTTP/1 request that carries the upgrade before
    anything else does, so refusing every non-preface would reject exactly
    what ``both`` exists to accept.
    """

    def _connect(self, mode, peername=TRUSTED_ADDR):
        cfg = h2c_config()
        cfg.set("http2_cleartext", mode)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        proto = make_asgi_protocol(cfg, loop)
        transport = _FakeTransport(peername)
        proto.connection_made(transport)
        return proto, transport, loop

    @contextlib.contextmanager
    def _protocol(self, mode):
        proto, transport, loop = self._connect(mode)
        try:
            yield proto, transport
        finally:
            proto._h2c_cancel_timer()
            drain_task(loop, proto._task)
            loop.close()
            asyncio.set_event_loop(None)

    def test_upgrade_request_survives_the_sniffer(self):
        with self._protocol("both") as (proto, transport):
            proto.data_received(
                upgrade_request() + negotiation.H2C_PREFACE)
            assert b"400" not in transport.written
            assert proto._h2c_upgrade_settings is not None
            assert bytes(proto.reader._buffer) == negotiation.H2C_PREFACE

    def test_plain_http1_is_served(self):
        with self._protocol("both") as (proto, transport):
            proto.data_received(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
            assert b"400" not in transport.written
            assert not transport.closed
            assert proto._current_request is not None

    def test_prior_knowledge_alone_still_refuses(self):
        with self._protocol("prior-knowledge") as (proto, transport):
            proto.data_received(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
            assert b"400" in transport.written
            assert transport.closed

    def test_quiet_client_is_not_refused(self):
        with self._protocol("both") as (proto, transport):
            proto._h2c_undecided_timeout()
            assert b"400" not in transport.written
            assert not transport.closed
            assert proto._callback_parser is not None

    def test_timer_after_the_decision_does_nothing(self):
        with self._protocol("both") as (proto, transport):
            proto.data_received(negotiation.H2C_PREFACE)
            assert proto._h2c_buffer is None
            proto._h2c_undecided_timeout()      # late timer, already resolved
            assert not transport.closed
            assert b"400" not in transport.written

    def test_quiet_client_is_refused_under_prior_knowledge(self):
        with self._protocol("prior-knowledge") as (proto, transport):
            proto._h2c_undecided_timeout()
            assert b"400" in transport.written
            assert transport.closed


@pytest.mark.parametrize("parser", PARSERS)
class TestRemainingContract:
    """Both callback parsers answer remaining() the same way."""

    def _parser(self, parser):
        if parser == "fast":
            from gunicorn_h1c import H1CProtocol
            return H1CProtocol()
        from gunicorn.asgi.parser import PythonProtocol
        return PythonProtocol()

    def test_empty_before_the_message_completes(self, parser):
        p = self._parser(parser)
        p.feed(b"POST / HTTP/1.1\r\nHost: a\r\nContent-Length: 4\r\n\r\nab")
        assert not p.is_complete
        assert p.remaining() == b""

    def test_tail_after_the_body(self, parser):
        p = self._parser(parser)
        p.feed(b"POST / HTTP/1.1\r\nHost: a\r\nContent-Length: 4\r\n\r\nabcdTAIL")
        assert p.is_complete
        assert p.remaining() == b"TAIL"

    def test_reset_clears_it(self, parser):
        p = self._parser(parser)
        p.feed(b"GET / HTTP/1.1\r\nHost: a\r\n\r\nTAIL")
        assert p.remaining() == b"TAIL"
        p.reset()
        assert p.remaining() == b""


@pytest.mark.skipif(not H2_AVAILABLE, reason="h2 library not available")
class TestH2CASGIPriorKnowledgeEndToEnd:
    """Prior knowledge, driven end to end like the upgrade case.

    Covers the other half of _handle_http2_connection: the connection is
    initiated rather than upgraded, and every request comes off the receive
    loop instead of being synthesised as stream 1.
    """

    def test_request_is_served(self):
        import h2.config
        import h2.connection
        import h2.events

        seen = []

        async def app(scope, receive, send):
            await receive()
            seen.append((scope["http_version"], scope["method"], scope["path"]))
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"BODY"})

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        proto = None
        try:
            cfg = h2c_config()          # prior-knowledge
            worker = mock.Mock()
            worker.cfg = cfg
            worker.log = mock.Mock()
            worker.asgi = app
            worker.loop = loop
            worker.nr_conns = 0
            worker.nr = 0
            worker.max_requests = 1000
            from gunicorn.asgi.protocol import ASGIProtocol
            proto = ASGIProtocol(worker)
            transport = _FakeTransport()
            proto.connection_made(transport)

            client = h2.connection.H2Connection(
                config=h2.config.H2Configuration(
                    client_side=True, header_encoding="utf-8"))
            client.initiate_connection()
            client.send_headers(1, [
                (":method", "GET"), (":path", "/pk"),
                (":scheme", "http"), (":authority", "x"),
            ], end_stream=True)
            proto.data_received(client.data_to_send())

            async def until_answered():
                while b"BODY" not in transport.written:
                    await asyncio.sleep(0.005)
            loop.run_until_complete(
                asyncio.wait_for(until_answered(), timeout=5))

            assert not worker.log.exception.called
            assert seen == [("2", "GET", "/pk")]
            events = client.receive_data(transport.written)
            statuses = [dict(e.headers)[":status"] for e in events
                        if isinstance(e, h2.events.ResponseReceived)]
            assert statuses == ["200"]
        finally:
            if proto is not None:
                proto._h2c_cancel_timer()
                drain_task(loop, proto._task)
            loop.close()
            asyncio.set_event_loop(None)


@pytest.mark.skipif(not H1C_AVAILABLE, reason="gunicorn_h1c not available")
class TestH2CASGIUpgradeOversizedTail:
    """The fast parser caps remaining(); past the cap the tail is gone.

    Only that parser has a cap, so this is not parametrised. Handing h2 a
    tail with a hole in it would start the connection mid-frame, so the
    upgrade is refused instead.
    """

    def test_refused(self):
        cfg = asgi_upgrade_config("fast")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        proto = make_asgi_protocol(cfg, loop)
        transport = _FakeTransport()
        proto.connection_made(transport)
        try:
            # one feed: the tail has to be capped before the handover runs
            proto.data_received(upgrade_request() + b"\x00" * (64 * 1024 + 1))
            assert proto.reader is None
            assert b"400" in transport.written
            assert transport.closed
        finally:
            drain_task(loop, proto._task)
            loop.close()
            asyncio.set_event_loop(None)


@pytest.mark.skipif(not H2_AVAILABLE, reason="h2 library not available")
@pytest.mark.parametrize("parser", PARSERS)
class TestH2CASGIUpgradeEndToEnd:
    """Drive the whole handover and read the answer back as an h2 client.

    The unit tests above stop at the handover. This one runs the event loop
    and decodes what actually goes on the wire, because a mocked application
    will happily report success while the server answers 500.
    """

    def _run(self, parser, body=b"", chunked=False, raising=False):
        import h2.config
        import h2.connection
        import h2.events

        echoed = []

        async def app(scope, receive, send):
            payload = b""
            while True:
                message = await receive()
                payload += message.get("body", b"")
                if not message.get("more_body"):
                    break
            echoed.append((scope["type"], scope["http_version"],
                           scope["method"], scope["path"], payload))
            if raising:
                raise RuntimeError("boom")
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"BODY"})

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            cfg = asgi_upgrade_config(parser)
            worker = mock.Mock()
            worker.cfg = cfg
            worker.log = mock.Mock()
            # assigned before construction: ASGIProtocol captures worker.asgi
            worker.asgi = app
            worker.loop = loop
            worker.nr_conns = 0
            worker.nr = 0
            worker.max_requests = 1000
            from gunicorn.asgi.protocol import ASGIProtocol
            proto = ASGIProtocol(worker)
            transport = _FakeTransport()
            proto.connection_made(transport)

            client = h2.connection.H2Connection(
                config=h2.config.H2Configuration(
                    client_side=True, header_encoding="utf-8"))
            client.initiate_upgrade_connection()

            proto.data_received(upgrade_request(body, chunked)
                                + client.data_to_send())

            async def until_answered():
                while True:
                    if raising and worker.log.exception.called:
                        # the 500 is sent right after the log call
                        await asyncio.sleep(0.05)
                        return
                    if not raising and b"BODY" in transport.written:
                        return
                    await asyncio.sleep(0.005)
            loop.run_until_complete(
                asyncio.wait_for(until_answered(), timeout=5))

            if not raising:
                assert not worker.log.exception.called
            assert transport.written.startswith(negotiation.UPGRADE_101)
            events = client.receive_data(
                transport.written[len(negotiation.UPGRADE_101):])
            return echoed, events
        finally:
            drain_task(loop, proto._task)
            loop.close()
            asyncio.set_event_loop(None)

    def test_upgraded_request_is_served_over_http2(self, parser):
        import h2.events
        echoed, events = self._run(parser)

        assert echoed == [("http", "2", "GET", "/p", b"")]
        statuses = [dict(e.headers)[":status"] for e in events
                    if isinstance(e, h2.events.ResponseReceived)]
        assert statuses == ["200"]
        data = b"".join(e.data for e in events
                        if isinstance(e, h2.events.DataReceived))
        assert data == b"BODY"

    def test_payload_reaches_the_application(self, parser):
        echoed, _events = self._run(parser, body=b"hello=world")
        assert echoed == [("http", "2", "POST", "/p", b"hello=world")]

    def test_application_error_answers_500(self, parser):
        # answered by _handle_http2_request's own handler; the outer net in
        # _serve_http2_request only catches that handler itself failing
        import h2.events
        _echoed, events = self._run(parser, raising=True)
        statuses = [dict(e.headers)[":status"] for e in events
                    if isinstance(e, h2.events.ResponseReceived)]
        assert statuses == ["500"]

    def test_chunked_payload_reaches_the_application(self, parser):
        echoed, _events = self._run(parser, body=b"hello=world", chunked=True)
        assert echoed == [("http", "2", "POST", "/p", b"hello=world")]


@pytest.mark.skipif(not H2_AVAILABLE, reason="h2 library not available")
class TestUpgradeSynthesis:
    """The upgraded request becomes stream 1."""

    def _connection(self):
        from gunicorn.http2.connection import HTTP2ServerConnection
        server, client = socket.socketpair()
        cfg = h2c_config()
        conn = HTTP2ServerConnection(cfg, server, TRUSTED_ADDR)
        return conn, server, client

    def test_request_is_carried_over(self):
        import base64
        conn, server, client = self._connection()
        try:
            req = mock.Mock()
            req.method = "POST"
            req.uri = "/upgraded?x=1"
            req.scheme = "http"
            req.body = None
            req.headers = [("HOST", "example.com"), ("UPGRADE", "h2c"),
                           ("HTTP2-SETTINGS", "AAMAAABk"),
                           ("CONNECTION", "Upgrade, HTTP2-Settings"),
                           ("X-KEPT", "yes")]
            settings = base64.urlsafe_b64encode(
                b"\x00\x03\x00\x00\x00\x64").rstrip(b"=")
            h2req = conn.initiate_upgrade(settings, req)

            assert h2req.method == "POST"
            assert h2req.path == "/upgraded"
            assert h2req.query == "x=1"
            assert 1 in conn.streams
            names = [n for n, _ in h2req.headers]
            # hop-by-hop upgrade headers do not travel to HTTP/2
            assert "UPGRADE" not in names
            assert "HTTP2-SETTINGS" not in names
            assert "CONNECTION" not in names
            assert "X-KEPT" in names
        finally:
            server.close()
            client.close()

    def test_body_is_read_off_the_request_when_not_passed(self):
        import base64
        from io import BytesIO
        conn, server, client = self._connection()
        try:
            req = mock.Mock()
            req.method = "POST"
            req.uri = "/upgraded"
            req.scheme = "http"
            req.body = BytesIO(b"payload")
            req.headers = [("HOST", "example.com")]
            settings = base64.urlsafe_b64encode(
                b"\x00\x03\x00\x00\x00\x64").rstrip(b"=")
            # no body argument: the caller has not drained it yet
            h2req = conn.initiate_upgrade(settings, req)
            assert h2req.body.read() == b"payload"
        finally:
            server.close()
            client.close()
