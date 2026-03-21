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
from datetime import datetime

from gunicorn.asgi.unreader import AsyncUnreader
from gunicorn.asgi.parser import HttpParser, FastAsyncRequest
from gunicorn.asgi.uwsgi import AsyncUWSGIRequest
from gunicorn.http.errors import NoMoreData
from gunicorn.uwsgi.errors import UWSGIParseException


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


def _get_cached_date_header():
    """Get cached Date header, updating once per second."""
    global _cached_date_header, _cached_date_time  # pylint: disable=global-statement
    import time
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
    """Lightweight body receiver that reads directly on demand.

    Replaces per-request Queue and Task with direct on-demand reading.
    This reduces allocations and improves performance for most requests
    where body is read sequentially.
    """

    __slots__ = ('request', 'protocol', 'body_complete', '_disconnect_event')

    def __init__(self, request, protocol):
        self.request = request
        self.protocol = protocol
        self.body_complete = False
        self._disconnect_event = asyncio.Event()

    def signal_disconnect(self):
        """Signal that connection has been lost."""
        self._disconnect_event.set()

    async def receive(self):  # pylint: disable=too-many-return-statements
        """ASGI receive callable - reads body on demand."""
        # Already finished body - return disconnect
        if self.body_complete:
            return {"type": "http.disconnect"}

        # No body expected - must return body message before disconnect
        if self.request.content_length == 0 and not self.request.chunked:
            self.body_complete = True
            return {
                "type": "http.request",
                "body": b"",
                "more_body": False,
            }

        # Check for disconnect before reading (only when body hasn't been returned)
        if self.protocol._closed:
            return {"type": "http.disconnect"}

        # Read body chunk directly (no intermediate Queue)
        try:
            # Create tasks for reading body and waiting for disconnect
            read_task = asyncio.create_task(self.request.read_body(65536))
            disconnect_task = asyncio.create_task(self._disconnect_event.wait())

            # Wait for either body data or disconnect
            done, pending = await asyncio.wait(
                [read_task, disconnect_task],
                return_when=asyncio.FIRST_COMPLETED
            )

            # Cancel pending tasks
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            # Check what completed
            if disconnect_task in done:
                return {"type": "http.disconnect"}

            chunk = read_task.result()

            if chunk:
                return {
                    "type": "http.request",
                    "body": chunk,
                    "more_body": True,
                }
            else:
                self.body_complete = True
                return {
                    "type": "http.request",
                    "body": b"",
                    "more_body": False,
                }

        except asyncio.CancelledError:
            return {"type": "http.disconnect"}
        except Exception:
            self.body_complete = True
            return {
                "type": "http.request",
                "body": b"",
                "more_body": False,
            }


