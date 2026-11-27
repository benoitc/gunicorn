#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
WebSocket protocol handler for ASGI.

Implements RFC 6455 WebSocket protocol for ASGI applications.
"""

import asyncio
import base64
import hashlib
import struct

from gunicorn.asgi.protocol import ClientDisconnected, _validate_response_headers


# WebSocket frame opcodes
OPCODE_CONTINUATION = 0x0
OPCODE_TEXT = 0x1
OPCODE_BINARY = 0x2
OPCODE_CLOSE = 0x8
OPCODE_PING = 0x9
OPCODE_PONG = 0xA

# WebSocket close codes
CLOSE_NORMAL = 1000
CLOSE_GOING_AWAY = 1001
CLOSE_PROTOCOL_ERROR = 1002
CLOSE_UNSUPPORTED = 1003
CLOSE_NO_STATUS = 1005
CLOSE_ABNORMAL = 1006
CLOSE_INVALID_DATA = 1007
CLOSE_POLICY_VIOLATION = 1008
CLOSE_MESSAGE_TOO_BIG = 1009

# RFC 6455 section 5.5: control frames carry at most 125 bytes.
MAX_CONTROL_PAYLOAD = 125
# RFC 6455 section 5.2: opcodes 0x3-0x7 and 0xB-0xF are reserved.
KNOWN_OPCODES = frozenset((0x0, 0x1, 0x2, 0x8, 0x9, 0xA))
DEFAULT_MAX_MESSAGE_SIZE = 16 * 1024 * 1024
# Stop reading from the socket once this many bytes wait in the buffer and
# the reader does not need them yet.
READ_BUFFER_HIGH_WATER = 64 * 1024
# Stop reading frames while this many messages wait for the app to receive().
RECEIVE_QUEUE_HIGH_WATER = 32
CLOSE_MANDATORY_EXT = 1010
CLOSE_INTERNAL_ERROR = 1011

# WebSocket handshake GUID (RFC 6455)
WS_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class WebSocketDisconnected(ClientDisconnected, RuntimeError):
    """Raised by send() once the WebSocket is closed.

    ASGI 2.4: a send on a closed connection raises a server-specific
    subclass of OSError. It also stays a RuntimeError, which is what
    gunicorn raised before, so existing ``except RuntimeError`` still match.
    """


def _valid_close_code(code):
    """RFC 6455 section 7.4: codes a peer may send in a close frame."""
    if 1000 <= code <= 1014:
        return code not in (1004, 1005, 1006)
    return 3000 <= code <= 4999


class WebSocketProtocol:
    """WebSocket connection handler for ASGI applications.

    Uses callback-based data feeding instead of StreamReader for efficiency.
    Data is fed via feed_data() from the parent protocol's data_received().
    """

    def __init__(self, transport, scope, app, log,
                 max_message_size=DEFAULT_MAX_MESSAGE_SIZE, drain=None):
        """Initialize WebSocket protocol handler.

        Args:
            transport: asyncio transport for writing
            scope: ASGI WebSocket scope dict
            app: ASGI application callable
            log: Logger instance
            max_message_size: largest message accepted, 0 for no limit
            drain: coroutine function that returns once the transport is
                below its write limit (the connection's FlowControl.drain)
        """
        self.transport = transport
        self.scope = scope
        self.app = app
        self.log = log

        self.accepted = False
        self.closed = False
        # Set once an HTTP response refused the handshake.
        self._denied = False
        self.close_code = None
        self.close_reason = ""

        # Close handshake state (RFC 6455 Section 7.1.1)
        self._close_sent = False
        self._close_received = False
        self._close_event = asyncio.Event()

        # Message reassembly state
        self._fragments = []
        self._fragment_opcode = None
        self._fragments_size = 0
        self.max_message_size = max_message_size
        self._drain = drain

        # Backpressure: pause the transport while bytes pile up unread, and
        # stop reading frames while messages wait for the app.
        self._reading_paused = False
        self._wanted = 0
        self._queue_space = asyncio.Event()
        self._queue_space.set()

        # Receive queue for incoming messages
        self._receive_queue = asyncio.Queue()

        # Callback-based data reception (replaces StreamReader)
        self._buffer = bytearray()
        self._data_event = asyncio.Event()
        self._eof = False

    def feed_data(self, data):
        """Feed incoming data from the parent protocol's data_received().

        Args:
            data: bytes received on the connection
        """
        if data:
            self._buffer.extend(data)
            self._data_event.set()
            if (not self._reading_paused
                    and len(self._buffer) > max(READ_BUFFER_HIGH_WATER, self._wanted)):
                self._pause_reading()

    def _pause_reading(self):
        try:
            self.transport.pause_reading()
            self._reading_paused = True
        except (AttributeError, RuntimeError):
            pass

    def _resume_reading(self):
        if self._reading_paused:
            self._reading_paused = False
            try:
                self.transport.resume_reading()
            except (AttributeError, RuntimeError):
                pass

    def feed_eof(self):
        """Signal that the connection has been closed."""
        self._eof = True
        self._data_event.set()

    async def run(self):
        """Run the WebSocket ASGI application."""
        # Send initial connect event
        await self._receive_queue.put({"type": "websocket.connect"})

        # Start frame reading task
        read_task = asyncio.create_task(self._read_frames())

        failed = False
        try:
            await self.app(self.scope, self._receive, self._send)
        except WebSocketDisconnected:
            # The client went away; ASGI asks servers not to log this.
            self.log.debug("WebSocket closed while the application was sending")
        except Exception:
            failed = True
            self.log.exception("Error in WebSocket ASGI application")
        finally:
            # The app ended without accepting: the handshake is refused with
            # an HTTP response (403, or 500 when the app raised).
            if not self.accepted and not self._denied:
                if failed:
                    self._deny(500, "Internal Server Error")
                else:
                    self._deny(403, "Forbidden")

            # Send close frame if not already closed
            if not self.closed and self.accepted and not self._close_sent:
                await self._send_close(CLOSE_INTERNAL_ERROR, "Application error")
                # Wait for client's close response
                try:
                    await asyncio.wait_for(self._close_event.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    self.closed = True

            read_task.cancel()
            try:
                await read_task
            except asyncio.CancelledError:
                pass

    def _deny(self, status, reason):
        """Refuse the handshake with an HTTP response and close."""
        if self._denied:
            return
        self._denied = True
        self.closed = True
        self._close_event.set()
        try:
            self.transport.write(
                b"HTTP/1.1 %d %s\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                % (status, reason.encode("latin-1")))
            self.transport.close()
        except (OSError, RuntimeError):
            pass

    async def _receive(self):
        """ASGI receive callable."""
        message = await self._receive_queue.get()
        if self._receive_queue.qsize() < RECEIVE_QUEUE_HIGH_WATER:
            self._queue_space.set()
        return message

    async def _put_message(self, message):
        """Queue a message for the app, waiting while too many are unread."""
        # Once our close frame is out the read loop must keep going to see the
        # client's reply, so it stops waiting for the app, and the app gets no
        # more data.
        while (self._receive_queue.qsize() >= RECEIVE_QUEUE_HIGH_WATER
               and not self._close_sent):
            self._queue_space.clear()
            await self._queue_space.wait()
        if self._close_sent:
            return
        await self._receive_queue.put(message)

    async def _send(self, message):
        """ASGI send callable."""
        msg_type = message["type"]

        if msg_type == "websocket.accept":
            if self.accepted:
                raise RuntimeError("WebSocket already accepted")
            await self._send_accept(message)
            self.accepted = True

        elif msg_type == "websocket.send":
            if not self.accepted:
                raise RuntimeError("WebSocket not accepted")
            if self.closed:
                raise WebSocketDisconnected("WebSocket closed")

            # Check for truthy values since both keys may be present with None
            text = message.get("text")
            bytes_data = message.get("bytes")
            # Wait while the client is not reading, as HTTP responses do, so
            # a slow client cannot grow the write buffer without end.
            if self._drain is not None:
                await self._drain()
                if self.closed:
                    raise WebSocketDisconnected("WebSocket closed")
            if text is not None:
                await self._send_frame(OPCODE_TEXT, text.encode("utf-8"))
            elif bytes_data is not None:
                await self._send_frame(OPCODE_BINARY, bytes_data)

        elif msg_type == "websocket.close":
            if not self.accepted:
                # ASGI: closing before accept refuses the handshake with an
                # HTTP 403; no WebSocket frame goes on the wire.
                self._deny(403, "Forbidden")
                return
            code = message.get("code", CLOSE_NORMAL)
            reason = message.get("reason", "")
            await self._send_close(code, reason)

            # Wait for client's close frame (RFC 6455 close handshake)
            try:
                await asyncio.wait_for(self._close_event.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.log.debug("WebSocket close handshake timeout")
                self.closed = True
                self._close_event.set()

            # Close the transport after close handshake
            self.transport.close()

    async def _send_accept(self, message):
        """Send WebSocket handshake accept response."""
        # Get Sec-WebSocket-Key from headers
        ws_key = None
        for name, value in self.scope["headers"]:
            if name == b"sec-websocket-key":
                ws_key = value
                break

        if not ws_key:
            raise RuntimeError("Missing Sec-WebSocket-Key header")

        # Calculate accept key
        accept_key = base64.b64encode(
            hashlib.sha1(ws_key + WS_GUID).digest()
        ).decode("ascii")

        # Build response headers
        headers = [
            "HTTP/1.1 101 Switching Protocols\r\n",
            "Upgrade: websocket\r\n",
            "Connection: Upgrade\r\n",
            f"Sec-WebSocket-Accept: {accept_key}\r\n",
        ]

        # Add selected subprotocol if specified
        subprotocol = message.get("subprotocol")
        if subprotocol:
            _validate_response_headers([("Sec-WebSocket-Protocol", subprotocol)])
            headers.append(f"Sec-WebSocket-Protocol: {subprotocol}\r\n")

        # Add any extra headers from message
        extra_headers = message.get("headers", [])
        _validate_response_headers(extra_headers)
        for name, value in extra_headers:
            if isinstance(name, bytes):
                name = name.decode("latin-1")
            if isinstance(value, bytes):
                value = value.decode("latin-1")
            headers.append(f"{name}: {value}\r\n")

        headers.append("\r\n")
        self.transport.write("".join(headers).encode("latin-1"))

    async def _read_frames(self):
        """Read and process incoming WebSocket frames."""
        try:
            # Continue reading while not closed, or if we sent close but haven't
            # received client's close response yet (RFC 6455 close handshake)
            while not self.closed or (self._close_sent and not self._close_received):
                frame = await self._read_frame()
                if frame is None:
                    break

                opcode, payload = frame

                if opcode == OPCODE_CLOSE:
                    await self._handle_close(payload)
                    break

                if opcode == OPCODE_PING:
                    await self._send_frame(OPCODE_PONG, payload)
                elif opcode == OPCODE_PONG:
                    # Ignore pongs
                    pass
                elif opcode == OPCODE_TEXT:
                    try:
                        text = payload.decode("utf-8")
                    except UnicodeDecodeError:
                        # RFC 6455 section 8.1: invalid UTF-8 fails the
                        # connection with 1007.
                        await self._send_close(CLOSE_INVALID_DATA, "Invalid UTF-8")
                        break
                    await self._put_message({
                        "type": "websocket.receive",
                        "text": text,
                    })
                elif opcode == OPCODE_BINARY:
                    await self._put_message({
                        "type": "websocket.receive",
                        "bytes": payload,
                    })
                elif opcode == OPCODE_CONTINUATION:
                    # Handle fragmented messages
                    await self._handle_continuation(payload)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.log.debug("WebSocket read error: %s", e)
        finally:
            # Signal disconnect
            self.closed = True
            await self._receive_queue.put({
                "type": "websocket.disconnect",
                "code": self.close_code or CLOSE_ABNORMAL,
            })

    async def _read_frame(self):  # pylint: disable=too-many-return-statements
        """Read a single WebSocket frame.

        Returns:
            tuple: (opcode, payload) or None if connection closed
        """
        # Read frame header (2 bytes minimum)
        header = await self._read_exact(2)
        if not header:
            return None

        first_byte, second_byte = header[0], header[1]

        fin = (first_byte >> 7) & 1
        rsv1 = (first_byte >> 6) & 1
        rsv2 = (first_byte >> 5) & 1
        rsv3 = (first_byte >> 4) & 1
        opcode = first_byte & 0x0F

        # RSV bits must be 0 (no extensions)
        if rsv1 or rsv2 or rsv3:
            await self._send_close(CLOSE_PROTOCOL_ERROR, "RSV bits set")
            return None

        # RFC 6455 section 5.2: a reserved opcode fails the connection.
        if opcode not in KNOWN_OPCODES:
            await self._send_close(CLOSE_PROTOCOL_ERROR, "Reserved opcode")
            return None

        masked = (second_byte >> 7) & 1
        payload_len = second_byte & 0x7F

        # Client frames must be masked (RFC 6455)
        if not masked:
            await self._send_close(CLOSE_PROTOCOL_ERROR, "Frame not masked")
            return None

        # Extended payload length
        if payload_len == 126:
            ext_len = await self._read_exact(2)
            if not ext_len:
                return None
            payload_len = struct.unpack("!H", ext_len)[0]
            # RFC 6455 section 5.2: the minimal number of bytes MUST be used.
            if payload_len < 126:
                await self._send_close(CLOSE_PROTOCOL_ERROR, "Non-minimal length")
                return None
        elif payload_len == 127:
            ext_len = await self._read_exact(8)
            if not ext_len:
                return None
            payload_len = struct.unpack("!Q", ext_len)[0]
            # Minimal encoding, and the most significant bit MUST be 0.
            if payload_len < 65536 or payload_len >> 63:
                await self._send_close(CLOSE_PROTOCOL_ERROR, "Invalid length")
                return None

        # RFC 6455 section 5.4: a new text or binary frame cannot start while
        # a fragmented message is unfinished.
        if opcode in (OPCODE_TEXT, OPCODE_BINARY) and self._fragment_opcode is not None:
            await self._send_close(CLOSE_PROTOCOL_ERROR, "Expected continuation")
            return None

        # RFC 6455 section 5.5: control frames are not fragmented and carry at
        # most 125 bytes.
        if opcode >= 0x8 and (not fin or payload_len > MAX_CONTROL_PAYLOAD):
            await self._send_close(CLOSE_PROTOCOL_ERROR, "Invalid control frame")
            return None

        # Refuse a message larger than the limit before reading it (RFC 6455
        # section 7.4.1, 1009).
        if opcode < 0x8 and self.max_message_size:
            total = payload_len + (self._fragments_size if opcode == OPCODE_CONTINUATION else 0)
            if total > self.max_message_size:
                await self._send_close(CLOSE_MESSAGE_TOO_BIG, "Message too big")
                return None

        # Read masking key
        masking_key = await self._read_exact(4)
        if not masking_key:
            return None

        # Read payload
        payload = await self._read_exact(payload_len)
        if payload is None:
            return None

        # Unmask payload
        payload = self._unmask(payload, masking_key)

        # Handle fragmented messages
        if opcode == OPCODE_CONTINUATION:
            if self._fragment_opcode is None:
                await self._send_close(CLOSE_PROTOCOL_ERROR, "Unexpected continuation")
                return None
            self._fragments.append(payload)
            self._fragments_size += len(payload)
            if fin:
                # Reassemble complete message
                full_payload = b"".join(self._fragments)
                final_opcode = self._fragment_opcode
                self._fragments = []
                self._fragments_size = 0
                self._fragment_opcode = None
                return (final_opcode, full_payload)
            return (OPCODE_CONTINUATION, b"")  # Fragment received, wait for more
        elif opcode in (OPCODE_TEXT, OPCODE_BINARY):
            if not fin:
                # Start of fragmented message
                self._fragment_opcode = opcode
                self._fragments = [payload]
                self._fragments_size = len(payload)
                return (OPCODE_CONTINUATION, b"")  # Fragment started, wait for more
            return (opcode, payload)
        else:
            # Control frames
            return (opcode, payload)

    async def _read_exact(self, n):
        """Read exactly n bytes from internal buffer.

        Waits for data via the callback-fed buffer instead of StreamReader.
        """
        self._wanted = n
        while len(self._buffer) < n:
            if self._eof:
                return None
            # The reader needs these bytes: never wait with reading paused.
            self._resume_reading()
            self._data_event.clear()
            # Critical: check buffer AGAIN after clearing to avoid race
            # condition where data arrives between clear() and wait()
            if len(self._buffer) >= n:
                break
            await self._data_event.wait()
            if self._eof and len(self._buffer) < n:
                return None

        data = bytes(self._buffer[:n])
        del self._buffer[:n]
        self._wanted = 0
        if self._reading_paused and len(self._buffer) <= READ_BUFFER_HIGH_WATER:
            self._resume_reading()
        return data

    def _unmask(self, payload, masking_key):
        """Unmask WebSocket payload data."""
        if not payload:
            return payload
        # XOR each byte with corresponding mask byte
        return bytes(b ^ masking_key[i % 4] for i, b in enumerate(payload))

    async def _handle_close(self, payload):
        """Handle incoming close frame.

        RFC 6455 section 5.5.1: the body is empty, or a 2-byte code and a
        UTF-8 reason. A malformed body is answered with 1002 (or 1007 for a
        reason that is not UTF-8) instead of echoing it.
        """
        reply = None
        if len(payload) >= 2:
            self.close_code = struct.unpack("!H", payload[:2])[0]
            try:
                self.close_reason = payload[2:].decode("utf-8")
            except UnicodeDecodeError:
                self.close_reason = ""
                reply = (CLOSE_INVALID_DATA, "Invalid UTF-8")
            if not _valid_close_code(self.close_code):
                reply = (CLOSE_PROTOCOL_ERROR, "Invalid close code")
        elif len(payload) == 1:
            self.close_code = CLOSE_PROTOCOL_ERROR
            self.close_reason = ""
            reply = (CLOSE_PROTOCOL_ERROR, "Invalid close payload")
        else:
            self.close_code = CLOSE_NO_STATUS
            self.close_reason = ""

        self._close_received = True

        # Echo close frame back if we haven't already sent one
        if not self._close_sent:
            if reply is not None:
                await self._send_close(*reply)
            elif self.close_code == CLOSE_NO_STATUS:
                # 1005 must not be sent on the wire: reply with no code.
                await self._send_close(CLOSE_NORMAL)
            else:
                await self._send_close(self.close_code, self.close_reason)

        self.closed = True
        self._close_event.set()

    async def _handle_continuation(self, payload):  # pylint: disable=unused-argument
        """Handle continuation frame (already processed in _read_frame)."""
        # This is called for partial fragments, nothing to do here

    async def _send_frame(self, opcode, payload):
        """Send a WebSocket frame.

        Server frames are not masked (RFC 6455).
        """
        if isinstance(payload, str):
            payload = payload.encode("utf-8")

        length = len(payload)
        frame = bytearray()

        # First byte: FIN + opcode
        frame.append(0x80 | opcode)

        # Second byte: length (no mask bit for server)
        if length < 126:
            frame.append(length)
        elif length < 65536:
            frame.append(126)
            frame.extend(struct.pack("!H", length))
        else:
            frame.append(127)
            frame.extend(struct.pack("!Q", length))

        # Payload
        frame.extend(payload)

        self.transport.write(bytes(frame))

    async def _send_close(self, code, reason=""):
        """Send a close frame."""
        if self._close_sent:
            return  # Already sent

        payload = struct.pack("!H", code)
        if reason:
            payload += reason.encode("utf-8")[:123]  # Max 125 bytes total
        await self._send_frame(OPCODE_CLOSE, payload)
        self._close_sent = True
        self._queue_space.set()

        # If we already received a close, handshake is complete
        if self._close_received:
            self.closed = True
            self._close_event.set()
