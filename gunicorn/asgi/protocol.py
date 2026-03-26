#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
ASGI protocol handler for gunicorn.

Implements asyncio.Protocol to handle HTTP/1.x and HTTP/2 connections
and dispatch to ASGI applications.
"""

import asyncio
import errno
import ipaddress
import time

from gunicorn.asgi.unreader import AsyncUnreader
from gunicorn.asgi.parser import (
    PythonProtocol, CallbackRequest, ParseError,
    LimitRequestLine, LimitRequestHeaders, InvalidChunkExtension
)
from gunicorn.asgi.uwsgi import AsyncUWSGIRequest
from gunicorn.http.errors import NoMoreData
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


# Cached response bytes for common cases
_CACHED_STATUS_LINES = {}
_CACHED_SERVER_HEADER = b"Server: gunicorn/asgi\r\n"

# Date header cache (updated once per second)
_cached_date_header = b""
_cached_date_time = 0.0

# Pre-compute common chunk size prefixes to avoid repeated formatting
_CHUNK_PREFIXES = {i: f"{i:x}\r\n".encode("latin-1") for i in range(16384)}

# High water mark for write buffer backpressure (64KB)
HIGH_WATER_LIMIT = 65536


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


def _get_cached_status_line(version, status, reason):
    """Get cached status line bytes."""
    key = (version, status)
    if key not in _CACHED_STATUS_LINES:
        line = f"HTTP/{version[0]}.{version[1]} {status} {reason}\r\n"
        _CACHED_STATUS_LINES[key] = line.encode("latin-1")
    return _CACHED_STATUS_LINES[key]


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

    __slots__ = ('_chunks', '_complete', '_body_finished', '_closed', '_waiter',
                 'request', 'protocol')

    def __init__(self, request, protocol):
        self.request = request
        self.protocol = protocol
        self._chunks = []
        self._complete = False
        self._body_finished = False  # True after returning more_body=False
        self._closed = False
        self._waiter = None

    def feed(self, chunk):
        """Feed a body chunk directly (called by parser callback)."""
        if chunk:
            self._chunks.append(chunk)
            self._wake_waiter()

    def set_complete(self):
        """Mark body as complete (called when message ends)."""
        self._complete = True
        self._wake_waiter()

    def signal_disconnect(self):
        """Signal that connection has been lost."""
        self._closed = True
        self._wake_waiter()

    def _wake_waiter(self):
        """Wake up any pending receive() call."""
        if self._waiter is not None and not self._waiter.done():
            self._waiter.set_result(None)

    async def receive(self):  # pylint: disable=too-many-return-statements
        """ASGI receive callable - returns body chunks or disconnect."""
        # Already disconnected or body finished
        if self._closed or self._body_finished:
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

        # Wait for body chunk to arrive via callback
        try:
            await self._wait_for_data()
            return self._build_receive_result()
        except asyncio.CancelledError:
            return {"type": "http.disconnect"}

    def _pop_chunk(self):
        """Pop a chunk and return the appropriate message."""
        chunk = self._chunks.pop(0)
        more = bool(self._chunks) or not self._complete
        if not more:
            self._body_finished = True
        return {"type": "http.request", "body": chunk, "more_body": more}

    def _build_receive_result(self):
        """Build receive result after waiting for data."""
        if self._closed:
            return {"type": "http.disconnect"}

        if self._chunks:
            return self._pop_chunk()

        # Complete OR timeout - mark body finished to prevent infinite loops
        # Apps should not loop forever waiting for body that won't arrive
        self._body_finished = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def _wait_for_data(self):
        """Wait for body data to arrive via callback."""
        if self._chunks or self._complete or self._closed:
            return

        # Create a new waiter
        loop = asyncio.get_event_loop()
        self._waiter = loop.create_future()

        try:
            # Wait with timeout for data or completion
            await asyncio.wait_for(self._waiter, timeout=30.0)
        except asyncio.TimeoutError:
            pass
        finally:
            self._waiter = None


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
    _h1c_invalid_chunk_extension = None  # Exception class from gunicorn_h1c >= 0.6.3

    def __init__(self, worker):
        self.worker = worker
        self.cfg = worker.cfg
        self.log = worker.log
        self.app = worker.asgi

        self.transport = None
        self.reader = None  # Only used for HTTP/2
        self.writer = None
        self._task = None
        self.req_count = 0

        # Connection state
        self._closed = False
        self._body_receiver = None  # Set per-request for disconnect signaling

        # Response buffering for write batching
        self._response_buffer = None

        # Backpressure control
        self._reading_paused = False
        self._max_buffer_size = 65536 * 4  # 256KB max buffer (HTTP/2 only)

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

        # HTTP/1.x connection - always use callback parser
        self._is_ssl = ssl_object is not None
        self.writer = transport

        # Setup flow control for HTTP/1.x
        self._flow_control = FlowControl(transport)
        transport.set_write_buffer_limits(high=HIGH_WATER_LIMIT)

        # Setup callback parser with request ready event
        self._request_ready = asyncio.Event()
        self._setup_callback_parser()
        self._task = self.worker.loop.create_task(self._handle_connection())

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
                # Check for InvalidChunkExtension (>= 0.6.3)
                cls._h1c_invalid_chunk_extension = getattr(
                    gunicorn_h1c, 'InvalidChunkExtension', None
                )
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

        # Create parser with callbacks and limit parameters (both parsers support them)
        self._callback_parser = parser_class(
            on_headers_complete=self._on_headers_complete,
            on_body=self._on_body,
            on_message_complete=self._on_message_complete,
            limit_request_line=limit_request_line,
            limit_request_fields=self.cfg.limit_request_fields,
            limit_request_field_size=self.cfg.limit_request_field_size,
            permit_unconventional_http_method=self.cfg.permit_unconventional_http_method,
            permit_unconventional_http_version=self.cfg.permit_unconventional_http_version,
        )

    def _on_headers_complete(self):
        """Callback: request headers are complete."""
        # Build request from parser state
        self._current_request = CallbackRequest.from_parser(
            self._callback_parser, is_ssl=self._is_ssl
        )

        # Create body receiver for this request
        self._body_receiver = BodyReceiver(self._current_request, self)

        # Signal that request is ready for processing
        if self._request_ready:
            self._request_ready.set()

        # Return True for HEAD to skip body parsing
        return self._callback_parser.method == b'HEAD'

    def _on_body(self, chunk):
        """Callback: received body data chunk."""
        if self._body_receiver:
            self._body_receiver.feed(chunk)

    def _on_message_complete(self):
        """Callback: request is fully received."""
        if self._body_receiver:
            self._body_receiver.set_complete()

    def data_received(self, data):
        """Called when data is received on the connection."""
        if self._websocket:
            # WebSocket path - forward to WebSocket protocol
            self._websocket.feed_data(data)
            return
        if self.reader:
            # HTTP/2 path - use StreamReader
            self.reader.feed_data(data)
        elif self._callback_parser:
            # HTTP/1.x path - feed directly to callback parser
            try:
                self._callback_parser.feed(data)
            except LimitRequestLine as e:
                self._send_error_response(414, str(e))  # URI Too Long
                self._close_transport()
                return
            except LimitRequestHeaders as e:
                self._send_error_response(431, str(e))  # Request Header Fields Too Large
                self._close_transport()
                return
            except InvalidChunkExtension as e:
                self._send_error_response(400, str(e))
                self._close_transport()
                return
            except ParseError as e:
                self._send_error_response(400, str(e))
                self._close_transport()
                return
            except Exception as e:
                # Handle gunicorn_h1c exceptions (different class hierarchy)
                h1c_exc = ASGIProtocol._h1c_invalid_chunk_extension
                # pylint: disable=isinstance-second-argument-not-valid-type
                if h1c_exc is not None and isinstance(e, h1c_exc):
                    self._send_error_response(400, str(e))
                    self._close_transport()
                    return
                raise

        # Backpressure: pause reading if buffer is too large
        if not self._reading_paused and self._is_buffer_full():
            self._pause_reading()

    def _is_buffer_full(self):
        """Check if internal buffer is full (HTTP/2 only)."""
        if self.reader and hasattr(self.reader, '_buffer'):
            return len(self.reader._buffer) > self._max_buffer_size
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
        keepalive_timeout = self.cfg.keepalive
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

    def connection_lost(self, exc):
        """Called when the connection is lost or closed.

        Instead of immediately cancelling the task, we signal a disconnect
        event and send an http.disconnect message to the receive queue.
        This allows the ASGI app to clean up resources (like database
        connections) gracefully before the task is cancelled.

        See: https://github.com/benoitc/gunicorn/issues/3484
        """
        # Guard against multiple calls (idempotent)
        if self._closed:
            return

        self._closed = True
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

    def resume_writing(self):
        """Called by transport when write buffer drains below low water mark."""
        if self._flow_control:
            self._flow_control.resume_writing()

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
        try:
            peername = self.transport.get_extra_info('peername')
            sockname = self.transport.get_extra_info('sockname')

            # Check protocol type - use separate path for uWSGI
            protocol_type = getattr(self.cfg, 'protocol', 'http')
            if protocol_type == 'uwsgi':
                await self._handle_connection_uwsgi(peername, sockname)
                return

            while not self._closed:
                self.req_count += 1
                self._cancel_keepalive_timer()

                # Wait for headers to be parsed (callback sets the event and _current_request)
                # Don't clear if request already arrived (data_received ran before us)
                if not self._request_ready.is_set():
                    try:
                        await self._request_ready.wait()
                    except asyncio.CancelledError:
                        break

                if self._closed or self._current_request is None:
                    break

                request = self._current_request

                # Check for WebSocket upgrade
                if self._is_websocket_upgrade(request):
                    await self._handle_websocket(request, sockname, peername)
                    break  # WebSocket takes over the connection

                # Handle HTTP request
                keepalive = await self._handle_http_request(
                    request, sockname, peername
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
                if not self.cfg.keepalive:
                    break

                # Resume reading if paused during body consumption
                self._resume_reading()

                # Reset parser for next request
                if self._callback_parser:
                    self._callback_parser.reset()

                # Clear request state for next iteration
                self._current_request = None
                self._body_receiver = None
                self._request_ready.clear()

                # Arm keepalive timer between requests
                self._arm_keepalive_timer()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.log.exception("Error handling connection: %s", e)
        finally:
            self._close_transport()

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

            # Handle HTTP request
            keepalive = await self._handle_http_request(
                request, sockname, peername
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

            if not self.cfg.keepalive:
                break

            await request.drain_body()

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

        scope = self._build_websocket_scope(request, sockname, peername)
        ws_protocol = WebSocketProtocol(
            self.transport, scope, self.app, self.log
        )

        # Store reference so data_received() forwards to WebSocket
        self._websocket = ws_protocol

        await ws_protocol.run()

    async def _handle_http_request(self, request, sockname, peername):
        """Handle a single HTTP request."""
        scope = self._build_http_scope(request, sockname, peername)
        response_started = False
        response_complete = False
        exc_to_raise = None
        use_chunked = False

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
            nonlocal response_status, response_headers, response_sent, use_chunked

            # If client disconnected, silently ignore send attempts
            # This allows apps to finish cleanup without errors
            if self._closed:
                return

            msg_type = message["type"]

            if msg_type == "http.response.informational":
                # Handle informational responses (1xx) like 103 Early Hints
                info_status = message.get("status")
                info_headers = message.get("headers", [])
                self._send_informational(info_status, info_headers, request)
                return

            if msg_type == "http.response.start":
                if response_started:
                    exc_to_raise = RuntimeError("Response already started")
                    return
                response_started = True
                response_status = message["status"]
                response_headers = message.get("headers", [])

                # Check if Content-Length is present
                has_content_length = any(
                    (name.lower() if isinstance(name, str) else name.lower()) == b"content-length"
                    or (name.lower() if isinstance(name, str) else name.lower()) == "content-length"
                    for name, _ in response_headers
                )

                # Use chunked encoding for HTTP/1.1 streaming responses without Content-Length
                if not has_content_length and request.version >= (1, 1):
                    use_chunked = True
                    response_headers = list(response_headers) + [(b"transfer-encoding", b"chunked")]

                self._send_response_start(response_status, response_headers, request)

            elif msg_type == "http.response.body":
                if not response_started:
                    exc_to_raise = RuntimeError("Response not started")
                    return
                if response_complete:
                    exc_to_raise = RuntimeError("Response already complete")
                    return

                body = message.get("body", b"")
                more_body = message.get("more_body", False)

                if body:
                    self._send_body(body, chunked=use_chunked)
                    response_sent += len(body)
                    # Apply write backpressure for streaming responses
                    if self._flow_control:
                        await self._flow_control.drain()

                if not more_body:
                    if use_chunked:
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

        # Only build environ for logging if access logging is enabled
        access_log_enabled = self.log.access_log_enabled

        try:
            request_start = time.monotonic()
            self.cfg.pre_request(self.worker, request)

            await self.app(scope, body_receiver.receive, send)

            if exc_to_raise is not None:
                raise exc_to_raise

            # Ensure response was sent
            if not response_started:
                self._send_error_response(500, "Internal Server Error")
                response_status = 500

        except asyncio.CancelledError:
            # Client disconnected - don't log as error, this is normal
            self.log.debug("Request cancelled (client disconnected)")
            return False
        except Exception:
            self.log.exception("Error in ASGI application")
            if not response_started:
                self._send_error_response(500, "Internal Server Error")
                response_status = 500
            return False
        finally:
            # Clear the body receiver reference
            self._body_receiver = None

            try:
                request_time = _RequestTime(time.monotonic() - request_start)
                # Only build log data if access logging is enabled
                if access_log_enabled:
                    environ = self._build_environ(request, sockname, peername)
                    resp = ASGIResponseInfo(response_status, response_headers, response_sent)
                    self.log.access(resp, request, environ, request_time)
                else:
                    environ = None
                    resp = None
                self.cfg.post_request(self.worker, request, environ, resp)
            except Exception:
                self.log.exception("Exception in post_request hook")

        # Determine keepalive
        if request.should_close():
            return False

        return self.worker.alive and self.cfg.keepalive

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

        server = _normalize_sockaddr(sockname)
        client = _normalize_sockaddr(peername)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": f"{request.version[0]}.{request.version[1]}",
            "method": request.method,
            "scheme": request.scheme,
            "path": request.path,
            "raw_path": request.raw_path if request.raw_path else b"",
            "query_string": request.query.encode("latin-1") if request.query else b"",
            "root_path": self.cfg.root_path or "",
            "headers": headers,
            "server": server,
            "client": client,
        }

        # Add state dict for lifespan sharing
        if hasattr(self.worker, 'state'):
            scope["state"] = self.worker.state

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
            "root_path": self.cfg.root_path or "",
            "headers": headers,
            "server": server,
            "client": client,
            "subprotocols": subprotocols,
        }

        # Add state dict for lifespan sharing
        if hasattr(self.worker, 'state'):
            scope["state"] = self.worker.state

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

    def _send_response_start(self, status, headers, request):
        """Send HTTP response status and headers.

        Uses cached status lines and headers for common cases to avoid
        repeated string formatting and encoding.
        """
        # Get cached status line bytes
        reason = self._get_reason_phrase(status)
        status_line = _get_cached_status_line(request.version, status, reason)

        # Build headers as bytes directly
        parts = [status_line]

        has_date = False
        has_server = False

        for name, value in headers:
            if isinstance(name, bytes):
                name_lower = name.lower()
                parts.append(name)
            else:
                name_lower = name.lower().encode("latin-1")
                parts.append(name.encode("latin-1"))

            parts.append(b": ")

            if isinstance(value, bytes):
                parts.append(value)
            else:
                parts.append(value.encode("latin-1"))

            parts.append(b"\r\n")

            # Track if Date/Server headers are present
            if name_lower == b"date":
                has_date = True
            elif name_lower == b"server":
                has_server = True

        # Add default headers if not present
        if not has_server:
            parts.append(_CACHED_SERVER_HEADER)
        if not has_date:
            parts.append(_get_cached_date_header())

        parts.append(b"\r\n")

        # Buffer headers for batching with first body chunk
        self._response_buffer = b"".join(parts)

    def _send_body(self, body, chunked=False):
        """Send response body chunk.

        Combines buffered headers with first body chunk for efficient write batching.
        """
        if chunked:
            if body:
                # Chunked encoding: size in hex + CRLF + data + CRLF
                # Use pre-cached prefix for common sizes, else format
                size = len(body)
                prefix = _CHUNK_PREFIXES.get(size) or f"{size:x}\r\n".encode("latin-1")
                chunk_data = prefix + body + b"\r\n"
            else:
                chunk_data = b""

            # Combine with buffered headers if present
            if self._response_buffer:
                self._safe_write(self._response_buffer + chunk_data)
                self._response_buffer = None
            elif chunk_data:
                self._safe_write(chunk_data)
        else:
            # Non-chunked: combine headers + body or just body
            if self._response_buffer:
                self._safe_write(self._response_buffer + body)
                self._response_buffer = None
            elif body:
                self._safe_write(body)

    def _send_error_response(self, status, message):
        """Send an error response."""
        body = message.encode("utf-8")
        response = (
            f"HTTP/1.1 {status} {message}\r\n"
            f"Content-Type: text/plain\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        )
        self._safe_write(response.encode("latin-1"))
        self._safe_write(body)

    def _get_reason_phrase(self, status):
        """Get HTTP reason phrase for status code."""
        reasons = {
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
        return reasons.get(status, "Unknown")

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

    async def _handle_http2_connection(self, transport, ssl_object):
        """Handle an HTTP/2 connection."""
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

            # Create HTTP/2 connection handler
            h2_conn = AsyncHTTP2Connection(
                self.cfg, reader, writer, peername
            )
            await h2_conn.initiate_connection()

            self._h2_conn = h2_conn

            # Main loop - receive and handle requests
            while not h2_conn.is_closed and self.worker.alive:
                try:
                    requests = await h2_conn.receive_data(timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    self.log.debug("HTTP/2 receive error: %s", e)
                    break

                for req in requests:
                    try:
                        await self._handle_http2_request(
                            req, h2_conn, sockname, peername
                        )
                    except Exception as e:
                        self.log.exception("Error handling HTTP/2 request")
                        try:
                            await h2_conn.send_error(
                                req.stream.stream_id, 500, str(e)
                            )
                        except Exception:
                            pass
                    finally:
                        h2_conn.cleanup_stream(req.stream.stream_id)

                # Increment worker request count
                self.worker.nr += len(requests)

                # Check max_requests
                if self.worker.nr >= self.worker.max_requests:
                    self.log.info("Autorestarting worker after current request.")
                    self.worker.alive = False
                    break

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.log.exception("HTTP/2 connection error: %s", e)
        finally:
            if hasattr(self, '_h2_conn'):
                try:
                    await self._h2_conn.close()
                except Exception:
                    pass
            self._close_transport()

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
        exc_to_raise = None
        response_status = 500
        response_headers = []
        response_sent = 0

        # Track if we've finished receiving body
        body_received = False

        async def receive():
            nonlocal body_received

            # Check if stream is closed or missing
            if stream is None or stream.state.name == "CLOSED":
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

            # Streaming: read next chunk
            try:
                chunk = await asyncio.wait_for(
                    stream.read_body_chunk(),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                return {"type": "http.disconnect"}

            if chunk is None:
                body_received = True
                return {
                    "type": "http.request",
                    "body": b"",
                    "more_body": False,
                }

            if stream._body_complete:
                body_received = True

            return {
                "type": "http.request",
                "body": chunk,
                "more_body": not stream._body_complete,
            }

        async def send(message):
            nonlocal response_started, response_complete, headers_sent
            nonlocal response_status, response_headers, response_sent, exc_to_raise

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
                response_headers = message.get("headers", [])
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

                # Send headers with first body chunk
                if not headers_sent:
                    headers = self._convert_h2_headers(response_headers)
                    response_hdrs = [(':status', str(response_status))]
                    response_hdrs.extend(headers)

                    # Send headers without end_stream since we have body
                    stream = h2_conn.streams.get(stream_id)
                    if stream is None:
                        exc_to_raise = RuntimeError("Stream closed")
                        return
                    h2_conn.h2_conn.send_headers(stream_id, response_hdrs, end_stream=False)
                    stream.send_headers(response_hdrs, end_stream=False)
                    await h2_conn._send_pending_data()
                    headers_sent = True

                # Stream body immediately
                if body:
                    await h2_conn.send_data(stream_id, body, end_stream=not more_body)
                    response_sent += len(body)

                if not more_body:
                    if not body:
                        # Empty final chunk - send end_stream
                        await h2_conn.send_data(stream_id, b"", end_stream=True)
                    response_complete = True

            elif msg_type == "http.response.trailers":
                if not response_complete:
                    exc_to_raise = RuntimeError("Cannot send trailers before body complete")
                    return
                trailer_headers = message.get("headers", [])
                trailers = self._convert_h2_headers(trailer_headers)
                await h2_conn.send_trailers(stream_id, trailers)

        # Only build environ for logging if access logging is enabled
        access_log_enabled = self.log.access_log_enabled
        request_start = time.monotonic()

        try:
            self.cfg.pre_request(self.worker, request)
            await self.app(scope, receive, send)

            if exc_to_raise is not None:
                raise exc_to_raise

            # Handle case where app didn't send any response
            if not response_started:
                await h2_conn.send_error(stream_id, 500, "Internal Server Error")
                response_status = 500

            # Handle case where headers were started but no body was sent
            elif not headers_sent:
                # Send headers now (empty body response)
                headers = self._convert_h2_headers(response_headers)
                response_hdrs = [(':status', str(response_status))]
                response_hdrs.extend(headers)
                stream = h2_conn.streams.get(stream_id)
                if stream:
                    h2_conn.h2_conn.send_headers(stream_id, response_hdrs, end_stream=True)
                    stream.send_headers(response_hdrs, end_stream=True)
                    await h2_conn._send_pending_data()

        except Exception:
            self.log.exception("Error in ASGI application")
            if not headers_sent:
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
                self.cfg.post_request(self.worker, request, environ, resp)
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
            "root_path": self.cfg.root_path or "",
            "headers": headers,
            "server": server,
            "client": client,
        }

        if hasattr(self.worker, 'state'):
            scope["state"] = self.worker.state

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
