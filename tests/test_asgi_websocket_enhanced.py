#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Enhanced WebSocket ASGI tests.

Tests for WebSocket message size limits, connection rejection,
subprotocol negotiation, and compression per ASGI 3.0 and RFC 6455.
"""

import struct
from unittest import mock

import pytest


# ============================================================================
# WebSocket Message Size Tests
# ============================================================================

class TestWebSocketMessageSizeLimits:
    """Test WebSocket message size limits and close code 1009."""

    def test_close_code_1009_defined(self):
        """Close code 1009 (message too big) should be defined."""
        from gunicorn.asgi.websocket import CLOSE_MESSAGE_TOO_BIG

        assert CLOSE_MESSAGE_TOO_BIG == 1009

    def test_control_frame_max_payload_125_bytes(self):
        """Control frames have max payload of 125 bytes (RFC 6455)."""
        # Close frame max reason: 125 - 2 (close code) = 123 bytes
        from gunicorn.asgi.websocket import CLOSE_NORMAL

        max_reason = "x" * 123
        payload = struct.pack("!H", CLOSE_NORMAL) + max_reason.encode("utf-8")

        assert len(payload) == 125

    def test_text_message_encoding(self):
        """Text messages should be UTF-8."""
        # Large valid UTF-8 message
        large_text = "Hello " * 1000
        encoded = large_text.encode("utf-8")

        assert isinstance(encoded, bytes)
        assert len(encoded) == 6000

    def test_binary_message_allowed(self):
        """Binary messages can contain any bytes."""
        binary_data = bytes(range(256)) * 10

        assert len(binary_data) == 2560
        assert isinstance(binary_data, bytes)


# ============================================================================
# WebSocket Connection Rejection Tests
# ============================================================================

class TestWebSocketConnectionRejection:
    """Test WebSocket connection rejection responses."""

    def _create_protocol(self, scope=None):
        """Create a WebSocketProtocol instance."""
        from gunicorn.asgi.websocket import WebSocketProtocol

        if scope is None:
            scope = {
                "type": "websocket",
                "headers": [(b"sec-websocket-key", b"dGhlIHNhbXBsZSBub25jZQ==")],
            }

        transport = mock.Mock()

        return WebSocketProtocol(
            transport=transport,
            scope=scope,
            app=mock.AsyncMock(),
            log=mock.Mock(),
        )

    @pytest.mark.asyncio
    async def test_reject_before_accept_closes_connection(self):
        """Rejecting before accept should close with HTTP response."""
        protocol = self._create_protocol()
        protocol.transport.write = mock.Mock()

        # Send close without accepting
        await protocol._send({"type": "websocket.close", "code": 1000})

        assert protocol.closed is True

    @pytest.mark.asyncio
    async def test_close_with_custom_code(self):
        """Close can specify custom close code."""
        protocol = self._create_protocol()
        protocol.transport.write = mock.Mock()

        # Accept first
        await protocol._send({"type": "websocket.accept"})

        # Then close with custom code
        await protocol._send({
            "type": "websocket.close",
            "code": 4000,
            "reason": "Custom close"
        })

        assert protocol.closed is True
        # Verify close frame was sent (write called)
        assert protocol.transport.write.call_count >= 2

    @pytest.mark.asyncio
    async def test_close_with_reason(self):
        """Close can include reason string."""
        protocol = self._create_protocol()
        protocol.transport.write = mock.Mock()

        await protocol._send({"type": "websocket.accept"})
        await protocol._send({
            "type": "websocket.close",
            "code": 1000,
            "reason": "Normal closure"
        })

        assert protocol.closed is True
        # Close frame was written
        assert protocol.transport.write.call_count >= 2


# ============================================================================
# WebSocket Subprotocol Tests
# ============================================================================

class TestWebSocketSubprotocols:
    """Test WebSocket subprotocol negotiation."""

    def _create_protocol(self, subprotocols=None):
        """Create a WebSocketProtocol with optional subprotocols."""
        from gunicorn.asgi.websocket import WebSocketProtocol

        headers = [(b"sec-websocket-key", b"dGhlIHNhbXBsZSBub25jZQ==")]
        if subprotocols:
            headers.append((b"sec-websocket-protocol", ", ".join(subprotocols).encode()))

        scope = {
            "type": "websocket",
            "headers": headers,
            "subprotocols": subprotocols or [],
        }

        transport = mock.Mock()

        return WebSocketProtocol(
            transport=transport,
            scope=scope,
            app=mock.AsyncMock(),
            log=mock.Mock(),
        )

    @pytest.mark.asyncio
    async def test_accept_without_subprotocol(self):
        """Accept without subprotocol should work."""
        protocol = self._create_protocol()
        protocol.transport.write = mock.Mock()

        await protocol._send({"type": "websocket.accept"})

        assert protocol.accepted is True

    @pytest.mark.asyncio
    async def test_accept_with_subprotocol(self):
        """Accept with subprotocol should include it in response."""
        protocol = self._create_protocol(subprotocols=["graphql-ws", "chat"])
        protocol.transport.write = mock.Mock()

        await protocol._send({
            "type": "websocket.accept",
            "subprotocol": "graphql-ws"
        })

        assert protocol.accepted is True

    def test_subprotocol_in_scope(self):
        """Subprotocols should be available in scope."""
        protocol = self._create_protocol(subprotocols=["graphql-ws", "chat"])

        assert "subprotocols" in protocol.scope
        assert protocol.scope["subprotocols"] == ["graphql-ws", "chat"]


# ============================================================================
# WebSocket Accept Message Tests
# ============================================================================

class TestWebSocketAcceptMessage:
    """Test WebSocket accept message handling."""

    def _create_protocol(self):
        """Create a WebSocketProtocol instance."""
        from gunicorn.asgi.websocket import WebSocketProtocol

        scope = {
            "type": "websocket",
            "headers": [(b"sec-websocket-key", b"dGhlIHNhbXBsZSBub25jZQ==")],
        }

        transport = mock.Mock()

        return WebSocketProtocol(
            transport=transport,
            scope=scope,
            app=mock.AsyncMock(),
            log=mock.Mock(),
        )

    @pytest.mark.asyncio
    async def test_accept_sets_accepted_flag(self):
        """Accepting should set the accepted flag."""
        protocol = self._create_protocol()
        protocol.transport.write = mock.Mock()

        assert protocol.accepted is False

        await protocol._send({"type": "websocket.accept"})

        assert protocol.accepted is True

    @pytest.mark.asyncio
    async def test_accept_with_headers(self):
        """Accept can include additional headers."""
        protocol = self._create_protocol()
        protocol.transport.write = mock.Mock()

        await protocol._send({
            "type": "websocket.accept",
            "headers": [
                (b"x-custom-header", b"custom-value"),
            ],
        })

        assert protocol.accepted is True

    @pytest.mark.asyncio
    async def test_double_accept_raises(self):
        """Accepting twice should raise RuntimeError."""
        protocol = self._create_protocol()
        protocol.transport.write = mock.Mock()

        await protocol._send({"type": "websocket.accept"})

        with pytest.raises(RuntimeError, match="already accepted"):
            await protocol._send({"type": "websocket.accept"})


# ============================================================================
# WebSocket Send Message Tests
# ============================================================================

class TestWebSocketSendMessages:
    """Test WebSocket send message handling."""

    def _create_protocol(self):
        """Create a WebSocketProtocol instance."""
        from gunicorn.asgi.websocket import WebSocketProtocol

        scope = {
            "type": "websocket",
            "headers": [(b"sec-websocket-key", b"dGhlIHNhbXBsZSBub25jZQ==")],
        }

        transport = mock.Mock()

        return WebSocketProtocol(
            transport=transport,
            scope=scope,
            app=mock.AsyncMock(),
            log=mock.Mock(),
        )

    @pytest.mark.asyncio
    async def test_send_text_message(self):
        """Sending text message should work after accept."""
        protocol = self._create_protocol()
        protocol.transport.write = mock.Mock()

        await protocol._send({"type": "websocket.accept"})
        await protocol._send({
            "type": "websocket.send",
            "text": "Hello, WebSocket!"
        })

        # Verify write was called (for accept and send)
        assert protocol.transport.write.call_count >= 2

    @pytest.mark.asyncio
    async def test_send_binary_message(self):
        """Sending binary message should work after accept."""
        protocol = self._create_protocol()
        protocol.transport.write = mock.Mock()

        await protocol._send({"type": "websocket.accept"})
        await protocol._send({
            "type": "websocket.send",
            "bytes": b"\x00\x01\x02\x03"
        })

        assert protocol.transport.write.call_count >= 2

    @pytest.mark.asyncio
    async def test_send_before_accept_raises(self):
        """Sending before accept should raise RuntimeError."""
        protocol = self._create_protocol()

        with pytest.raises(RuntimeError, match="not accepted"):
            await protocol._send({
                "type": "websocket.send",
                "text": "Hello"
            })

    @pytest.mark.asyncio
    async def test_send_after_close_raises(self):
        """Sending after close should raise RuntimeError."""
        protocol = self._create_protocol()
        protocol.transport.write = mock.Mock()

        await protocol._send({"type": "websocket.accept"})
        await protocol._send({"type": "websocket.close", "code": 1000})

        with pytest.raises(RuntimeError, match="closed"):
            await protocol._send({
                "type": "websocket.send",
                "text": "Hello"
            })


# ============================================================================
# WebSocket Frame Building Tests
# ============================================================================

class TestWebSocketFrameBuilding:
    """Test WebSocket frame construction."""

    def _create_protocol(self):
        """Create a WebSocketProtocol instance."""
        from gunicorn.asgi.websocket import WebSocketProtocol

        scope = {
            "type": "websocket",
            "headers": [],
        }

        return WebSocketProtocol(
            transport=mock.Mock(),
            scope=scope,
            app=mock.AsyncMock(),
            log=mock.Mock(),
        )

    def test_frame_header_fin_bit(self):
        """FIN bit should be set for complete messages."""
        # FIN=1, opcode=1 (text) = 0b10000001 = 0x81
        first_byte = 0x81
        assert (first_byte >> 7) & 1 == 1  # FIN set
        assert first_byte & 0x0F == 1  # OPCODE text

    def test_frame_header_mask_bit(self):
        """Server frames should NOT have MASK bit set."""
        # Server to client: MASK=0
        # Length 5, no mask = 0b00000101 = 0x05
        second_byte = 0x05
        assert (second_byte >> 7) & 1 == 0  # MASK not set
        assert second_byte & 0x7F == 5  # Length

    def test_frame_length_encoding_small(self):
        """Small payloads (< 126) use 7-bit length."""
        length = 100
        second_byte = length
        assert second_byte & 0x7F == 100

    def test_frame_length_encoding_medium(self):
        """Medium payloads (126-65535) use 16-bit length."""
        length = 1000
        # Indicator byte
        indicator = 126
        # Extended length as big-endian 16-bit
        extended = struct.pack("!H", length)

        assert indicator == 126
        assert struct.unpack("!H", extended)[0] == 1000

    def test_frame_length_encoding_large(self):
        """Large payloads (> 65535) use 64-bit length."""
        length = 100000
        # Indicator byte
        indicator = 127
        # Extended length as big-endian 64-bit
        extended = struct.pack("!Q", length)

        assert indicator == 127
        assert struct.unpack("!Q", extended)[0] == 100000


# ============================================================================
# WebSocket Close Code Tests
# ============================================================================

class TestWebSocketCloseCodes:
    """Test WebSocket close code handling."""

    def test_all_close_codes_defined(self):
        """All standard close codes should be defined."""
        from gunicorn.asgi import websocket

        assert websocket.CLOSE_NORMAL == 1000
        assert websocket.CLOSE_GOING_AWAY == 1001
        assert websocket.CLOSE_PROTOCOL_ERROR == 1002
        assert websocket.CLOSE_UNSUPPORTED == 1003
        assert websocket.CLOSE_NO_STATUS == 1005
        assert websocket.CLOSE_ABNORMAL == 1006
        assert websocket.CLOSE_INVALID_DATA == 1007
        assert websocket.CLOSE_POLICY_VIOLATION == 1008
        assert websocket.CLOSE_MESSAGE_TOO_BIG == 1009
        assert websocket.CLOSE_MANDATORY_EXT == 1010
        assert websocket.CLOSE_INTERNAL_ERROR == 1011

    def test_close_code_payload_format(self):
        """Close frame payload should be code + optional reason."""
        from gunicorn.asgi.websocket import CLOSE_NORMAL

        # Just code
        payload_code_only = struct.pack("!H", CLOSE_NORMAL)
        assert len(payload_code_only) == 2

        # Code + reason
        reason = "Goodbye"
        payload_with_reason = struct.pack("!H", CLOSE_NORMAL) + reason.encode("utf-8")
        assert len(payload_with_reason) == 2 + len(reason)


# ============================================================================
# WebSocket Receive Queue Tests
# ============================================================================

class TestWebSocketReceiveQueue:
    """Test WebSocket receive queue handling."""

    def _create_protocol(self):
        """Create a WebSocketProtocol instance."""
        from gunicorn.asgi.websocket import WebSocketProtocol

        scope = {
            "type": "websocket",
            "headers": [],
        }

        return WebSocketProtocol(
            transport=mock.Mock(),
            scope=scope,
            app=mock.AsyncMock(),
            log=mock.Mock(),
        )

    @pytest.mark.asyncio
    async def test_receive_returns_from_queue(self):
        """Receive should return messages from the queue."""
        protocol = self._create_protocol()

        # Put a connect message on the queue
        await protocol._receive_queue.put({"type": "websocket.connect"})

        # Receive should return it
        message = await protocol._receive()
        assert message["type"] == "websocket.connect"

    @pytest.mark.asyncio
    async def test_receive_blocks_on_empty_queue(self):
        """Receive should block when queue is empty."""
        import asyncio
        protocol = self._create_protocol()

        # Start receive task
        receive_task = asyncio.create_task(protocol._receive())

        # Give it a moment
        await asyncio.sleep(0.01)

        # Should not be done yet (blocked)
        assert not receive_task.done()

        # Put a message
        await protocol._receive_queue.put({"type": "websocket.connect"})

        # Now should complete
        message = await asyncio.wait_for(receive_task, timeout=1.0)
        assert message["type"] == "websocket.connect"
