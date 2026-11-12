#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
ASGI protocol handler for gunicorn.

Implements asyncio.Protocol to handle HTTP/1.x and HTTP/2 connections
and dispatch to ASGI applications.
"""

import asyncio
import base64
import binascii
import collections
import errno
from http import HTTPStatus
import ipaddress
import logging
import re
import time

from gunicorn.asgi.unreader import AsyncUnreader
from gunicorn.asgi.parser import (
    PythonProtocol, CallbackRequest, ParseError,
    LimitRequestLine, LimitRequestHeaders, InvalidChunkExtension,
    UnsupportedTransferCoding,
)
from gunicorn.asgi.uwsgi import AsyncUWSGIRequest
from gunicorn.http.errors import InvalidResponseHeader, InvalidResponseHeaderName, NoMoreData
from gunicorn.http.errors import ParseException as HTTPParseException
from gunicorn.http.message import TOKEN_RE, HeaderPolicy
from gunicorn.http.wsgi import HEADER_VALUE_RE
from gunicorn.http2 import negotiation
from gunicorn.http2.errors import HTTP2ConnectionError, HTTP2ErrorCode, HTTP2StreamError
from gunicorn.http2.stream import StreamState
from gunicorn.uwsgi.errors import UWSGIParseException


class _RequestTime:
    """Lightweight request time container compatible with logging atoms.

    Uses time.monotonic() elapsed seconds instead of datetime.now() syscalls.
    Provides .seconds and .microseconds attributes for glogging.py compatibility.
    """

    __slots__ = ('seconds', 'microseconds')

    def __init__(self, elapsed):
        self.seconds = int(elapsed)
        self.microseconds = int((elapsed - self.seconds) * 1_000_000)


def _normalize_sockaddr(sockaddr):
    """Normalize socket address to ASGI-compatible (host, port) tuple.

    ASGI spec requires server/client to be (host, port) tuples.
    IPv6 sockets return 4-tuples (host, port, flowinfo, scope_id),
    so we extract just the first two elements.
    """
    return tuple(sockaddr[:2]) if sockaddr else None


def _check_trusted_proxy(peer_addr, allow_list, networks):
    """Check if peer address is in the trusted proxy list.

    Cached at connection start to avoid repeated IP parsing per request.
    """
    if not isinstance(peer_addr, tuple):
        return False
    if '*' in allow_list:
        return True
    try:
        ip = ipaddress.ip_address(peer_addr[0])
    except ValueError:
        return False
    for network in networks:
        if ip in network:
            return True
    return False


# Response header checks, same rules as the WSGI Response.process_headers
_HEADER_NAME_RE = re.compile(TOKEN_RE.pattern.encode("latin-1"))
_HEADER_VALUE_RE = re.compile(HEADER_VALUE_RE.pattern.encode("latin-1"))


def _validate_response_headers(headers):
    """Reject response headers that would break HTTP/1.1 framing.

    Names must be tokens and values must not contain CR, LF or other
    control characters, otherwise an app echoing request data into a
    header can split the response.
    """
    for name, value in headers:
        if isinstance(name, str):
            name = name.encode("latin-1")
        if isinstance(value, str):
            value = value.encode("latin-1")
        if not _HEADER_NAME_RE.fullmatch(name):
            raise InvalidResponseHeaderName('%r' % name)
        if not _HEADER_VALUE_RE.fullmatch(value):
            # Pass only the name, the value may carry sensitive data
            raise InvalidResponseHeader('%r' % name)


def _scan_response_headers(headers):
    """Validate response headers and find their framing fields, in one pass.

    Same checks as _validate_response_headers(). Returns
    (has_content_length, content_length_value, has_transfer_encoding).
    """
    has_content_length = False
    has_transfer_encoding = False
    content_length_value = None
    for name, value in headers:
        bname = name.encode("latin-1") if isinstance(name, str) else name
        bvalue = value.encode("latin-1") if isinstance(value, str) else value
        if not _HEADER_NAME_RE.fullmatch(bname):
            raise InvalidResponseHeaderName('%r' % bname)
        if not _HEADER_VALUE_RE.fullmatch(bvalue):
            # Pass only the name, the value may carry sensitive data
            raise InvalidResponseHeader('%r' % bname)
        lowered = bname.lower()
        if lowered == b"content-length":
            has_content_length = True
            content_length_value = value
        elif lowered == b"transfer-encoding":
            has_transfer_encoding = True
    return has_content_length, content_length_value, has_transfer_encoding


class _RequestHeaderPolicy(HeaderPolicy):
    """Run the header policy shared with WSGI and HTTP/2 on an HTTP/1
    request parsed by the ASGI worker: scheme headers and underscore names
    are honored only from peers in ``forwarded_allow_ips``."""

    # Expect: 100-continue is handled by the ASGI body receiver.
    _policy_expect_continue = False

    def __init__(self, cfg, peer_addr, scheme, version):
        self.cfg = cfg
        self.peer_addr = peer_addr
        self.scheme = scheme
        self.version = version

    def apply(self, request, trust=None, secure_names=None):
        """Apply the policy to the request's (lower-case bytes) headers.

        ``trust`` is _peer_trusted_for_forwarded() and ``secure_names`` is
        secure_scheme_names() of its first item, passed in when the caller
        already knows them for this peer.
        """
        secure_scheme_headers, forwarder_headers = (
            trust if trust is not None else self._peer_trusted_for_forwarded())
        if secure_names is None:
            secure_names = secure_scheme_names(secure_scheme_headers)
        scheme_state = [False]
        seen = set()
        drop = None
        headers_bytes = request.headers_bytes
        for index, (name, value) in enumerate(headers_bytes):
            # Only a scheme header or a name with '_' can be acted on here:
            # Expect is off for this policy, and the singleton fields were
            # checked by CallbackRequest.from_parser(). Others are kept.
            if b'_' in name or name in secure_names:
                kept = self._apply_header_policy(
                    name.decode('latin-1').upper(), value.decode('latin-1'),
                    scheme_state, seen, secure_scheme_headers, forwarder_headers)
                if kept is None:
                    if drop is None:
                        drop = set()
                    drop.add(index)
        if drop:
            str_headers = getattr(request, '_headers', None)
            request.headers_bytes = [
                h for i, h in enumerate(headers_bytes) if i not in drop]
            if str_headers is not None:
                request.headers = [
                    h for i, h in enumerate(str_headers) if i not in drop]
        request.scheme = self.scheme


def secure_scheme_names(secure_scheme_headers):
    """The secure_scheme_headers names as lower-case bytes."""
    return frozenset(name.lower().encode('latin-1')
                     for name in secure_scheme_headers)


# Cached response bytes for common cases
_CACHED_STATUS_LINES = {}
_CACHED_SERVER_HEADER = b"Server: gunicorn/asgi\r\n"

# Date header cache (updated once per second)
_cached_date_header = b""
_cached_date_time = 0.0

# Pre-compute common chunk size prefixes to avoid repeated formatting
# A body at least this large is handed to the transport as it is, next to
# the headers or chunk framing, instead of being joined to them: the join
# would copy it, and the copy would stay alive until the socket took it.
_NO_COPY_BODY_SIZE = 65536

_CHUNK_PREFIXES = {i: f"{i:x}\r\n".encode("latin-1") for i in range(16384)}

# High water mark for write buffer backpressure (64KB)
HIGH_WATER_LIMIT = 65536

# HTTP/1 application calls that may still be running on one connection after
# their response went out (background tasks, cleanup). The next request waits
# while this many are left.
_MAX_FINISHING_APP_CALLS = 16


class ClientDisconnected(OSError):
    """Raised from an HTTP/2 send() once the peer reset the stream or left.

    ASGI 2.4 asks for an OSError subclass on a closed connection.
    """


def _valid_websocket_key(key):
    """RFC 6455 section 4.2.1: base64 of 16 bytes."""
    if not key:
        return False
    try:
        return len(base64.b64decode(key, validate=True)) == 16
    except (ValueError, binascii.Error):
        return False


class FlowControl:
    """Manage transport-level write flow control.

    Blocks send() when transport buffer exceeds high water mark,
    preventing memory issues with large streaming responses.
    """
    __slots__ = ('_transport', 'read_paused', 'write_paused', '_is_writable_event')

    def __init__(self, transport):
        self._transport = transport
        self.read_paused = False
        self.write_paused = False
        self._is_writable_event = asyncio.Event()
        self._is_writable_event.set()

    async def drain(self):
        """Wait until transport is writable."""
        await self._is_writable_event.wait()

    def pause_reading(self):
        if not self.read_paused:
            self.read_paused = True
            self._transport.pause_reading()

    def resume_reading(self):
        if self.read_paused:
            self.read_paused = False
            self._transport.resume_reading()

    def pause_writing(self):
        if not self.write_paused:
            self.write_paused = True
            self._is_writable_event.clear()

    def resume_writing(self):
        if self.write_paused:
            self.write_paused = False
            self._is_writable_event.set()


def _get_cached_date_header():
    """Get cached Date header, updating once per second."""
    global _cached_date_header, _cached_date_time  # pylint: disable=global-statement
    now = time.time()
    if now - _cached_date_time >= 1.0:
        # Update date header
        from email.utils import formatdate
        _cached_date_header = f"Date: {formatdate(usegmt=True)}\r\n".encode("latin-1")
        _cached_date_time = now
    return _cached_date_header


# Reason phrases for the status line, built once.
_REASON_PHRASES = {
    100: "Continue",
    101: "Switching Protocols",
    103: "Early Hints",
    200: "OK",
    201: "Created",
    202: "Accepted",
    204: "No Content",
    206: "Partial Content",
    301: "Moved Permanently",
    302: "Found",
    303: "See Other",
    304: "Not Modified",
    307: "Temporary Redirect",
    308: "Permanent Redirect",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    408: "Request Timeout",
    409: "Conflict",
    410: "Gone",
    411: "Length Required",
    413: "Payload Too Large",
    414: "URI Too Long",
    415: "Unsupported Media Type",
    422: "Unprocessable Entity",
    429: "Too Many Requests",
    500: "Internal Server Error",
    501: "Not Implemented",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Gateway Timeout",
}


def _get_cached_status_line(version, status, reason=None):
    """Get cached status line bytes; the reason phrase is only looked up
    the first time a (version, status) pair is seen."""
    line = _CACHED_STATUS_LINES.get((version, status))
    if line is None:
        if reason is None:
            reason = _REASON_PHRASES.get(status, "Unknown")
        line = f"HTTP/{version[0]}.{version[1]} {status} {reason}\r\n".encode("latin-1")
        _CACHED_STATUS_LINES[(version, status)] = line
    return line


class ASGIResponseInfo:
    """Simple container for ASGI response info for access logging."""

    def __init__(self, status, headers, sent):
        self.status = status
        self.sent = sent
        # Convert headers to list of string tuples for logging
        self.headers = []
        for name, value in headers:
            if isinstance(name, bytes):
                name = name.decode("latin-1")
            if isinstance(value, bytes):
                value = value.decode("latin-1")
            self.headers.append((name, value))


class BodyReceiver:
    """Body receiver for callback-based parsers.

    Body chunks are fed directly via the feed() method from parser callbacks.
    Uses Future-based waiting for efficient async receive().
    """

    __slots__ = ('_chunks', '_buffered', '_source', '_complete', '_body_finished',
                 '_closed', '_body_wait_expired', '_waiter', 'request', 'protocol',
                 'expect_continue')

    def __init__(self, request, protocol):
        self.request = request
        self.protocol = protocol
        # Chunks wait here until the app receives them. The protocol pauses
        # reading from the socket while too many bytes wait (see
        # ASGIProtocol._is_buffer_full), so this stays bounded.
        self._chunks = collections.deque()
        self._buffered = 0
        # Optional coroutine function returning the next body chunk (b'' at
        # the end): the uWSGI path reads its body as the app asks for it.
        self._source = None
        self._complete = False
        self._body_finished = False  # True after returning more_body=False
        # _closed means the client transport has gone away (signal_disconnect
        # was called or the protocol detected a disconnect).  _body_wait_expired
        # means the body did not finish framing within the configured timeout
        # but the transport itself may still be open.  Both surface as
        # http.disconnect to the app, but they are distinct conditions.
        self._closed = False
        self._body_wait_expired = False
        self._waiter = None
        # RFC 9110 section 10.1.1: the client may hold the body back until it
        # sees a 100 (Continue). It goes out when the app first asks for the
        # body; a final response sent before that clears it.
        self.expect_continue = getattr(request, '_expect_100_continue', False) is True

    def feed(self, chunk):
        """Feed a body chunk directly (called by parser callback)."""
        if chunk:
            # The client sent the body without waiting: no 100 is needed.
            self.expect_continue = False
            self._chunks.append(chunk)
            self._buffered += len(chunk)
            self._wake_waiter()

    @property
    def buffered(self):
        """Bytes received but not yet handed to the app."""
        return self._buffered

    def set_complete(self):
        """Mark body as complete (called when message ends)."""
        self._complete = True
        self._wake_waiter()

    def signal_disconnect(self):
        """Signal that the client transport has gone away."""
        self._closed = True
        self._wake_waiter()

    @property
    def _disconnected(self):
        """True when the receiver should yield http.disconnect to the app."""
        return self._closed or self._body_wait_expired

    def _wake_waiter(self):
        """Wake up any pending receive() call."""
        if self._waiter is not None and not self._waiter.done():
            self._waiter.set_result(None)

    async def receive(self):  # pylint: disable=too-many-return-statements
        """ASGI receive callable - returns body chunks or disconnect."""
        # Already disconnected (transport closed or body wait timed out)
        if self._disconnected:
            return {"type": "http.disconnect"}

        # Body finished but not disconnected - wait for actual disconnect
        # This is needed for frameworks like Django that listen for disconnect
        if self._body_finished:
            await self._wait_for_disconnect()
            return {"type": "http.disconnect"}

        # Fast path: chunk already available
        if self._chunks:
            return self._pop_chunk()

        # Body complete with no more chunks
        if self._complete:
            self._body_finished = True
            return {"type": "http.request", "body": b"", "more_body": False}

        # No body expected
        if self.request.content_length == 0 and not self.request.chunked:
            self._complete = True
            self._body_finished = True
            return {"type": "http.request", "body": b"", "more_body": False}

        # Check protocol closed state
        if self.protocol._closed:
            self._closed = True
            return {"type": "http.disconnect"}

        # Pull source (uWSGI): read the next piece only when the app asks.
        if self._source is not None:
            chunk = await self._source()
            if chunk:
                return {"type": "http.request", "body": chunk, "more_body": True}
            self._complete = True
            self._body_finished = True
            return {"type": "http.request", "body": b"", "more_body": False}

        if self.expect_continue:
            self.expect_continue = False
            self.protocol._safe_write(b"HTTP/1.1 100 Continue\r\n\r\n")

        # Wait for body chunk to arrive via callback.  A real disconnect or a
        # body-wait expiry is surfaced by _wait_for_data via _disconnected; a
        # task cancellation propagates to the app rather than being masked as
        # http.disconnect (#3627).
        await self._wait_for_data()
        return self._build_receive_result()

    def _pop_chunk(self):
        """Pop a chunk and return the appropriate message."""
        chunk = self._chunks.popleft()
        self._buffered -= len(chunk)
        self.protocol._maybe_resume_reading()
        more = bool(self._chunks) or not self._complete
        if not more:
            self._body_finished = True
        return {"type": "http.request", "body": chunk, "more_body": more}

    def _build_receive_result(self):
        """Build receive result after waiting for data."""
        if self._disconnected:
            return {"type": "http.disconnect"}

        if self._chunks:
            return self._pop_chunk()

        if self._complete:
            self._body_finished = True
            return {"type": "http.request", "body": b"", "more_body": False}

        # Wait returned without data and the message was not framed complete:
        # treat as a body-wait expiry rather than synthesizing end-of-body
        # (which would desync the next pipelined request).
        self._body_wait_expired = True
        return {"type": "http.disconnect"}

    async def _wait_for_data(self):
        """Wait for body data to arrive via callback."""
        if self._chunks or self._complete or self._disconnected:
            return

        # Create a new waiter
        loop = asyncio.get_event_loop()
        self._waiter = loop.create_future()

        # Bound the wait by the configured worker timeout (default 30s).
        # The protocol-level timeout drives transport disconnect handling;
        # this only needs to escape an idle wait if data never arrives.
        cfg = getattr(self.protocol, 'cfg', None)
        timeout = getattr(cfg, 'timeout', None) if cfg is not None else None
        if not timeout or timeout <= 0:
            timeout = 30.0

        try:
            await asyncio.wait_for(self._waiter, timeout=timeout)
        except asyncio.TimeoutError:
            # No data arrived in time: mark body-wait as expired so receive()
            # yields http.disconnect rather than a fake terminal http.request
            # with more_body=False.  The transport itself may still be alive;
            # _closed stays False so any code keying on transport-disconnect
            # only is unaffected.
            self._body_wait_expired = True
        finally:
            self._waiter = None

    async def _wait_for_disconnect(self):
        """Wait for connection to close after body is finished.

        This is needed for ASGI apps (like Django) that call receive()
        to listen for client disconnect after the request body is consumed.
        """
        if self._closed:
            return

        # Check protocol closed state first
        if self.protocol._closed:
            self._closed = True
            return

        # Create a new waiter to wait for disconnect
        loop = asyncio.get_event_loop()
        self._waiter = loop.create_future()

        # Wait for a real transport disconnect.  If the application's task is
        # cancelled (eg the framework cancels its disconnect listener once the
        # response is done), let CancelledError propagate instead of swallowing
        # it and returning http.disconnect.  Swallowing it makes frameworks like
        # Django raise RequestAborted in place of running response.close(),
        # which skips request_finished and leaks DB connections (#3627).
        try:
            await self._waiter
        finally:
            self._waiter = None
            self._closed = True


def _pre_request_hook(cfg, log):
    """The pre_request hook to call, or None when calling it would do
    nothing: the default hook only logs the request at debug level,
    through a logger whose debug() goes to the error log."""
    hook = getattr(cfg, "pre_request", None)
    settings = getattr(cfg, "settings", None)
    if not isinstance(settings, dict) or "pre_request" not in settings:
        return hook
    if hook is not settings["pre_request"].default:
        return hook
    from gunicorn.glogging import Logger
    from gunicorn.instrument.statsd import Statsd
    error_log = getattr(log, "error_log", None)
    if (getattr(type(log), "debug", None) in (Logger.debug, Statsd.debug)
            and error_log is not None
            and not error_log.isEnabledFor(logging.DEBUG)):
        return None
    return hook


def _relay_result(task, future):
    """Pass a finished task's outcome on to ``future`` unless it has one."""
    if future.done():
        return
    if task.cancelled():
        future.cancel()
    elif task.exception() is not None:
        future.set_exception(task.exception())
    else:
        future.set_result(task.result())


