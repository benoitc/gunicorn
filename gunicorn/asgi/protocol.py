#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
ASGI protocol handler for gunicorn.

Implements asyncio.Protocol to handle HTTP/1.x connections and dispatch
to ASGI applications.
"""

import asyncio
from datetime import datetime

from gunicorn.asgi.unreader import AsyncUnreader
from gunicorn.asgi.message import AsyncRequest
from gunicorn.http.errors import NoMoreData


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

    def connection_made(self, transport):
        """Called when a connection is established."""
        self.transport = transport
        self.worker.nr_conns += 1

        # Create stream reader/writer
        self.reader = asyncio.StreamReader()
        self.writer = transport

        # Start handling requests
        self._task = self.worker.loop.create_task(self._handle_connection())

    def data_received(self, data):
        """Called when data is received on the connection."""
        if self.reader:
            self.reader.feed_data(data)

    def connection_lost(self, exc):
        """Called when the connection is lost or closed."""
        self._closed = True
        self.worker.nr_conns -= 1
        if self.reader:
            self.reader.feed_eof()
        if self._task and not self._task.done():
            self._task.cancel()

    async def _handle_connection(self):
        """Main request handling loop for this connection."""
        unreader = AsyncUnreader(self.reader)

        try:
            peername = self.transport.get_extra_info('peername')
            sockname = self.transport.get_extra_info('sockname')

            while not self._closed:
                self.req_count += 1

                try:
                    # Parse HTTP request
                    request = await AsyncRequest.parse(
                        self.cfg,
                        unreader,
                        peername,
                        self.req_count
                    )
                except StopIteration:
                    # No more data, close connection
                    break
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

        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.log.exception("Error handling connection: %s", e)
        finally:
            self._close_transport()

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

        # Response tracking for access logging
        response_status = 500
        response_headers = []
        response_sent = 0

        # Receive queue for body
        receive_queue = asyncio.Queue()

        # Pre-populate with initial body state
        if request.content_length == 0 and not request.chunked:
            await receive_queue.put({
                "type": "http.request",
                "body": b"",
                "more_body": False,
            })
        else:
            # Start body reading task
            asyncio.create_task(self._read_body_to_queue(request, receive_queue))

        async def receive():
            return await receive_queue.get()

        async def send(message):
            nonlocal response_started, response_complete, exc_to_raise
            nonlocal response_status, response_headers, response_sent

            msg_type = message["type"]

            if msg_type == "http.response.start":
                if response_started:
                    exc_to_raise = RuntimeError("Response already started")
                    return
                response_started = True
                response_status = message["status"]
                response_headers = message.get("headers", [])
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
                    await self._send_body(body)
                    response_sent += len(body)

                if not more_body:
                    response_complete = True

        # Build environ for logging
        environ = self._build_environ(request, sockname, peername)
        resp = None

        try:
            request_start = datetime.now()
            self.cfg.pre_request(self.worker, request)

            await self.app(scope, receive, send)

            if exc_to_raise is not None:
                raise exc_to_raise

            # Ensure response was sent
            if not response_started:
                await self._send_error_response(500, "Internal Server Error")
                response_status = 500

        except Exception:
            self.log.exception("Error in ASGI application")
            if not response_started:
                await self._send_error_response(500, "Internal Server Error")
                response_status = 500
            return False
        finally:
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

    async def _read_body_to_queue(self, request, queue):
        """Read request body and put chunks on the queue."""
        try:
            while True:
                chunk = await request.read_body(65536)
                if chunk:
                    await queue.put({
                        "type": "http.request",
                        "body": chunk,
                        "more_body": True,
                    })
                else:
                    await queue.put({
                        "type": "http.request",
                        "body": b"",
                        "more_body": False,
                    })
                    break
        except Exception as e:
            self.log.debug("Error reading body: %s", e)
            await queue.put({
                "type": "http.request",
                "body": b"",
                "more_body": False,
            })

    def _build_http_scope(self, request, sockname, peername):
        """Build ASGI HTTP scope from parsed request."""
        # Build headers list as bytes tuples
        headers = []
        for name, value in request.headers:
            headers.append((name.lower().encode("latin-1"), value.encode("latin-1")))

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
            "server": sockname if sockname else None,
            "client": peername if peername else None,
        }

        # Add state dict for lifespan sharing
        if hasattr(self.worker, 'state'):
            scope["state"] = self.worker.state

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
            "server": sockname if sockname else None,
            "client": peername if peername else None,
            "subprotocols": subprotocols,
        }

        # Add state dict for lifespan sharing
        if hasattr(self.worker, 'state'):
            scope["state"] = self.worker.state

        return scope

    async def _send_response_start(self, status, headers, request):
        """Send HTTP response status and headers."""
        # Build status line
        reason = self._get_reason_phrase(status)
        status_line = f"HTTP/{request.version[0]}.{request.version[1]} {status} {reason}\r\n"

        # Build headers
        header_lines = []

        for name, value in headers:
            if isinstance(name, bytes):
                name = name.decode("latin-1")
            if isinstance(value, bytes):
                value = value.decode("latin-1")
            header_lines.append(f"{name}: {value}\r\n")

        # Add server header if not present
        header_lines.append("Server: gunicorn/asgi\r\n")

        response = status_line + "".join(header_lines) + "\r\n"
        self.transport.write(response.encode("latin-1"))

    async def _send_body(self, body):
        """Send response body chunk."""
        if body:
            self.transport.write(body)

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
        self.transport.write(response.encode("latin-1"))
        self.transport.write(body)

    def _get_reason_phrase(self, status):
        """Get HTTP reason phrase for status code."""
        reasons = {
            100: "Continue",
            101: "Switching Protocols",
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
        """Close the transport safely."""
        if self.transport and not self._closed:
            try:
                self.transport.close()
            except Exception:
                pass
            self._closed = True