class ASGIProtocol(asyncio.Protocol):
    """HTTP/1.1 protocol handler for ASGI applications.

    Handles connection lifecycle, request parsing, and ASGI app invocation.
    """

    def __init__(self, worker):
        self.worker = worker
        self.cfg = worker.cfg
        self.log = worker.log
        self.app = worker.asgi

        self.transport = None
        self.reader = None
        self.writer = None
        self._task = None
        self.req_count = 0

        # Connection state
        self._closed = False
        self._body_receiver = None  # Set per-request for disconnect signaling

        # Backpressure control
        self._reading_paused = False
        self._max_buffer_size = 65536 * 4  # 256KB max buffer

        # Keep-alive timer
        self._keepalive_handle = None

    def connection_made(self, transport):
        """Called when a connection is established."""
        self.transport = transport
        self.worker.nr_conns += 1

        # Check if HTTP/2 was negotiated via ALPN
        ssl_object = transport.get_extra_info('ssl_object')
        if ssl_object and hasattr(ssl_object, 'selected_alpn_protocol'):
            alpn = ssl_object.selected_alpn_protocol()
            if alpn == 'h2':
                # HTTP/2 connection - create reader immediately to avoid race condition
                # data_received may be called before _handle_http2_connection starts
                self.reader = asyncio.StreamReader()
                self._task = self.worker.loop.create_task(
                    self._handle_http2_connection(transport, ssl_object)
                )
                return

        # HTTP/1.x connection
        # Create stream reader/writer
        self.reader = asyncio.StreamReader()
        self.writer = transport

        # Start handling requests
        self._task = self.worker.loop.create_task(self._handle_connection())

    def data_received(self, data):
        """Called when data is received on the connection."""
        if self.reader:
            self.reader.feed_data(data)
            # Backpressure: pause reading if buffer is too large
            if not self._reading_paused and self._is_buffer_full():
                self._pause_reading()

    def _is_buffer_full(self):
        """Check if internal buffer is full."""
        # Check StreamReader internal buffer size
        if hasattr(self.reader, '_buffer'):
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
        """Main request handling loop for this connection."""
        try:
            peername = self.transport.get_extra_info('peername')
            sockname = self.transport.get_extra_info('sockname')

            # Check protocol type - use old path for uWSGI
            protocol_type = getattr(self.cfg, 'protocol', 'http')
            if protocol_type == 'uwsgi':
                await self._handle_connection_uwsgi(peername, sockname)
                return

            # Fast path: use HttpParser for HTTP protocol
            await self._handle_connection_fast(peername, sockname)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.log.exception("Error handling connection: %s", e)
        finally:
            self._close_transport()

    async def _handle_connection_fast(self, peername, sockname):
        """Fast HTTP connection handling using HttpParser."""
        # Check if peer is trusted proxy once per connection
        is_trusted = _check_trusted_proxy(
            peername,
            self.cfg.forwarded_allow_ips,
            self.cfg.forwarded_allow_networks()
        )

        # Get SSL state
        ssl_object = self.transport.get_extra_info('ssl_object')
        is_ssl = ssl_object is not None

        # Create parser and buffer
        parser = HttpParser(
            self.cfg, peername, is_ssl=is_ssl,
            req_number=1, is_trusted_proxy=is_trusted
        )
        buffer = bytearray()

        while not self._closed:
            self.req_count += 1

            # Cancel keepalive timer when new request starts
            self._cancel_keepalive_timer()

            try:
                # Parse request using fast parser
                request = await self._parse_request_fast(
                    parser, buffer, peername
                )
            except NoMoreData:
                # Client disconnected
                break

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

            # Drain any unread body before next request
            await request.drain_body()

            # Resume reading if paused during body consumption
            self._resume_reading()

            # Reset parser for next request (keep trusted proxy check)
            parser.reset()

            # Arm keepalive timer between requests
            self._arm_keepalive_timer()

    async def _parse_request_fast(self, parser, buffer, peername):
        """Parse request using fast HttpParser.

        Returns a FastAsyncRequest wrapping the ParseResult.
        """
        # Read data until we have complete headers
        while True:
            # Try to parse current buffer
            if buffer:
                try:
                    result = parser.feed(buffer)
                    if result is not None:
                        # Headers complete - create request wrapper
                        request = FastAsyncRequest(
                            result, self.reader, buffer, result.consumed
                        )
                        # Clear consumed data from buffer
                        del buffer[:result.consumed]
                        return request
                except Exception as e:
                    # Re-raise HTTP parsing errors
                    if 'incomplete' not in str(e).lower():
                        raise

            # Need more data
            try:
                data = await self.reader.read(65536)
            except Exception:
                data = b""

            if not data:
                raise NoMoreData(bytes(buffer))

            buffer.extend(data)

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

        scope = self._build_websocket_scope(request, sockname, peername)
        ws_protocol = WebSocketProtocol(
            self.transport, self.reader, scope, self.app, self.log
        )
        await ws_protocol.run()

    async def _handle_http_request(self, request, sockname, peername):
        """Handle a single HTTP request."""
        scope = self._build_http_scope(request, sockname, peername)
        response_started = False
        response_complete = False
        exc_to_raise = None
        use_chunked = False

        # Response tracking for access logging
        response_status = 500
        response_headers = []
        response_sent = 0

        # Create body receiver - reads directly on demand, no Queue/Task overhead
        body_receiver = BodyReceiver(request, self)
        self._body_receiver = body_receiver

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
                await self._send_informational(info_status, info_headers, request)
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

                await self._send_response_start(response_status, response_headers, request)

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
                    await self._send_body(body, chunked=use_chunked)
                    response_sent += len(body)

                if not more_body:
                    if use_chunked:
                        # Send terminal chunk
                        self._safe_write(b"0\r\n\r\n")
                    response_complete = True

        # Build environ for logging
        environ = self._build_environ(request, sockname, peername)
        resp = None

        try:
            request_start = datetime.now()
            self.cfg.pre_request(self.worker, request)

            await self.app(scope, body_receiver.receive, send)

            if exc_to_raise is not None:
                raise exc_to_raise

            # Ensure response was sent
            if not response_started:
                await self._send_error_response(500, "Internal Server Error")
                response_status = 500

        except asyncio.CancelledError:
            # Client disconnected - don't log as error, this is normal
            self.log.debug("Request cancelled (client disconnected)")
            return False
        except Exception:
            self.log.exception("Error in ASGI application")
            if not response_started:
                await self._send_error_response(500, "Internal Server Error")
                response_status = 500
            return False
        finally:
            # Clear the body receiver reference
            self._body_receiver = None

            try:
                request_time = datetime.now() - request_start
                # Create response info for logging
                resp = ASGIResponseInfo(response_status, response_headers, response_sent)
                self.log.access(resp, request, environ, request_time)
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
        # Fall back to conversion for legacy requests (AsyncRequest, HTTP/2)
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
            "raw_path": request.path.encode("latin-1") if request.path else b"",
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
            "raw_path": request.path.encode("latin-1") if request.path else b"",
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

    async def _send_informational(self, status, headers, request):
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

    async def _send_response_start(self, status, headers, request):
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

        # Write as single buffer
        self._safe_write(b"".join(parts))

    async def _send_body(self, body, chunked=False):
        """Send response body chunk."""
        if body:
            if chunked:
                # Chunked encoding: size in hex + CRLF + data + CRLF
                chunk = f"{len(body):x}\r\n".encode("latin-1") + body + b"\r\n"
                self._safe_write(chunk)
            else:
                self._safe_write(body)

    async def _send_error_response(self, status, message):
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

    async def _handle_http2_request(self, request, h2_conn, sockname, peername):
        """Handle a single HTTP/2 request."""
        stream_id = request.stream.stream_id
        scope = self._build_http2_scope(request, sockname, peername)

        response_started = False
        response_complete = False
        exc_to_raise = None

        response_status = 500
        response_headers = []
        response_body = b''
        response_trailers = []

        async def receive():
            # For HTTP/2, the body is already buffered in the stream
            body = request.body.read()
            return {
                "type": "http.request",
                "body": body,
                "more_body": False,
            }

        async def send(message):
            nonlocal response_started, response_complete, exc_to_raise
            nonlocal response_status, response_headers, response_body

            msg_type = message["type"]

            if msg_type == "http.response.informational":
                # Handle informational responses (1xx) like 103 Early Hints over HTTP/2
                info_status = message.get("status")
                info_headers = message.get("headers", [])
                # Convert headers to list of string tuples
                headers = []
                for name, value in info_headers:
                    if isinstance(name, bytes):
                        name = name.decode("latin-1")
                    if isinstance(value, bytes):
                        value = value.decode("latin-1")
                    headers.append((name, value))
                await h2_conn.send_informational(stream_id, info_status, headers)
                return

            if msg_type == "http.response.start":
                if response_started:
                    exc_to_raise = RuntimeError("Response already started")
                    return
                response_started = True
                response_status = message["status"]
                response_headers = message.get("headers", [])

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
                    response_body += body

                if not more_body:
                    response_complete = True

            elif msg_type == "http.response.trailers":
                if not response_complete:
                    exc_to_raise = RuntimeError("Cannot send trailers before body complete")
                    return
                trailer_headers = message.get("headers", [])
                # Convert to list of tuples with string values
                trailers = []
                for name, value in trailer_headers:
                    if isinstance(name, bytes):
                        name = name.decode("latin-1")
                    if isinstance(value, bytes):
                        value = value.decode("latin-1")
                    trailers.append((name, value))
                response_trailers.extend(trailers)

        # Build environ for logging
        environ = self._build_http2_environ(request, sockname, peername)
        request_start = datetime.now()

        try:
            self.cfg.pre_request(self.worker, request)
            await self.app(scope, receive, send)

            if exc_to_raise is not None:
                raise exc_to_raise

            # Send response via HTTP/2
            if response_started:
                # Convert headers to list of tuples
                headers = []
                for name, value in response_headers:
                    if isinstance(name, bytes):
                        name = name.decode("latin-1")
                    if isinstance(value, bytes):
                        value = value.decode("latin-1")
                    headers.append((name, value))

                if response_trailers:
                    # Send headers, body, then trailers separately
                    response_hdrs = [(':status', str(response_status))]
                    for name, value in headers:
                        response_hdrs.append((name.lower(), str(value)))

                    # Send headers without ending stream
                    h2_conn.h2_conn.send_headers(stream_id, response_hdrs, end_stream=False)
                    stream = h2_conn.streams[stream_id]
                    stream.send_headers(response_hdrs, end_stream=False)
                    await h2_conn._send_pending_data()

                    # Send body without ending stream
                    if response_body:
                        h2_conn.h2_conn.send_data(stream_id, response_body, end_stream=False)
                        stream.send_data(response_body, end_stream=False)
                        await h2_conn._send_pending_data()

                    # Send trailers (ends stream)
                    await h2_conn.send_trailers(stream_id, response_trailers)
                else:
                    await h2_conn.send_response(
                        stream_id, response_status, headers, response_body
                    )
            else:
                await h2_conn.send_error(stream_id, 500, "Internal Server Error")
                response_status = 500

        except Exception:
            self.log.exception("Error in ASGI application")
            if not response_started:
                await h2_conn.send_error(stream_id, 500, "Internal Server Error")
                response_status = 500
        finally:
            try:
                request_time = datetime.now() - request_start
                resp = ASGIResponseInfo(
                    response_status, response_headers, len(response_body)
                )
                self.log.access(resp, request, environ, request_time)
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
            "raw_path": request.path.encode("latin-1") if request.path else b"",
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