def _post_request_hook(cfg):
    """The post_request hook to call, or None for the default one, which
    does nothing."""
    hook = getattr(cfg, "post_request", None)
    settings = getattr(cfg, "settings", None)
    if (isinstance(settings, dict) and "post_request" in settings
            and hook is settings["post_request"].default):
        return None
    return hook


class ASGIProtocol(asyncio.Protocol):
    """HTTP/1.1 protocol handler for ASGI applications.

    Handles connection lifecycle, request parsing, and ASGI app invocation.
    Uses callback-based parsing (H1CProtocol/PythonProtocol) for efficient
    incremental parsing in data_received().
    """

    # Class-level cache for H1CProtocol availability
    _h1c_available = None
    _h1c_protocol_class = None
    _h1c_has_limits = False  # True if >= 0.4.1 (has limit parameters)
    _h1c_limit_request_line = None  # Exception class from gunicorn_h1c >= 0.4.1
    _h1c_limit_request_headers = None  # Exception class from gunicorn_h1c >= 0.4.1
    _h1c_invalid_chunk_extension = None  # Exception class from gunicorn_h1c >= 0.6.3
    _h1c_parse_errors = ()  # Every other request error gunicorn_h1c raises
    _h1c_unsupported_transfer_coding = None  # When gunicorn_h1c defines it

    def __init__(self, worker):
        self.worker = worker
        self.cfg = cfg = worker.cfg
        self.log = worker.log
        self.app = worker.asgi
        # Settings read on every request, read once per connection instead.
        # A configuration reload starts new workers, so they cannot change
        # under a live connection.
        # getattr with the settings' defaults: a partial config (tests,
        # embedders) used to work as long as these were not needed.
        self._keepalive = getattr(cfg, "keepalive", 2)
        self._root_path = getattr(cfg, "root_path", "") or ""
        self._pre_request = _pre_request_hook(cfg, worker.log)
        self._post_request = _post_request_hook(cfg)
        self._uses_uwsgi = getattr(cfg, "protocol", "http") == "uwsgi"
        self._proxy_protocol = getattr(cfg, "proxy_protocol", "off")
        # (secure_scheme_headers, forwarder_headers) this peer may set,
        # decided on the first request: the peer cannot change either.
        self._forwarded_trust = None
        self._secure_names = None
        # (sockname, peername, scope server, scope client), see
        # _build_http_scope()
        self._scope_addresses = None
        # Tasks serving HTTP/2 streams on this connection
        self._h2_tasks = set()
        # Stand-in protocol behind the HTTP/2 StreamWriter; drain() waits on it
        self._h2_writer_protocol = None
        # Transport asked us to stop writing: we stop reading as well
        self._write_paused = False

        self.transport = None
        self.reader = None  # Only used for HTTP/2
        # Set to a bytes buffer while sniffing for the cleartext HTTP/2
        # connection preface, before either protocol has been committed to.
        self._h2c_buffer = None
        self._h2c_timer = None
        # Upgrade: h2c. ``_h2c_upgrade_ok`` is the per-connection decision;
        # the other two are per-request and only set once one is under way.
        self._h2c_upgrade_ok = False
        self._h2c_upgrade_settings = None
        self._h2c_upgrade_body = None
        self.writer = None
        self._task = None
        self.req_count = 0

        # Connection state
        self._closed = False
        # Guards the connection_lost() cleanup so it runs exactly once. Kept
        # separate from ``_closed`` because a server-initiated close sets
        # ``_closed`` early (in _close_transport), and connection_lost() must
        # still run its cleanup (e.g. decrement nr_conns) afterwards.
        self._conn_lost_handled = False
        self._body_receiver = None  # Set per-request for disconnect signaling
        # HTTP/1 application calls whose response is complete but which are
        # still running, mapped to their body receivers. The connection
        # serves the next request meanwhile.
        self._finishing_calls = {}
        self._awaiting_request = False

        # Response buffering for write batching
        self._response_buffer = None

        # Backpressure control
        self._reading_paused = False
        self._max_buffer_size = 65536 * 4  # 256KB held before reading pauses

        # Keep-alive timer
        self._keepalive_handle = None

        # Callback parser state
        self._callback_parser = None
        self._request_ready = None  # Event signaling headers complete
        self._current_request = None  # Request built from parser state
        self._is_ssl = False

        # Write flow control
        self._flow_control = None

        # WebSocket protocol (set during upgrade, receives data via callbacks)
        self._websocket = None

    def connection_made(self, transport):
        """Called when a connection is established."""
        self.transport = transport
        self.worker.nr_conns += 1

        # Check if HTTP/2 was negotiated via ALPN
        ssl_object = transport.get_extra_info('ssl_object')
        if ssl_object and hasattr(ssl_object, 'selected_alpn_protocol'):
            alpn = ssl_object.selected_alpn_protocol()
            if alpn == 'h2':
                # HTTP/2 connection - uses StreamReader (complex framing)
                self.reader = asyncio.StreamReader()
                self._task = self.worker.loop.create_task(
                    self._handle_http2_connection(transport, ssl_object)
                )
                return

        peername = transport.get_extra_info('peername')
        if negotiation.prior_knowledge_allowed(self.cfg, peername):
            # Cleartext HTTP/2 with prior knowledge. Unlike the sync workers
            # we cannot read here, so commit to neither protocol yet: buffer
            # in data_received() until the preface either matches or cannot.
            self._is_ssl = False
            self.writer = transport
            self._flow_control = FlowControl(transport)
            transport.set_write_buffer_limits(high=HIGH_WATER_LIMIT)
            self._h2c_buffer = b""
            self._h2c_timer = self.worker.loop.call_later(
                negotiation.H2C_PREFACE_TIMEOUT, self._h2c_undecided_timeout
            )
            return

        # HTTP/1.x connection - always use callback parser
        self._is_ssl = ssl_object is not None
        self.writer = transport

        # Setup flow control
        self._flow_control = FlowControl(transport)
        transport.set_write_buffer_limits(high=HIGH_WATER_LIMIT)
        if getattr(self.cfg, 'protocol', 'http') == 'uwsgi':
            self._start_uwsgi()
        else:
            self._start_http1()

    def _start_uwsgi(self):
        """Commit to the uWSGI protocol on this connection.

        uWSGI framing is pull-parsed from a StreamReader that data_received()
        feeds, so create the reader here instead of the HTTP/1 callback parser;
        _handle_connection() dispatches to the uWSGI handler.
        """
        self.reader = asyncio.StreamReader()
        self._task = self.worker.loop.create_task(self._handle_connection())

    def _start_http1(self, buffered=b""):
        """Commit to HTTP/1.x and replay anything already read.

        Called straight from connection_made(), and again when h2c sniffing
        gives up on a connection that turned out to speak HTTP/1 after all.
        """
        self._request_ready = asyncio.Event()
        self._setup_callback_parser()
        peername = self.transport.get_extra_info('peername')
        # Decided once per connection: upgrade needs a parser that can hand
        # back the bytes pipelined behind the request, which gunicorn_h1c
        # gained in 0.6.9. The pip floor is not enforced at runtime, so an
        # older parser means no upgrade rather than silently dropped frames.
        self._h2c_upgrade_ok = (
            negotiation.upgrade_allowed(self.cfg, peername)
            and hasattr(self._callback_parser, 'remaining')
        )
        self._task = self.worker.loop.create_task(self._handle_connection())
        if buffered:
            self._feed_callback_parser(buffered)

    @classmethod
    def _check_h1c_protocol_available(cls):
        """Check if H1CProtocol is available (cached at class level)."""
        if cls._h1c_available is None:
            try:
                import gunicorn_h1c
                from gunicorn_h1c import H1CProtocol
                cls._h1c_available = True
                cls._h1c_protocol_class = H1CProtocol
                # Require >= 0.4.1 for limit enforcement
                cls._h1c_has_limits = hasattr(gunicorn_h1c, 'LimitRequestLine')
                # Store h1c exception classes for handling (>= 0.4.1)
                cls._h1c_limit_request_line = getattr(
                    gunicorn_h1c, 'LimitRequestLine', None
                )
                cls._h1c_limit_request_headers = getattr(
                    gunicorn_h1c, 'LimitRequestHeaders', None
                )
                # Check for InvalidChunkExtension (>= 0.6.3)
                cls._h1c_invalid_chunk_extension = getattr(
                    gunicorn_h1c, 'InvalidChunkExtension', None
                )
                cls._h1c_unsupported_transfer_coding = getattr(
                    gunicorn_h1c, 'UnsupportedTransferCoding', None
                )
                # Any other malformed request. gunicorn_h1c raises two
                # unrelated ParseError classes: the public one, base of
                # the errors above, and one from H1CProtocol itself (bare
                # LF, invalid request target, chunk size).
                protocol_module = getattr(gunicorn_h1c, '_protocol', None)
                cls._h1c_parse_errors = tuple(
                    c for c in (getattr(gunicorn_h1c, 'ParseError', None),
                                getattr(protocol_module, 'ParseError', None))
                    if isinstance(c, type) and issubclass(c, Exception))
            except ImportError:
                cls._h1c_available = False
                cls._h1c_has_limits = False
        return cls._h1c_available

    # Compatibility flags not supported by the fast parser
    _FAST_PARSER_INCOMPATIBLE_FLAGS = (
        'permit_obsolete_folding',
        'strip_header_spaces',
    )

    def _setup_callback_parser(self):
        """Create callback parser based on http_parser setting.

        Parser selection:
        - auto: Use H1CProtocol if available (>= 0.4.1) and no incompatible flags, else PythonProtocol
        - fast: Require H1CProtocol >= 0.4.1 (error if unavailable or incompatible flags)
        - python: Use PythonProtocol only
        """
        parser_setting = getattr(self.cfg, 'http_parser', 'auto')

        # Check for incompatible compatibility flags
        incompatible = []
        for flag in self._FAST_PARSER_INCOMPATIBLE_FLAGS:
            if getattr(self.cfg, flag, False):
                incompatible.append(flag)
        # PROXY protocol framing is implemented only in PythonProtocol; the C parser
        # has no proxy_protocol kwarg and would silently drop the framing.
        if getattr(self.cfg, 'proxy_protocol', 'off') != 'off':
            incompatible.append('proxy_protocol')

        if parser_setting == 'python':
            parser_class = PythonProtocol
        elif parser_setting == 'fast':
            if not self._check_h1c_protocol_available():
                raise RuntimeError("gunicorn_h1c required for http_parser='fast'")
            if not ASGIProtocol._h1c_has_limits:
                raise RuntimeError(
                    "gunicorn_h1c >= 0.4.1 required for http_parser='fast'. "
                    "Please upgrade: pip install --upgrade gunicorn_h1c"
                )
            if incompatible:
                raise RuntimeError(
                    "http_parser='fast' is incompatible with compatibility flags: %s. "
                    "Use http_parser='python' or disable these flags."
                    % ', '.join(incompatible)
                )
            parser_class = ASGIProtocol._h1c_protocol_class
        else:  # auto
            if (self._check_h1c_protocol_available() and
                    ASGIProtocol._h1c_has_limits and not incompatible):
                parser_class = ASGIProtocol._h1c_protocol_class
            else:
                parser_class = PythonProtocol

        # Handle limit_request_line=0 (unlimited per documentation)
        # PythonProtocol handles 0 correctly, but C parser needs a large value
        limit_request_line = self.cfg.limit_request_line
        if limit_request_line == 0 and parser_class != PythonProtocol:
            limit_request_line = 1024 * 1024  # 1MB for C parser

        # Create parser with callbacks and limit parameters (both parsers support them).
        # Only the Python parser implements PROXY protocol framing; pass the option there.
        parser_kwargs = {
            'on_headers_complete': self._on_headers_complete,
            'on_body': self._on_body,
            'on_message_complete': self._on_message_complete,
            'limit_request_line': limit_request_line,
            'limit_request_fields': self.cfg.limit_request_fields,
            'limit_request_field_size': self.cfg.limit_request_field_size,
            'permit_unconventional_http_method': self.cfg.permit_unconventional_http_method,
            'permit_unconventional_http_version': self.cfg.permit_unconventional_http_version,
        }
        if parser_class is PythonProtocol:
            # PROXY framing is only honored when the peer is in
            # ``proxy_allow_ips`` (the WSGI parser enforces the same gate at
            # gunicorn/http/message.py:proxy_protocol_access_check).  Untrusted
            # peers get proxy_protocol='off', so any framing they send is
            # interpreted as malformed HTTP and rejected with a 400.
            cfg_proxy = getattr(self.cfg, 'proxy_protocol', 'off')
            if cfg_proxy != 'off':
                peername = self.transport.get_extra_info('peername')
                normalized = _normalize_sockaddr(peername)
                trusted = _check_trusted_proxy(
                    normalized,
                    self.cfg.proxy_allow_ips,
                    self.cfg.proxy_allow_networks(),
                )
                parser_kwargs['proxy_protocol'] = cfg_proxy if trusted else 'off'
            else:
                parser_kwargs['proxy_protocol'] = 'off'
        self._callback_parser = parser_class(**parser_kwargs)

    def _on_headers_complete(self):
        """Callback: request headers are complete."""
        # Build request from parser state
        self._current_request = CallbackRequest.from_parser(
            self._callback_parser, is_ssl=self._is_ssl
        )
        request = self._current_request
        policy = _RequestHeaderPolicy(
            self.cfg, self.transport.get_extra_info('peername'),
            request.scheme, request.version,
        )
        if self._forwarded_trust is None:
            self._forwarded_trust = policy._peer_trusted_for_forwarded()
            self._secure_names = secure_scheme_names(self._forwarded_trust[0])
        policy.apply(request, self._forwarded_trust, self._secure_names)

        # Create body receiver for this request
        self._body_receiver = BodyReceiver(self._current_request, self)

        if self._h2c_upgrade_ok and request.may_upgrade():
            self._h2c_upgrade_settings = negotiation.upgrade_settings(
                self._current_request)
            if self._h2c_upgrade_settings is not None:
                # Hold the request back until the message is complete and the
                # bytes behind it have been recovered. Waking the connection
                # loop now would let it answer over HTTP/1 mid-upgrade.
                self._h2c_upgrade_body = bytearray()
                return False

        # Signal that request is ready for processing
        if self._request_ready:
            self._request_ready.set()

        # Never skip the body: a request is framed by its own Content-Length
        # or Transfer-Encoding whatever the method (RFC 9112 section 6.3).
        # Only a response to HEAD has no body.
        return False

    def _on_body(self, chunk):
        """Callback: received body data chunk."""
        if self._h2c_upgrade_body is not None:
            # RFC 7540 section 3.2 allows a payload on the upgrade request.
            # It becomes the body of stream 1, so it is kept here instead of
            # going to a receiver no ASGI app will ever read from.
            self._h2c_upgrade_body += chunk
            if len(self._h2c_upgrade_body) > negotiation.H2C_UPGRADE_BODY_LIMIT:
                # Held in memory until stream 1 exists; nothing needs more.
                self.log.debug("h2c upgrade body over %d bytes, closing",
                               negotiation.H2C_UPGRADE_BODY_LIMIT)
                self._close_transport()
            return
        if self._body_receiver:
            self._body_receiver.feed(chunk)

    def _on_message_complete(self):
        """Callback: request is fully received."""
        if self._body_receiver:
            self._body_receiver.set_complete()

    def _handle_h1c_exception(self, exc):
        """Handle gunicorn_h1c exceptions with appropriate HTTP status codes.

        Returns True if the exception was handled, False otherwise.
        """
        # pylint: disable=isinstance-second-argument-not-valid-type
        h1c_limit_line = ASGIProtocol._h1c_limit_request_line
        if h1c_limit_line is not None and isinstance(exc, h1c_limit_line):
            self._send_error_response(414, str(exc))  # URI Too Long
            self._close_transport()
            return True
        h1c_limit_headers = ASGIProtocol._h1c_limit_request_headers
        if h1c_limit_headers is not None and isinstance(exc, h1c_limit_headers):
            self._send_error_response(431, str(exc))  # Request Header Fields Too Large
            self._close_transport()
            return True
        h1c_chunk_ext = ASGIProtocol._h1c_invalid_chunk_extension
        if h1c_chunk_ext is not None and isinstance(exc, h1c_chunk_ext):
            self._send_error_response(400, str(exc))
            self._close_transport()
            return True
        h1c_unsupported_te = ASGIProtocol._h1c_unsupported_transfer_coding
        if h1c_unsupported_te is not None and isinstance(exc, h1c_unsupported_te):
            self._send_error_response(501, str(exc))  # RFC 9112 section 6.1
            self._close_transport()
            return True
        # Any other malformed request gets a 400, as with the Python parser
        # (RFC 9112 section 3, 5.1), instead of an unhandled exception that
        # dropped the connection without a response.
        if isinstance(exc, ASGIProtocol._h1c_parse_errors):
            self._send_error_response(400, str(exc))
            self._close_transport()
            return True
        return False

    def data_received(self, data):
        """Called when data is received on the connection."""
        if self._websocket:
            # WebSocket path - forward to WebSocket protocol
            self._websocket.feed_data(data)
            return
        if self._h2c_buffer is not None:
            self._h2c_feed(data)
            return
        if self.reader:
            # HTTP/2 path - use StreamReader
            self.reader.feed_data(data)
        elif self._callback_parser:
            # HTTP/1.x path - feed directly to callback parser
            if not self._feed_callback_parser(data):
                return
            # Backpressure: pause reading if buffer is too large
            if (not self._reading_paused and self._callback_parser is not None
                    and self._http1_buffered() > self._max_buffer_size):
                self._pause_reading()
            return

        # Backpressure: pause reading if buffer is too large
        if not self._reading_paused and self._is_buffer_full():
            self._pause_reading()

    def _h2c_feed(self, data):
        """Accumulate bytes until the connection preface resolves."""
        self._h2c_buffer += data
        state = negotiation.preface_match(self._h2c_buffer)
        if state is negotiation.PARTIAL:
            return
        buffered, self._h2c_buffer = self._h2c_buffer, None
        self._h2c_cancel_timer()
        if state is negotiation.MATCH:
            self._h2c_start(buffered)
            return
        if negotiation.mismatch_is_error(self.cfg):
            # A trusted peer on a prior-knowledge-only port must speak
            # HTTP/2. Anything else is refused rather than downgraded.
            self._send_error_response(400, "Invalid HTTP/2 connection preface")
            self._close_transport()
            return
        # Upgrade is enabled too, so this may be the HTTP/1 request that
        # carries it; carry on with the bytes preserved.
        self._start_http1(buffered)

    def _h2c_start(self, buffered):
        """Commit to HTTP/2 and replay the bytes read while undecided."""
        self.reader = asyncio.StreamReader()
        self._task = self.worker.loop.create_task(
            # No ssl_object: this is cleartext. The handler does not use it.
            self._handle_http2_connection(self.transport, None)
        )
        self.reader.feed_data(buffered)

    def _h2c_undecided_timeout(self):
        """Nothing conclusive arrived in time.

        With prior knowledge alone the peer is expected to speak HTTP/2, so
        stalling mid-preface is refused rather than downgraded. Where an
        upgrade is also on offer, a quiet client is just a quiet client and
        the ordinary HTTP/1 timeouts apply.
        """
        self._h2c_timer = None
        if self._h2c_buffer is None:
            return
        buffered, self._h2c_buffer = self._h2c_buffer, None
        if not negotiation.mismatch_is_error(self.cfg):
            self._start_http1(buffered)
            return
        self._send_error_response(400, "Invalid HTTP/2 connection preface")
        self._close_transport()

    def _h2c_cancel_timer(self):
        if self._h2c_timer is not None:
            self._h2c_timer.cancel()
            self._h2c_timer = None

    def _feed_callback_parser(self, data):  # pylint: disable=too-many-return-statements
        """Feed data to callback parser, handling parse errors.

        Returns True if parsing should continue, False if connection was closed.
        """
        try:
            self._callback_parser.feed(data)
            if self._h2c_upgrade_settings is not None:
                return self._h2c_arm_upgrade()
            return True
        except LimitRequestLine as e:
            self._send_error_response(414, str(e))  # URI Too Long
            self._close_transport()
            return False
        except LimitRequestHeaders as e:
            self._send_error_response(431, str(e))  # Request Header Fields Too Large
            self._close_transport()
            return False
        except UnsupportedTransferCoding as e:
            # RFC 9112 section 6.1: a transfer coding the server does not
            # understand SHOULD get 501, as the WSGI workers answer.
            self._send_error_response(501, str(e))
            self._close_transport()
            return False
        except (InvalidChunkExtension, ParseError, HTTPParseException) as e:
            self._send_error_response(400, str(e))
            self._close_transport()
            return False
        except Exception as e:
            # Handle gunicorn_h1c exceptions (different class hierarchy)
            if self._handle_h1c_exception(e):
                return False
            raise

    def _h2c_arm_upgrade(self):
        """Hand the connection over to HTTP/2 once the request is complete.

        Runs synchronously, inside data_received(), because that is what stops
        the connection preface and the frames behind it from reaching the
        HTTP/1 parser. Installing the reader here also gives later
        data_received() calls somewhere to land while the connection loop is
        still waking up.

        Returns True to keep feeding HTTP/1, as _feed_callback_parser does.
        """
        parser = self._callback_parser
        if not parser.is_complete:
            return True
        if parser.remaining_truncated:
            # The tail is capped, so frames the client already sent are gone
            # and the HTTP/2 stream would start corrupt. Nobody legitimately
            # pipelines that much behind an upgrade request.
            self._h2c_upgrade_settings = None
            self._h2c_upgrade_body = None
            self._send_error_response(400, "Upgrade request tail too large")
            self._close_transport()
            # Let the connection loop out of its wait instead of leaving it
            # for the disconnect grace period to cancel.
            self._request_ready.set()
            return False
        pending = parser.remaining()
        self._callback_parser = None
        self.reader = asyncio.StreamReader()
        if pending:
            self.reader.feed_data(pending)
        self._request_ready.set()
        return False

    def _http1_buffered(self):
        """Bytes held for HTTP/1 that the app has not taken yet.

        The body chunks waiting in the receiver, plus what the pure-Python
        parser holds after a completed message (a pipelined request); the
        C parser caps that tail itself.
        """
        receiver = self._body_receiver
        held = receiver.buffered if receiver is not None else 0
        parser = self._callback_parser
        if parser.__class__ is PythonProtocol and parser.is_complete:
            tail = getattr(parser, '_buffer', None)
            if tail is not None:
                held += len(tail)
        return held

    def _is_buffer_full(self):
        """Check if internal buffers are full."""
        if self.reader and hasattr(self.reader, '_buffer'):
            return len(self.reader._buffer) > self._max_buffer_size
        if self.reader is None and self._callback_parser is not None:
            return self._http1_buffered() > self._max_buffer_size
        return False

    def _pause_reading(self):
        """Pause reading from transport due to backpressure."""
        if not self._reading_paused and self.transport:
            self._reading_paused = True
            try:
                self.transport.pause_reading()
            except (AttributeError, RuntimeError):
                pass

    def _resume_reading(self):
        """Resume reading from transport."""
        if self._reading_paused and self.transport:
            self._reading_paused = False
            try:
                self.transport.resume_reading()
            except (AttributeError, RuntimeError):
                pass

    def _arm_keepalive_timer(self):
        """Arm keepalive timeout timer after response completion."""
        if self._keepalive_handle:
            self._keepalive_handle.cancel()
        keepalive_timeout = self._keepalive
        if keepalive_timeout > 0:
            self._keepalive_handle = self.worker.loop.call_later(
                keepalive_timeout, self._keepalive_timeout
            )

    def _cancel_keepalive_timer(self):
        """Cancel keepalive timer when new request arrives."""
        if self._keepalive_handle:
            self._keepalive_handle.cancel()
            self._keepalive_handle = None

    def _keepalive_timeout(self):
        """Called when keepalive timeout expires."""
        self._close_transport()
        # Wake _handle_connection up so it sees _closed and exits instead of
        # waiting for the cancellation scheduled by connection_lost.
        self._request_ready.set()

    def connection_lost(self, exc):
        """Called when the connection is lost or closed.

        Instead of immediately cancelling the task, we signal a disconnect
        event and send an http.disconnect message to the receive queue.
        This allows the ASGI app to clean up resources (like database
        connections) gracefully before the task is cancelled.

        See: https://github.com/benoitc/gunicorn/issues/3484
        """
        # Guard against multiple calls (idempotent). Use a dedicated flag rather
        # than ``_closed``: a server-initiated close sets ``_closed`` in
        # _close_transport() before the transport reports the loss, and the
        # cleanup below (notably decrementing nr_conns) must still run.
        if self._conn_lost_handled:
            return

        self._conn_lost_handled = True
        self._closed = True
        # Drop any half-read preface with the connection it belonged to.
        self._h2c_buffer = None
        self._h2c_cancel_timer()
        self.worker.nr_conns -= 1

        # Cancel keepalive timer
        self._cancel_keepalive_timer()

        if self.reader:
            self.reader.feed_eof()

        # Signal EOF to WebSocket if active
        if self._websocket:
            self._websocket.feed_eof()

        # Signal disconnect to the app via the body receiver
        if self._body_receiver is not None:
            self._body_receiver.signal_disconnect()
        for receiver in self._finishing_calls.values():
            if receiver is not None:
                receiver.signal_disconnect()

        # HTTP/2: every stream task learns the peer is gone, and a task
        # blocked in writer.drain() is released with an error.
        h2_conn = getattr(self, '_h2_conn', None)
        if h2_conn is not None:
            h2_conn.abort_streams_nowait()
        if self._h2_writer_protocol is not None:
            try:
                self._h2_writer_protocol.connection_lost(exc)
            except Exception:
                pass

        # Schedule task cancellation after grace period if task doesn't complete
        if self._task and not self._task.done():
            grace_period = getattr(self.cfg, 'asgi_disconnect_grace_period', 3)
            if grace_period > 0:
                self.worker.loop.call_later(
                    grace_period,
                    self._cancel_task_if_pending
                )
            else:
                # Grace period of 0 means cancel immediately
                self._task.cancel()

    def _cancel_task_if_pending(self):
        """Cancel the task if it's still pending after grace period."""
        if self._task and not self._task.done():
            self._task.cancel()

    def pause_writing(self):
        """Called by transport when write buffer exceeds high water mark."""
        if self._flow_control:
            self._flow_control.pause_writing()
        elif self._h2_writer_protocol is not None:
            self._h2_writer_protocol.pause_writing()
            # The peer is not reading. Stop reading from it too: its PING
            # and SETTINGS frames are answered without waiting for the
            # transport, so parsing more of them would grow a write buffer
            # that is already over its limit.
            self._write_paused = True
            self._pause_reading()

    def resume_writing(self):
        """Called by transport when write buffer drains below low water mark."""
        if self._flow_control:
            self._flow_control.resume_writing()
        elif self._h2_writer_protocol is not None:
            self._h2_writer_protocol.resume_writing()
            self._write_paused = False
            self._maybe_resume_reading()

    def _safe_write(self, data):
        """Write data to transport, handling connection errors gracefully.

        Catches exceptions that occur when the client has disconnected:
        - OSError with errno EPIPE, ECONNRESET, ENOTCONN
        - RuntimeError when transport is closing/closed
        - AttributeError when transport is None

        These are silently ignored since the client is already gone.
        """
        try:
            self.transport.write(data)
        except OSError as e:
            if e.errno not in (errno.EPIPE, errno.ECONNRESET, errno.ENOTCONN):
                self.log.exception("Socket error writing response.")
        except (RuntimeError, AttributeError):
            # Transport is closing/closed or None
            pass

    async def _handle_connection(self):
        """Main request handling loop using callback-based parser.

        Uses synchronous parsing in data_received(), avoiding the async
        overhead of pull-based parsing. The parser fires callbacks when
        headers and body data are available, and this loop waits on
        events rather than actively parsing.
        """
        cancelled = False
        try:
            peername = self.transport.get_extra_info('peername')
            sockname = self.transport.get_extra_info('sockname')

            # Check protocol type - use separate path for uWSGI
            protocol_type = getattr(self.cfg, 'protocol', 'http')
            if protocol_type == 'uwsgi':
                await self._handle_connection_uwsgi(peername, sockname)
                return

            effective_peer = None
            while not self._closed:
                self.req_count += 1

                # Wait for headers to be parsed (callback sets the event and _current_request)
                # Don't clear if request already arrived (data_received ran before us)
                if not self._request_ready.is_set():
                    # Arm the keepalive timer while we wait for the next
                    # request to become available. While an application
                    # call is still running the connection is not idle;
                    # _finishing_call_done arms it once the last one ends.
                    if self.req_count > 1 and not self._finishing_calls:
                        self._arm_keepalive_timer()
                    self._awaiting_request = True
                    try:
                        await self._request_ready.wait()
                    except asyncio.CancelledError:
                        cancelled = True
                        break
                    finally:
                        self._awaiting_request = False
                self._cancel_keepalive_timer()

                if self._closed or self._current_request is None:
                    break

                request = self._current_request

                # If PROXY protocol provided a real client address, use it.
                # The PROXY header only opens a connection, so the answer
                # holds for every request on it.
                if effective_peer is None:
                    effective_peer = self._effective_peername(peername)

                # Check for cleartext HTTP/2 upgrade
                if self._h2c_upgrade_settings is not None:
                    await self._handle_h2c_upgrade(request)
                    break  # HTTP/2 takes over the connection

                # Check for WebSocket upgrade
                if request.may_upgrade() and self._is_websocket_upgrade(request):
                    await self._handle_websocket(request, sockname, effective_peer)
                    break  # WebSocket takes over the connection

                # Bound the application calls left running on this
                # connection before starting another one.
                while len(self._finishing_calls) >= _MAX_FINISHING_APP_CALLS:
                    await asyncio.wait(list(self._finishing_calls),
                                       return_when=asyncio.FIRST_COMPLETED)

                # Handle HTTP request
                keepalive = await self._serve_http_request(
                    request, sockname, effective_peer
                )

                # Increment worker request count
                self.worker.nr += 1

                # Check max_requests
                if self.worker.nr >= self.worker.max_requests:
                    self.log.info("Autorestarting worker after current request.")
                    self.worker.alive = False
                    keepalive = False

                if not keepalive or not self.worker.alive:
                    break

                # Check connection limits for keepalive
                if not self._keepalive:
                    break

                # Refuse keepalive if the previous request body was not fully
                # framed: residual bytes in the transport stream would be parsed
                # as the start of the next request (smuggling).  Only _complete
                # signals a cleanly framed message; _closed is set on transport
                # disconnect *and* on receive timeout, neither of which means
                # the body finished framing.
                receiver = self._body_receiver
                if receiver is not None and not receiver._complete:
                    break

                # Resume reading if paused during body consumption
                self._resume_reading()

                # A pipelined next request already sits in the parser buffer
                # (feed() leaves the tail after a completed message); reset()
                # would clear it, so recover it and re-feed it below.
                pipelined = b""
                if self._callback_parser:
                    if getattr(self._callback_parser, "remaining_truncated", False):
                        # A capped tail cannot be safely replayed.
                        break
                    pipelined = self._callback_parser.remaining()
                    self._callback_parser.reset()

                # Clear request state for next iteration
                self._current_request = None
                self._body_receiver = None
                self._request_ready.clear()

                # Re-feed the pipelined request so it is served rather than
                # dropped; _feed_callback_parser fires _on_headers_complete
                # synchronously and closes the connection (returns False) on a
                # malformed tail.
                if pipelined:
                    if not self._feed_callback_parser(pipelined):
                        break

        except asyncio.CancelledError:
            cancelled = True
        except Exception as e:
            self.log.exception("Error handling connection: %s", e)
        finally:
            await self._finish_app_calls(cancelled)
            self._close_transport()

    async def _serve_http_request(self, request, sockname, peername):
        """Run one HTTP/1 request; return once its response is complete.

        The application may keep running after its last response message
        (Starlette's background tasks run there). When the connection can
        be kept alive and the app has taken the whole request body, the
        call is left to finish in its own task and the next request is
        served meanwhile. Otherwise this waits for the call to return, so
        the connection is closed only after it. A post_request hook runs
        after the call and may still decide to close the connection, so
        with one set this also waits.

        Returns the keepalive decision, as _handle_http_request does.
        """
        loop = self.worker.loop
        receiver = self._body_receiver
        complete = loop.create_future()
        task = loop.create_task(
            self._handle_http_request(request, sockname, peername, complete))
        task.add_done_callback(lambda t: _relay_result(t, complete))
        try:
            keepalive = await complete
        except asyncio.CancelledError:
            task.cancel()
            raise
        if task.done():
            # The final answer, which a post_request hook may have changed.
            return task.result()
        # Body bytes the app has not taken would no longer count towards the
        # read backpressure once the next request is read, so they also wait.
        if (keepalive and self._post_request is None
                and (receiver is None
                     or (receiver._complete and not receiver.buffered))):
            self._finishing_calls[task] = receiver
            task.add_done_callback(self._finishing_call_done)
            return keepalive
        # This connection serves nothing more: wait for the call as before.
        # Awaiting the task directly passes a cancellation on to it.
        return await task

    def _finishing_call_done(self, task):
        """An application call left running after its response returned."""
        self._finishing_calls.pop(task, None)
        if (not self._finishing_calls and self._awaiting_request
                and not self._closed):
            # The connection is idle only now.
            self._arm_keepalive_timer()

    async def _finish_app_calls(self, cancel):
        """Settle the application calls still running when the loop ends.

        They run to completion while the connection stays open. Once the
        peer is gone, connection_lost() gives them
        asgi_disconnect_grace_period, then cancels this task, which
        cancels them.
        """
        tasks = list(self._finishing_calls)
        if not tasks:
            return
        if not cancel:
            try:
                await asyncio.wait(tasks)
                return
            except asyncio.CancelledError:
                pass
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _handle_connection_uwsgi(self, peername, sockname):
        """Handle uWSGI protocol connections (legacy path)."""
        unreader = AsyncUnreader(self.reader)

        while not self._closed:
            self.req_count += 1

            try:
                request = await AsyncUWSGIRequest.parse(
                    self.cfg,
                    unreader,
                    peername,
                    self.req_count
                )
            except NoMoreData:
                break
            except UWSGIParseException as e:
                self.log.debug("uWSGI parse error: %s", e)
                break

            # Check for WebSocket upgrade
            if self._is_websocket_upgrade(request):
                await self._handle_websocket(request, sockname, peername)
                break

            # Build the ASGI body receiver and feed it the uWSGI body. The
            # HTTP/1 path fills this from parser callbacks; the uWSGI body is
            # pull-read here (nginx buffers the request upstream).
            self._body_receiver = BodyReceiver(request, self)
            if request.content_length:
                # Read the body as the app asks for it rather than holding
                # all of it in memory before the app starts.
                self._body_receiver._source = request.read_body
            else:
                self._body_receiver.set_complete()

            # Handle HTTP request
            keepalive = await self._handle_http_request(
                request, sockname, peername
            )
            self._body_receiver = None

            # Discard what the app did not read, so the next request starts
            # where it should.
            if keepalive and request.content_length:
                await request.drain_body()

            # Increment worker request count
            self.worker.nr += 1

            # Check max_requests
            if self.worker.nr >= self.worker.max_requests:
                self.log.info("Autorestarting worker after current request.")
                self.worker.alive = False
                keepalive = False

            if not keepalive or not self.worker.alive:
                break

            if not self._keepalive:
                break

            await request.drain_body()

    async def _handle_h2c_upgrade(self, request):
        """Serve an Upgrade: h2c request over HTTP/2.

        The 101 goes out here rather than in _h2c_arm_upgrade so that nothing
        can write between it and the SETTINGS frame the HTTP/2 handler sends.
        """
        settings = self._h2c_upgrade_settings
        body = bytes(self._h2c_upgrade_body or b"")
        self._h2c_upgrade_settings = None
        self._h2c_upgrade_body = None
        self.transport.write(negotiation.UPGRADE_101)
        await self._handle_http2_connection(
            self.transport, None, upgrade=(settings, request, body)
        )

    def _is_websocket_upgrade(self, request):
        """Check if request is a WebSocket upgrade.

        Per RFC 6455 Section 4.1, the opening handshake requires:
        - HTTP method MUST be GET
        - Upgrade header MUST be "websocket" (case-insensitive)
        - Connection header MUST contain "Upgrade"
        """
        # RFC 6455: The method of the request MUST be GET
        if request.method != "GET":
            return False
        may_upgrade = getattr(request, "may_upgrade", None)
        if may_upgrade is not None and not may_upgrade():
            return False

        upgrade = None
        connection = None
        for name, value in request.headers:
            if name == "UPGRADE":
                upgrade = value.lower()
            elif name == "CONNECTION":
                connection = value.lower()
        return upgrade == "websocket" and connection and "upgrade" in connection

    async def _handle_websocket(self, request, sockname, peername):
        """Handle WebSocket upgrade request."""
        from gunicorn.asgi.websocket import WebSocketProtocol

        # Stop callback parser - WebSocket uses its own data handling
        self._callback_parser = None

        # RFC 6455 section 4.2.1: version 13 and a key that is 16 bytes
        # once base64-decoded. A version we do not speak gets 426 with the
        # version we do (section 4.2.2); a bad key gets 400.
        version = key = None
        for name, value in request.headers:
            if name == "SEC-WEBSOCKET-VERSION":
                version = value.strip()
            elif name == "SEC-WEBSOCKET-KEY":
                key = value.strip()
        if version != "13":
            self._send_error_response(426, "Upgrade Required",
                                      (("Sec-WebSocket-Version", "13"),))
            self._close_transport()
            return
        if not _valid_websocket_key(key):
            self._send_error_response(400, "Bad Request")
            self._close_transport()
            return

        scope = self._build_websocket_scope(request, sockname, peername)
        ws_protocol = WebSocketProtocol(
            self.transport, scope, self.app, self.log,
            max_message_size=self.cfg.websocket_max_message_size,
            drain=self._flow_control.drain if self._flow_control else None,
        )

        # Store reference so data_received() forwards to WebSocket
        self._websocket = ws_protocol

        await ws_protocol.run()

    async def _handle_http_request(self, request, sockname, peername, complete=None):
        """Handle a single HTTP request.

        Returns whether the connection may be kept alive. When ``complete``
        is a future, it gets that answer as soon as the response is
        complete, while the application may still be running.
        """
        scope = self._build_http_scope(request, sockname, peername)
        response_started = False
        response_complete = False
        exc_to_raise = None
        use_chunked = False
        omits_body = False
        omits_body_warned = False
        response_requires_close = False
        close_announced = None
        response_length = None
        uses_uwsgi = self._uses_uwsgi

        # Reset response buffer for write batching
        self._response_buffer = None

        # Response tracking for access logging
        response_status = 500
        response_headers = []
        response_sent = 0

        # Use body receiver created in _on_headers_complete (receives data via callbacks)
        body_receiver = self._body_receiver

        async def send(message):
            nonlocal response_started, response_complete, exc_to_raise
            nonlocal response_status, response_headers, response_sent, use_chunked, omits_body
            nonlocal omits_body_warned, response_requires_close, response_length
            nonlocal close_announced

            # If client disconnected, silently ignore send attempts
            # This allows apps to finish cleanup without errors
            if self._closed:
                return

            msg_type = message["type"]

            if msg_type == "http.response.informational":
                if response_started:
                    # RFC 9110 section 15.2: a 1xx comes before the final
                    # response, written later it would corrupt this response
                    # or the next one on the connection.
                    exc_to_raise = RuntimeError(
                        "Informational response after response start")
                    return
                # Handle informational responses (1xx) like 103 Early Hints
                info_status = message.get("status")
                info_headers = message.get("headers", [])
                _validate_response_headers(info_headers)
                self._send_informational(info_status, info_headers, request)
                if info_status == 100 and body_receiver is not None:
                    body_receiver.expect_continue = False
                return

            if msg_type == "http.response.start":
                if response_started:
                    exc_to_raise = RuntimeError("Response already started")
                    return
                response_headers = message.get("headers", [])
                # Validated before the response counts as started, so an
                # invalid header still turns into a 500.
                has_content_length, content_length_value, has_transfer_encoding = \
                    _scan_response_headers(response_headers)
                response_started = True
                response_status = message["status"]
                if body_receiver is not None:
                    # A final status before the body was asked for: the
                    # client gets no 100 (RFC 9110 section 10.1.1).
                    body_receiver.expect_continue = False
                if has_transfer_encoding:
                    use_chunked = True  # Framework already set chunked encoding

                # Transfer-Encoding is HTTP hop-by-hop framing.  A uWSGI
                # upstream response carries raw body bytes, so forwarding or
                # applying it would make nginx expose the chunk markers as
                # part of the application response.
                if uses_uwsgi and has_transfer_encoding:
                    response_headers = [
                        (name, value) for name, value in response_headers
                        if name.lower() not in (
                            b"transfer-encoding", "transfer-encoding"
                        )
                    ]
                    has_transfer_encoding = False
                    use_chunked = False

                # No-body responses (HEAD/1xx/204/304) must not carry a body.
                # Always drop Transfer-Encoding (no chunked terminator without
                # a body); Content-Length is dropped only for statuses that
                # forbid it per RFC 9110 §6.4.2 (1xx, 204).  HEAD and 304 keep
                # an app-supplied Content-Length.
                omits_body = self._response_omits_body(request.method, response_status)
                if omits_body and (has_content_length or has_transfer_encoding):
                    response_headers = self._strip_body_framing_headers(
                        response_headers, response_status
                    )
                    if self._response_forbids_content_length(response_status):
                        has_content_length = False
                    has_transfer_encoding = False
                    use_chunked = False

                # Use chunked encoding for HTTP/1.1 streaming responses without Content-Length.
                # Skip when the response cannot carry a body or when Transfer-Encoding was
                # already set by the framework.
                needs_chunked = (
                    not has_content_length
                    and not has_transfer_encoding
                    and request.version >= (1, 1)
                    and not omits_body
                    and not uses_uwsgi
                )
                if needs_chunked:
                    use_chunked = True
                    response_headers = list(response_headers) + [(b"transfer-encoding", b"chunked")]

                # Like the WSGI Response, never write more body bytes than the
                # app's Content-Length declares: the excess would be read as
                # the start of the next response on a reused connection.
                if has_content_length and not use_chunked and not omits_body:
                    try:
                        response_length = int(content_length_value)
                    except (TypeError, ValueError):
                        response_length = None

                # Without Content-Length, EOF delimits a uWSGI response body.
                # Do not reuse the upstream connection for another request.
                response_requires_close = (
                    uses_uwsgi and not has_content_length and not omits_body
                )

                close_announced = self._will_close(request, response_requires_close)
                self._send_response_start(
                    response_status, response_headers, request,
                    close=close_announced,
                )

            elif msg_type == "http.response.body":
                if not response_started:
                    exc_to_raise = RuntimeError("Response not started")
                    return
                if response_complete:
                    exc_to_raise = RuntimeError("Response already complete")
                    return

                body = message.get("body", b"")
                more_body = message.get("more_body", False)

                # RFC 9110: HEAD/1xx/204/304 responses must not carry a body,
                # even if the framework emits one.  Drop body bytes;
                # use_chunked has already been forced False above so no
                # terminator will be written either.  Warn once per request
                # so framework bugs surface in logs without spamming on
                # multi-chunk streams.
                if omits_body:
                    if body and not omits_body_warned:
                        self.log.warning(
                            "ASGI app sent body bytes on a no-body response "
                            "(method=%s status=%s); dropping per RFC 9110.",
                            request.method, response_status,
                        )
                        omits_body_warned = True
                    body = b""

                if body.__class__ is not bytes and body:
                    # A bytearray or memoryview the app may reuse once send()
                    # returns: the transport may hold on to what it is given.
                    body = bytes(body)
                size = len(body)
                if response_length is not None and size > response_length - response_sent:
                    size = max(response_length - response_sent, 0)
                    body = body[:size]

                if size:
                    # The last chunk carries the chunked terminator.
                    self._send_body(body, use_chunked, not more_body, size)
                    response_sent += size
                    # Apply write backpressure for streaming responses. The
                    # writable event is set whenever writing is not paused,
                    # so only a paused transport needs the await.
                    flow_control = self._flow_control
                    if flow_control is not None and flow_control.write_paused:
                        await flow_control.drain()

                if not more_body:
                    if use_chunked and size:
                        pass  # _send_body() wrote the terminator
                    elif use_chunked:
                        # Send terminal chunk, combined with any buffered headers
                        if self._response_buffer:
                            self._safe_write(self._response_buffer + b"0\r\n\r\n")
                            self._response_buffer = None
                        else:
                            self._safe_write(b"0\r\n\r\n")
                    elif self._response_buffer:
                        # Non-chunked empty response - flush headers
                        self._safe_write(self._response_buffer)
                        self._response_buffer = None
                    response_complete = True
                    if (complete is not None and exc_to_raise is None
                            and not complete.done()):
                        complete.set_result(keepalive_after_response())

        def keepalive_after_response():
            # A body shorter than the declared Content-Length leaves the
            # client waiting for bytes that never come; close instead of
            # keeping alive.
            if response_length is not None and response_sent < response_length:
                return False

            # What decided close_announced cannot have changed, except the
            # worker state and, when something read (and so could have
            # edited) the str headers, the request's own fields.
            if (close_announced is None or not isinstance(request, CallbackRequest)
                    or request._headers is not None):
                return not self._will_close(request, response_requires_close)
            worker = self.worker
            return not (close_announced or not worker.alive
                        or worker.nr + 1 >= worker.max_requests)

        # Only build environ for logging if access logging is enabled
        access_log_enabled = self.log.access_log_enabled

        try:
            # Only the access log uses the request time.
            request_start = time.monotonic() if access_log_enabled else 0.0
            if self._pre_request is not None:
                self._pre_request(self.worker, request)

            await self.app(scope, body_receiver.receive, send)

            if exc_to_raise is not None:
                raise exc_to_raise

            # Ensure response was sent
            if not response_started:
                self._send_error_response(500, "Internal Server Error")
                response_status = 500
            elif not response_complete:
                # The app returned in the middle of its response. The client
                # cannot tell where it ends, and on a kept-alive connection
                # the next response would be read as the rest of this one
                # (or, with the headers still buffered, as the response to
                # this request). Close the connection instead.
                if not self._closed:
                    self.log.error(
                        "ASGI application returned without completing "
                        "the response; closing the connection")
                return False

        except asyncio.CancelledError:
            # Client disconnected - don't log as error, this is normal
            self.log.debug("Request cancelled (client disconnected)")
            return False
        except Exception:
            # If response was already completely sent, this is likely a
            # disconnect-related exception (e.g. Django's RequestAborted)
            if response_complete:
                self.log.debug("Exception after response complete (client disconnected)")
            else:
                self.log.exception("Error in ASGI application")
                if not response_started:
                    self._send_error_response(500, "Internal Server Error")
                    response_status = 500
            return False
        finally:
            # NOTE: do NOT clear self._body_receiver here.  _handle_connection
            # reads it after this method returns to enforce the keepalive
            # smuggling guard (refuse keepalive when the body was not framed
            # complete).  The connection loop clears the reference itself
            # after the gate has run.
            try:
                # Only build log data if access logging is enabled
                if access_log_enabled:
                    request_time = _RequestTime(time.monotonic() - request_start)
                    environ = self._build_environ(request, sockname, peername)
                    resp = ASGIResponseInfo(response_status, response_headers, response_sent)
                    self.log.access(resp, request, environ, request_time)
                else:
                    environ = None
                    resp = None
                if self._post_request is not None:
                    self._post_request(self.worker, request, environ, resp)
            except Exception:
                self.log.exception("Exception in post_request hook")

        return keepalive_after_response()

    def _will_close(self, request, response_requires_close):
        """Return True when the connection is closed after this response.

        Single source of truth for the keepalive decision: ``send`` consults it
        to emit ``Connection: close`` and ``_handle_http_request`` returns its
        inverse, so the framing announced matches the framing used. Covers every
        close reason knowable when the response headers are written.
        """
        if response_requires_close:
            return True

        if request.should_close():
            return True

        if not (self.worker.alive and self._keepalive):
            return True

        # This response trips max_requests recycling; the loop closes the
        # connection right after it (nr is incremented once this request
        # returns). max_requests is sys.maxsize when disabled, so this is inert
        # unless the limit is set.
        if self.worker.nr + 1 >= self.worker.max_requests:
            return True

        return False

    def _build_http_scope(self, request, sockname, peername):
        """Build ASGI HTTP scope from parsed request."""
        # Use pre-computed bytes headers if available (fast path)
        # Fall back to conversion for HTTP/2 requests
        headers_bytes = getattr(request, 'headers_bytes', None)
        if isinstance(headers_bytes, list):
            headers = list(headers_bytes)  # Copy to avoid mutation
        else:
            headers = []
            for name, value in request.headers:
                headers.append((name.lower().encode("latin-1"), value.encode("latin-1")))

        # The same address objects come with every request on a connection;
        # the tuples built from them are immutable, so they are reused.
        addresses = self._scope_addresses
        if (addresses is None or addresses[0] is not sockname
                or addresses[1] is not peername):
            addresses = self._scope_addresses = (
                sockname, peername,
                _normalize_sockaddr(sockname), _normalize_sockaddr(peername))
        server = addresses[2]
        client = addresses[3]

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": f"{request.version[0]}.{request.version[1]}",
            "method": request.method,
            "scheme": request.scheme,
            "path": request.path,
            "raw_path": request.raw_path if request.raw_path else b"",
            "query_string": request.query.encode("latin-1") if request.query else b"",
            "root_path": self._root_path,
            "headers": headers,
            "server": server,
            "client": client,
        }

        # Each request gets a shallow copy of the lifespan state (ASGI lifespan
        # spec), so one request's changes never reach another.
        if hasattr(self.worker, 'state'):
            scope["state"] = self.worker.state.copy()

        # Add HTTP/2 priority extension if available
        if hasattr(request, 'priority_weight'):
            scope["extensions"] = {
                "http.response.priority": {
                    "weight": request.priority_weight,
                    "depends_on": request.priority_depends_on,
                }
            }

        return scope

    def _build_environ(self, request, sockname, peername):
        """Build minimal WSGI-like environ dict for access logging."""
        environ = {
            "REQUEST_METHOD": request.method,
            "RAW_URI": request.uri,
            "PATH_INFO": request.path,
            "QUERY_STRING": request.query or "",
            "SERVER_PROTOCOL": f"HTTP/{request.version[0]}.{request.version[1]}",
            "REMOTE_ADDR": peername[0] if peername else "-",
        }

        # Add HTTP headers as environ vars
        for name, value in request.headers:
            key = "HTTP_" + name.replace("-", "_")
            environ[key] = value

        return environ

    def _build_websocket_scope(self, request, sockname, peername):
        """Build ASGI WebSocket scope from parsed request."""
        # Build headers list as bytes tuples
        headers = []
        for name, value in request.headers:
            headers.append((name.lower().encode("latin-1"), value.encode("latin-1")))

        # Extract subprotocols from Sec-WebSocket-Protocol header
        subprotocols = []
        for name, value in request.headers:
            if name == "SEC-WEBSOCKET-PROTOCOL":
                subprotocols = [s.strip() for s in value.split(",")]
                break

        server = _normalize_sockaddr(sockname)
        client = _normalize_sockaddr(peername)

        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": f"{request.version[0]}.{request.version[1]}",
            "scheme": "wss" if request.scheme == "https" else "ws",
            "path": request.path,
            "raw_path": request.raw_path if request.raw_path else b"",
            "query_string": request.query.encode("latin-1") if request.query else b"",
            "root_path": self._root_path,
            "headers": headers,
            "server": server,
            "client": client,
            "subprotocols": subprotocols,
        }

        # Each request gets a shallow copy of the lifespan state (ASGI lifespan
        # spec), so one request's changes never reach another.
        if hasattr(self.worker, 'state'):
            scope["state"] = self.worker.state.copy()

        return scope

    def _send_informational(self, status, headers, request):
        """Send an informational response (1xx) such as 103 Early Hints.

        Args:
            status: HTTP status code (100-199)
            headers: List of (name, value) header tuples
            request: The parsed request object

        Note: Informational responses are only sent for HTTP/1.1 or later.
        HTTP/1.0 clients do not support 1xx responses.
        """
        # Don't send informational responses to HTTP/1.0 clients
        if request.version < (1, 1):
            return

        reason = self._get_reason_phrase(status)
        response = f"HTTP/{request.version[0]}.{request.version[1]} {status} {reason}\r\n"

        for name, value in headers:
            if isinstance(name, bytes):
                name = name.decode("latin-1")
            if isinstance(value, bytes):
                value = value.decode("latin-1")
            response += f"{name}: {value}\r\n"

        response += "\r\n"
        self._safe_write(response.encode("latin-1"))

    def _send_response_start(self, status, headers, request, close=False):
        """Send HTTP response status and headers.

        Uses cached status lines and headers for common cases to avoid
        repeated string formatting and encoding.

        ``close`` announces that the connection ends after this response, as
        RFC 9112 requires of a server that will not reuse it.
        """
        # Get cached status line bytes
        status_line = _get_cached_status_line(request.version, status)

        # Build headers as bytes directly
        parts = [status_line]

        has_date = False
        has_server = False
        has_connection = False

        for name, value in headers:
            if isinstance(name, bytes):
                name_lower = name.lower()
            else:
                name = name.encode("latin-1")
                name_lower = name.lower()
            if not isinstance(value, bytes):
                value = value.encode("latin-1")
            parts += (name, b": ", value, b"\r\n")

            # Track if Date/Server/Connection headers are present
            if name_lower == b"date":
                has_date = True
            elif name_lower == b"server":
                has_server = True
            elif name_lower == b"connection":
                has_connection = True

        # Add default headers if not present
        if not has_server:
            parts.append(_CACHED_SERVER_HEADER)
        if not has_date:
            parts.append(_get_cached_date_header())
        if close and not has_connection:
            parts.append(b"Connection: close\r\n")

        parts.append(b"\r\n")

        # Buffer headers for batching with first body chunk
        self._response_buffer = b"".join(parts)

    def _effective_peername(self, peername):
        """Return the client address advertised via PROXY protocol if any.

        Falls back to the transport peername when PROXY protocol is disabled,
        the framing was absent, the parser is the C variant (which currently
        does not surface PROXY metadata), or the transport peer is not in
        ``proxy_allow_ips`` (defense-in-depth: ``_setup_callback_parser``
        already disables PROXY parsing for untrusted peers).
        """
        if self._proxy_protocol == 'off':
            return peername
        if not _check_trusted_proxy(
            peername,
            self.cfg.proxy_allow_ips,
            self.cfg.proxy_allow_networks(),
        ):
            return peername
        parser = self._callback_parser
        info = getattr(parser, 'proxy_protocol_info', None) if parser else None
        if not info:
            return peername
        client_addr = info.get('client_addr')
        client_port = info.get('client_port')
        if client_addr is None or client_port is None:
            return peername
        return (client_addr, client_port)

    @staticmethod
    def _response_omits_body(method, status):
        """Return True when the response MUST NOT have a body (RFC 9110).

        Applies to HEAD requests and to status codes that semantically carry no body:
        1xx informational, 204 No Content, 304 Not Modified.
        """
        return (
            method == "HEAD"
            or status in (204, 304)
            or 100 <= status < 200
        )

    @staticmethod
    def _response_forbids_content_length(status):
        """Per RFC 9110 §6.4.2 a server MUST NOT send Content-Length on 1xx
        or 204 responses.  HEAD and 304 are NOT covered: HEAD MAY include the
        Content-Length the same GET would have returned, and 304 MAY include
        the Content-Length the unconditional response would have carried.
        """
        return status == 204 or 100 <= status < 200

    @classmethod
    def _strip_body_framing_headers(cls, headers, status):
        """Remove framing headers that must not appear on a no-body response.

        Transfer-Encoding is always stripped (chunked framing implies a body
        we will not send).  Content-Length is stripped only when the status
        forbids it (1xx / 204); HEAD and 304 keep app-supplied Content-Length.
        """
        forbidden = {b"transfer-encoding", "transfer-encoding"}
        if cls._response_forbids_content_length(status):
            forbidden.update({b"content-length", "content-length"})
        return [
            (n, v) for n, v in headers
            if (n.lower() if isinstance(n, str) else n.lower()) not in forbidden
        ]

    def _send_body(self, body, chunked=False, last=False, size=None):
        """Send response body chunk.

        Combines buffered headers with the first body chunk, and with
        ``last`` the final chunk with the chunked terminator, so each goes
        out in one write. A large body is handed over without being joined
        to its framing (see _NO_COPY_BODY_SIZE).
        """
        buffer = self._response_buffer
        if buffer:
            self._response_buffer = None
        if size is None:
            size = len(body)
        transport = self.transport
        try:
            if chunked and size:
                # Chunked encoding: size in hex + CRLF + data + CRLF
                # Use pre-cached prefix for common sizes, else format
                prefix = _CHUNK_PREFIXES.get(size) or f"{size:x}\r\n".encode("latin-1")
                tail = b"\r\n0\r\n\r\n" if last else b"\r\n"
                parts = (buffer, prefix, body, tail) if buffer else (prefix, body, tail)
                if size >= _NO_COPY_BODY_SIZE:
                    transport.writelines(parts)
                else:
                    transport.write(b"".join(parts))
            elif buffer:
                if size >= _NO_COPY_BODY_SIZE:
                    transport.writelines((buffer, body))
                else:
                    transport.write(buffer + body)
            elif size:
                transport.write(body)
        except OSError as e:
            if e.errno not in (errno.EPIPE, errno.ECONNRESET, errno.ENOTCONN):
                self.log.exception("Socket error writing response.")
        except (RuntimeError, AttributeError):
            # Transport is closing/closed or None
            pass

    def _send_error_response(self, status, message, extra_headers=()):
        """Send an error response.

        The status line carries the standard reason phrase; ``message``,
        which can quote the request, only goes in the body, as with the
        WSGI workers (RFC 9112 section 4: the reason phrase is fixed text
        describing the status code).
        """
        body = message.encode("utf-8")
        # gunicorn's own table first: HTTPStatus phrases change between
        # Python versions (414 is "Request-URI Too Long" before 3.13).
        reason = _REASON_PHRASES.get(status)
        if reason is None:
            try:
                reason = HTTPStatus(status).phrase
            except ValueError:
                reason = "Error"
        extra = "".join(f"{name}: {value}\r\n" for name, value in extra_headers)
        response = (
            f"HTTP/1.1 {status} {reason}\r\n"
            f"Content-Type: text/plain\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"{extra}"
            f"Connection: close\r\n"
            f"\r\n"
        )
        self._safe_write(response.encode("latin-1"))
        self._safe_write(body)

    def _get_reason_phrase(self, status):
        """Get HTTP reason phrase for status code."""
        return _REASON_PHRASES.get(status, "Unknown")

    def _close_transport(self):
        """Close the transport safely.

        Calls write_eof() first if supported to signal end of writing,
        which helps ensure buffered data is flushed before closing.
        """
        if self.transport and not self._closed:
            try:
                # Signal end of writing to help flush buffers
                if self.transport.can_write_eof():
                    self.transport.write_eof()
                self.transport.close()
            except Exception:
                pass
            self._closed = True

    async def _handle_http2_connection(self, transport, ssl_object, upgrade=None):
        """Handle an HTTP/2 connection.

        ``upgrade`` is set when the connection arrives over Upgrade: h2c and
        carries ``(settings, http1_req, body)``. The request that asked for
        the upgrade becomes stream 1 and is served before the receive loop
        starts, per RFC 7540 section 3.2.
        """
        try:
            from gunicorn.http2.async_connection import AsyncHTTP2Connection

            peername = transport.get_extra_info('peername')
            sockname = transport.get_extra_info('sockname')

            # Use the reader created in connection_made
            # (data_received feeds data to self.reader)
            reader = self.reader
            protocol = asyncio.StreamReaderProtocol(reader)
            writer = asyncio.StreamWriter(
                transport, protocol, reader, self.worker.loop
            )
            # The transport reports pause/resume to this ASGIProtocol; they
            # are forwarded to the stand-in so writer.drain() really waits.
            self._h2_writer_protocol = protocol
            self._flow_control = None
            try:
                transport.set_write_buffer_limits(high=HIGH_WATER_LIMIT)
            except (AttributeError, RuntimeError):
                pass

            # Create HTTP/2 connection handler
            h2_conn = AsyncHTTP2Connection(
                self.cfg, reader, writer, peername
            )
            if upgrade is None:
                await h2_conn.initiate_connection()
                self._h2_conn = h2_conn
            else:
                settings, http1_req, body = upgrade
                upgraded = await h2_conn.initiate_upgrade(
                    settings, http1_req, body)
                self._h2_conn = h2_conn
                self._start_http2_stream(upgraded, h2_conn, sockname, peername)
                self.worker.nr += 1

            # Main loop: each request is served by its own task as soon
            # as its headers are in, while this loop keeps reading frames
            # so bodies stream to the tasks and window credit flows back.
            # Once the worker stops accepting, or the peer sends a graceful
            # GOAWAY, the loop keeps reading until the streams already in
            # flight have finished, so their bodies still arrive; streams
            # opened meanwhile are refused.
            loop = self.worker.loop
            idle_since = None
            keepalive = self._keepalive or None
            while not h2_conn.is_closed:
                if (not self.worker.alive or h2_conn.draining) and not self._h2_tasks:
                    break
                if self._h2_tasks or h2_conn.streams:
                    idle_since = None
                elif idle_since is None:
                    idle_since = loop.time()
                elif keepalive and loop.time() - idle_since >= keepalive:
                    # Nothing open for cfg.keepalive: same as an idle
                    # HTTP/1 keep-alive connection, closed with GOAWAY.
                    await h2_conn.close()
                    break
                self._maybe_resume_reading()
                try:
                    requests = await h2_conn.receive_data(timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    self.log.debug("HTTP/2 receive error: %s", e)
                    break

                for req in requests:
                    stream_id = req.stream.stream_id
                    if not self.worker.alive:
                        await h2_conn.reset_stream(
                            stream_id, HTTP2ErrorCode.REFUSED_STREAM)
                        h2_conn.cleanup_stream(stream_id)
                        continue
                    self._start_http2_stream(req, h2_conn, sockname, peername)
                    self.worker.nr += 1
                    if self.worker.nr >= self.worker.max_requests:
                        self.log.info("Autorestarting worker after current request.")
                        self.worker.alive = False

        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.log.exception("HTTP/2 connection error: %s", e)
        finally:
            await self._finish_http2_streams()
            if hasattr(self, '_h2_conn'):
                try:
                    await self._h2_conn.close()
                except Exception:
                    pass
            self._close_transport()

    async def _finish_http2_streams(self):
        """Tell in-flight streams the peer is gone, then cancel stragglers.

        Same contract as HTTP/1: the application sees http.disconnect
        first and gets asgi_disconnect_grace_period to wind down.
        """
        tasks = list(self._h2_tasks)
        if not tasks:
            return
        h2_conn = getattr(self, '_h2_conn', None)
        if h2_conn is not None:
            h2_conn.abort_streams_nowait()
        grace = getattr(self.cfg, 'asgi_disconnect_grace_period', 3)
        if grace > 0:
            await asyncio.wait(tasks, timeout=grace)
        await self._cancel_http2_streams()

    def _maybe_resume_reading(self):
        """Resume a reader paused by data_received once the loop caught up.

        Only the HTTP/1 loop used to resume; an HTTP/2 connection that
        once paused never read again. Half the limit gives hysteresis.
        """
        if self._write_paused:
            # The transport is still over its write limit; reading more
            # would only make us answer frames we cannot send.
            return
        if not self._reading_paused:
            return
        if self.reader is not None:
            if len(self.reader._buffer) <= self._max_buffer_size // 2:
                self._resume_reading()
        elif self._http1_buffered() <= self._max_buffer_size // 2:
            self._resume_reading()

    def _start_http2_stream(self, req, h2_conn, sockname, peername):
        """Serve one stream in its own task."""
        task = self.worker.loop.create_task(
            self._serve_http2_request(req, h2_conn, sockname, peername))
        self._h2_tasks.add(task)
        task.add_done_callback(self._h2_tasks.discard)

    async def _cancel_http2_streams(self):
        """Stop stream tasks still running when the connection ends."""
        tasks = list(self._h2_tasks)
        if not tasks:
            return
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _serve_http2_request(self, req, h2_conn, sockname, peername):
        """Run one HTTP/2 request, answering 500 rather than dropping it."""
        try:
            await self._handle_http2_request(req, h2_conn, sockname, peername)
        except Exception as e:
            self.log.exception("Error handling HTTP/2 request")
            try:
                await h2_conn.send_error(req.stream.stream_id, 500, str(e))
            except Exception:
                pass
        finally:
            h2_conn.cleanup_stream(req.stream.stream_id)

    def _convert_h2_headers(self, headers):
        """Convert ASGI headers to HTTP/2 format (lowercase string names)."""
        result = []
        for name, value in headers:
            if isinstance(name, bytes):
                name = name.decode("latin-1")
            if isinstance(value, bytes):
                value = value.decode("latin-1")
            result.append((name.lower(), value))
        return result

    async def _handle_http2_request(self, request, h2_conn, sockname, peername):
        """Handle a single HTTP/2 request with streaming support.

        Streams both request and response body chunks immediately,
        avoiding buffering entire uploads and enabling SSE, streaming
        downloads, and other real-time use cases.
        """
        stream_id = request.stream.stream_id
        stream = h2_conn.streams.get(stream_id)
        scope = self._build_http2_scope(request, sockname, peername)

        response_started = False
        response_complete = False
        headers_sent = False
        omits_body = False
        omits_body_warned = False
        exc_to_raise = None
        response_status = 500
        response_headers = []
        response_sent = 0

        # Track if we've finished receiving body
        body_received = False

        async def receive():  # pylint: disable=too-many-return-statements
            nonlocal body_received

            # The peer reset the stream or the connection is gone
            if stream is None or stream.disconnected:
                return {"type": "http.disconnect"}
            if not body_received and stream.state is StreamState.CLOSED:
                return {"type": "http.disconnect"}

            if body_received:
                # The body has been delivered. Per the ASGI spec the next
                # message is http.disconnect: at once if the response is
                # already out, otherwise when the peer actually goes away.
                # Returning again at once would spin the disconnect
                # listeners frameworks run alongside the handler.
                if response_complete or peer_gone:
                    return {"type": "http.disconnect"}
                await stream.wait_disconnect()
                return {"type": "http.disconnect"}

            # First call: if body already complete (small requests), return it
            if not body_received and stream.request_complete and not stream._body_chunks:
                body_received = True
                body = stream.get_request_body()
                return {
                    "type": "http.request",
                    "body": body,
                    "more_body": False,
                }

            if stream.expect_continue and not stream.response_headers_sent:
                # The client is waiting for a 100 before sending the body.
                stream.expect_continue = False
                await h2_conn.send_informational(stream_id, 100, [])

            # Streaming: read next chunk, for at most cfg.timeout
            try:
                chunk = await asyncio.wait_for(
                    stream.read_body_chunk(),
                    timeout=self.cfg.timeout or None
                )
            except (asyncio.TimeoutError, HTTP2StreamError):
                return {"type": "http.disconnect"}

            if chunk is None:
                body_received = True
                return {
                    "type": "http.request",
                    "body": b"",
                    "more_body": False,
                }

            # END_STREAM may have landed with several frames still queued.
            done = stream._body_complete and not stream._body_chunks
            if done:
                body_received = True

            return {
                "type": "http.request",
                "body": chunk,
                "more_body": not done,
            }

        # Set once a send loses to the peer's RST_STREAM: the response is
        # over and every later send raises ClientDisconnected (ASGI 2.4);
        # none of it is an application failure.
        peer_gone = False
        expect_trailers = False
        trailers_sent = False
        pending_trailers = []

        def gone():
            nonlocal peer_gone, response_complete
            peer_gone = response_complete = True
            raise ClientDisconnected("HTTP/2 stream %d closed by the peer" % stream_id)

        async def send(message):  # pylint: disable=too-many-return-statements,too-many-branches
            nonlocal response_started, response_complete, headers_sent
            nonlocal response_status, response_headers, response_sent, exc_to_raise
            nonlocal omits_body, omits_body_warned, expect_trailers, trailers_sent

            if peer_gone or stream.disconnected:
                gone()

            msg_type = message["type"]

            if msg_type == "http.response.informational":
                # Handle informational responses (1xx) like 103 Early Hints over HTTP/2
                info_status = message.get("status")
                info_headers = message.get("headers", [])
                headers = self._convert_h2_headers(info_headers)
                await h2_conn.send_informational(stream_id, info_status, headers)
                return

            if msg_type == "http.response.start":
                if response_started:
                    exc_to_raise = RuntimeError("Response already started")
                    return
                response_started = True
                response_status = message["status"]
                # RFC 9110: HEAD, 1xx, 204 and 304 carry no body. The HTTP/1
                # handler has always applied this; HTTP/2 did not.
                omits_body = self._response_omits_body(
                    request.method, response_status)
                response_headers = message.get("headers", [])
                if omits_body:
                    response_headers = self._strip_body_framing_headers(
                        response_headers, response_status)
                expect_trailers = bool(message.get("trailers", False))
                # Don't send headers yet - wait for first body chunk

            elif msg_type == "http.response.body":
                if not response_started:
                    exc_to_raise = RuntimeError("Response not started")
                    return
                if response_complete:
                    exc_to_raise = RuntimeError("Response already complete")
                    return

                body = message.get("body", b"")
                more_body = message.get("more_body", False)

                if omits_body:
                    if body and not omits_body_warned:
                        self.log.warning(
                            "ASGI app sent body bytes on a no-body response "
                            "(method=%s status=%s); dropping per RFC 9110.",
                            request.method, response_status,
                        )
                        omits_body_warned = True
                    body = b""

                # Send headers with first body chunk
                if not headers_sent:
                    headers = self._convert_h2_headers(response_headers)
                    response_hdrs = [(':status', str(response_status))]
                    response_hdrs.extend(headers)

                    # Send headers without end_stream since we have body
                    if not await h2_conn.send_response_headers(
                            stream_id, response_hdrs, end_stream=False):
                        gone()
                    headers_sent = True

                # The stream ends with the body unless trailers follow
                final = not more_body and not expect_trailers

                # Stream body immediately
                if body:
                    if not await h2_conn.send_data(stream_id, body, end_stream=final):
                        gone()
                    response_sent += len(body)

                if not more_body:
                    if not body and final:
                        # Empty final chunk - send end_stream
                        if not await h2_conn.send_data(stream_id, b"", end_stream=True):
                            gone()
                    response_complete = True

            elif msg_type == "http.response.trailers":
                if not response_complete:
                    exc_to_raise = RuntimeError("Cannot send trailers before body complete")
                    return
                if not expect_trailers:
                    exc_to_raise = RuntimeError(
                        "Trailers were not announced in http.response.start")
                    return
                if trailers_sent:
                    exc_to_raise = RuntimeError("Trailers already sent")
                    return
                pending_trailers.extend(message.get("headers", []))
                if message.get("more_trailers", False):
                    return
                trailers = self._convert_h2_headers(pending_trailers)
                trailers_sent = True
                if not await h2_conn.send_trailers(stream_id, trailers):
                    gone()

        # Only build environ for logging if access logging is enabled
        access_log_enabled = self.log.access_log_enabled
        request_start = time.monotonic()

        try:
            if self._pre_request is not None:
                self._pre_request(self.worker, request)
            await self.app(scope, receive, send)

            if exc_to_raise is not None:
                raise exc_to_raise

            # Handle case where app didn't send any response
            if peer_gone or stream.disconnected:
                pass  # nobody to answer
            elif not response_started:
                await h2_conn.send_error(stream_id, 500, "Internal Server Error")
                response_status = 500

            # Trailers were announced but never sent: end the stream anyway
            elif headers_sent and expect_trailers and not trailers_sent and not peer_gone:
                await h2_conn.send_data(stream_id, b"", end_stream=True)

            # Handle case where headers were started but no body was sent
            elif not headers_sent:
                # Send headers now (empty body response)
                headers = self._convert_h2_headers(response_headers)
                response_hdrs = [(':status', str(response_status))]
                response_hdrs.extend(headers)
                await h2_conn.send_response_headers(
                    stream_id, response_hdrs, end_stream=True)

        except (ClientDisconnected, HTTP2ConnectionError) as e:
            # A peer that reset the stream or left is not an app failure
            self.log.debug("HTTP/2 stream %s: %s", stream_id, e)
        except Exception:
            self.log.exception("Error in ASGI application")
            if not headers_sent and not peer_gone:
                await h2_conn.send_error(stream_id, 500, "Internal Server Error")
                response_status = 500
        finally:
            try:
                request_time = _RequestTime(time.monotonic() - request_start)
                # Only build log data if access logging is enabled
                if access_log_enabled:
                    environ = self._build_http2_environ(request, sockname, peername)
                    resp = ASGIResponseInfo(
                        response_status, response_headers, response_sent
                    )
                    self.log.access(resp, request, environ, request_time)
                else:
                    environ = None
                    resp = None
                if self._post_request is not None:
                    self._post_request(self.worker, request, environ, resp)
            except Exception:
                self.log.exception("Exception in post_request hook")

    def _build_http2_scope(self, request, sockname, peername):
        """Build ASGI HTTP scope from HTTP/2 request."""
        headers = []
        for name, value in request.headers:
            headers.append((
                name.lower().encode("latin-1"),
                value.encode("latin-1")
            ))

        server = _normalize_sockaddr(sockname)
        client = _normalize_sockaddr(peername)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "2",
            "method": request.method,
            "scheme": request.scheme,
            "path": request.path,
            "raw_path": getattr(request, 'raw_path', None) or (request.path.encode("latin-1") if request.path else b""),
            "query_string": request.query.encode("latin-1") if request.query else b"",
            "root_path": self._root_path,
            "headers": headers,
            "server": server,
            "client": client,
        }

        if hasattr(self.worker, 'state'):
            scope["state"] = self.worker.state.copy()

        # Add HTTP/2 extensions
        extensions = {}
        if hasattr(request, 'priority_weight'):
            extensions["http.response.priority"] = {
                "weight": request.priority_weight,
                "depends_on": request.priority_depends_on,
            }
        # Add trailer support extension for HTTP/2
        extensions["http.response.trailers"] = {}
        scope["extensions"] = extensions

        return scope

    def _build_http2_environ(self, request, sockname, peername):
        """Build minimal environ dict for access logging."""
        environ = {
            "REQUEST_METHOD": request.method,
            "RAW_URI": request.uri,
            "PATH_INFO": request.path,
            "QUERY_STRING": request.query or "",
            "SERVER_PROTOCOL": "HTTP/2",
            "REMOTE_ADDR": peername[0] if peername else "-",
        }

        for name, value in request.headers:
            key = "HTTP_" + name.replace("-", "_")
            environ[key] = value

        return environ
