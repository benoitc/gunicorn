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
CLOSE_MANDATORY_EXT = 1010
CLOSE_INTERNAL_ERROR = 1011

# WebSocket handshake GUID (RFC 6455)
WS_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class WebSocketProtocol:
    """WebSocket connection handler for ASGI applications."""

    def __init__(self, transport, reader, scope, app, log):
        """Initialize WebSocket protocol handler.

        Args:
            transport: asyncio transport for writing
            reader: asyncio StreamReader for reading
            scope: ASGI WebSocket scope dict
            app: ASGI application callable
            log: Logger instance
        """
        self.transport = transport
        self.reader = reader
        self.scope = scope
        self.app = app
        self.log = log

        self.accepted = False
        self.closed = False
        self.close_code = None
        self.close_reason = ""

        # Message reassembly state
        self._fragments = []
        self._fragment_opcode = None

        # Receive queue for incoming messages
        self._receive_queue = asyncio.Queue()

    async def run(self):
        """Run the WebSocket ASGI application."""
        # Send initial connect event
        await self._receive_queue.put({"type": "websocket.connect"})

        # Start frame reading task
        read_task = asyncio.create_task(self._read_frames())

        try:
            await self.app(self.scope, self._receive, self._send)
        except Exception:
            self.log.exception("Error in WebSocket ASGI application")
        finally:
            read_task.cancel()
            try:
                await read_task
            except asyncio.CancelledError:
                pass

            # Send close frame if not already closed
            if not self.closed and self.accepted:
                await self._send_close(CLOSE_INTERNAL_ERROR, "Application error")

    async def _receive(self):
        """ASGI receive callable."""
        return await self._receive_queue.get()

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
                raise RuntimeError("WebSocket closed")

            if "text" in message:
                await self._send_frame(OPCODE_TEXT, message["text"].encode("utf-8"))
            elif "bytes" in message:
                await self._send_frame(OPCODE_BINARY, message["bytes"])

        elif msg_type == "websocket.close":
            code = message.get("code", CLOSE_NORMAL)
            reason = message.get("reason", "")
            await self._send_close(code, reason)
            self.closed = True

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
            headers.append(f"Sec-WebSocket-Protocol: {subprotocol}\r\n")

        # Add any extra headers from message
        extra_headers = message.get("headers", [])
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
            while not self.closed:
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
                    await self._receive_queue.put({
                        "type": "websocket.receive",
                        "text": payload.decode("utf-8"),
                    })
                elif opcode == OPCODE_BINARY:
                    await self._receive_queue.put({
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
            if not self.closed:
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
        elif payload_len == 127:
            ext_len = await self._read_exact(8)
            if not ext_len:
                return None
            payload_len = struct.unpack("!Q", ext_len)[0]

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
            if fin:
                # Reassemble complete message
                full_payload = b"".join(self._fragments)
                final_opcode = self._fragment_opcode
                self._fragments = []
                self._fragment_opcode = None
                return (final_opcode, full_payload)
            return (OPCODE_CONTINUATION, b"")  # Fragment received, wait for more
        elif opcode in (OPCODE_TEXT, OPCODE_BINARY):
            if not fin:
                # Start of fragmented message
                self._fragment_opcode = opcode
                self._fragments = [payload]
                return (OPCODE_CONTINUATION, b"")  # Fragment started, wait for more
            return (opcode, payload)
        else:
            # Control frames
            return (opcode, payload)

    async def _read_exact(self, n):
        """Read exactly n bytes from the reader."""
        try:
            data = await self.reader.readexactly(n)
            return data
        except asyncio.IncompleteReadError:
            return None
        except Exception:
            return None

    def _unmask(self, payload, masking_key):
        """Unmask WebSocket payload data."""
        if not payload:
            return payload
        # XOR each byte with corresponding mask byte
        return bytes(b ^ masking_key[i % 4] for i, b in enumerate(payload))

    async def _handle_close(self, payload):
        """Handle incoming close frame."""
        if len(payload) >= 2:
            self.close_code = struct.unpack("!H", payload[:2])[0]
            self.close_reason = payload[2:].decode("utf-8", errors="replace")
        else:
            self.close_code = CLOSE_NO_STATUS
            self.close_reason = ""

        # Echo close frame back if we haven't already sent one
        if not self.closed:
            await self._send_close(self.close_code, self.close_reason)

        self.closed = True

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
        payload = struct.pack("!H", code)
        if reason:
            payload += reason.encode("utf-8")[:123]  # Max 125 bytes total
        await self._send_frame(OPCODE_CLOSE, payload)
        self.closed = True
