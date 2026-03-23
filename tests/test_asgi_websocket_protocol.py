#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
WebSocket RFC 6455 compliance tests.

Tests that gunicorn's WebSocket implementation conforms to RFC 6455:
https://tools.ietf.org/html/rfc6455
"""

import base64
import hashlib
import struct
from unittest import mock

import pytest


# ============================================================================
# WebSocket Constants Tests
# ============================================================================

class TestWebSocketConstants:
    """Tests for WebSocket protocol constants."""

    def test_websocket_guid(self):
        """Test WebSocket GUID per RFC 6455 Section 1.3."""
        from gunicorn.asgi.websocket import WS_GUID

        # The GUID is a fixed value specified in RFC 6455
        assert WS_GUID == b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def test_opcode_continuation(self):
        """Test continuation frame opcode (0x0)."""
        from gunicorn.asgi.websocket import OPCODE_CONTINUATION
        assert OPCODE_CONTINUATION == 0x0

    def test_opcode_text(self):
        """Test text frame opcode (0x1)."""
        from gunicorn.asgi.websocket import OPCODE_TEXT
        assert OPCODE_TEXT == 0x1

    def test_opcode_binary(self):
        """Test binary frame opcode (0x2)."""
        from gunicorn.asgi.websocket import OPCODE_BINARY
        assert OPCODE_BINARY == 0x2

    def test_opcode_close(self):
        """Test close frame opcode (0x8)."""
        from gunicorn.asgi.websocket import OPCODE_CLOSE
        assert OPCODE_CLOSE == 0x8

    def test_opcode_ping(self):
        """Test ping frame opcode (0x9)."""
        from gunicorn.asgi.websocket import OPCODE_PING
        assert OPCODE_PING == 0x9

    def test_opcode_pong(self):
        """Test pong frame opcode (0xA)."""
        from gunicorn.asgi.websocket import OPCODE_PONG
        assert OPCODE_PONG == 0xA


# ============================================================================
# WebSocket Close Codes Tests (RFC 6455 Section 7.4.1)
# ============================================================================

class TestWebSocketCloseCodes:
    """Tests for WebSocket close status codes."""

    def test_close_normal(self):
        """Test normal closure code (1000)."""
        from gunicorn.asgi.websocket import CLOSE_NORMAL
        assert CLOSE_NORMAL == 1000

    def test_close_going_away(self):
        """Test going away code (1001)."""
        from gunicorn.asgi.websocket import CLOSE_GOING_AWAY
        assert CLOSE_GOING_AWAY == 1001

    def test_close_protocol_error(self):
        """Test protocol error code (1002)."""
        from gunicorn.asgi.websocket import CLOSE_PROTOCOL_ERROR
        assert CLOSE_PROTOCOL_ERROR == 1002

    def test_close_unsupported(self):
        """Test unsupported data code (1003)."""
        from gunicorn.asgi.websocket import CLOSE_UNSUPPORTED
        assert CLOSE_UNSUPPORTED == 1003

    def test_close_no_status(self):
        """Test no status received code (1005)."""
        from gunicorn.asgi.websocket import CLOSE_NO_STATUS
        assert CLOSE_NO_STATUS == 1005

    def test_close_abnormal(self):
        """Test abnormal closure code (1006)."""
        from gunicorn.asgi.websocket import CLOSE_ABNORMAL
        assert CLOSE_ABNORMAL == 1006

    def test_close_invalid_data(self):
        """Test invalid frame payload data code (1007)."""
        from gunicorn.asgi.websocket import CLOSE_INVALID_DATA
        assert CLOSE_INVALID_DATA == 1007

    def test_close_policy_violation(self):
        """Test policy violation code (1008)."""
        from gunicorn.asgi.websocket import CLOSE_POLICY_VIOLATION
        assert CLOSE_POLICY_VIOLATION == 1008

    def test_close_message_too_big(self):
        """Test message too big code (1009)."""
        from gunicorn.asgi.websocket import CLOSE_MESSAGE_TOO_BIG
        assert CLOSE_MESSAGE_TOO_BIG == 1009

    def test_close_mandatory_ext(self):
        """Test mandatory extension code (1010)."""
        from gunicorn.asgi.websocket import CLOSE_MANDATORY_EXT
        assert CLOSE_MANDATORY_EXT == 1010

    def test_close_internal_error(self):
        """Test internal server error code (1011)."""
        from gunicorn.asgi.websocket import CLOSE_INTERNAL_ERROR
        assert CLOSE_INTERNAL_ERROR == 1011


# ============================================================================
# WebSocket Handshake Tests (RFC 6455 Section 4.2.2)
# ============================================================================

class TestWebSocketHandshake:
    """Tests for WebSocket handshake implementation."""

    def test_accept_key_calculation(self):
        """Test Sec-WebSocket-Accept key calculation per RFC 6455."""
        from gunicorn.asgi.websocket import WS_GUID

        # Example from RFC 6455 Section 1.3
        client_key = b"dGhlIHNhbXBsZSBub25jZQ=="
        expected_accept = "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="

        # Calculation: Base64(SHA-1(client_key + GUID))
        accept_key = base64.b64encode(
            hashlib.sha1(client_key + WS_GUID).digest()
        ).decode("ascii")

        assert accept_key == expected_accept

    def test_accept_key_another_example(self):
        """Test accept key calculation with another key."""
        from gunicorn.asgi.websocket import WS_GUID

        # Another example key
        client_key = b"x3JJHMbDL1EzLkh9GBhXDw=="

        accept_key = base64.b64encode(
            hashlib.sha1(client_key + WS_GUID).digest()
        ).decode("ascii")

        # Verify it's a valid base64 string
        assert len(accept_key) == 28  # SHA-1 hash is 20 bytes, base64 encoded
        # Verify we can decode it
        decoded = base64.b64decode(accept_key)
        assert len(decoded) == 20  # SHA-1 produces 20 bytes


# ============================================================================
# WebSocket Frame Masking Tests (RFC 6455 Section 5.3)
# ============================================================================

class TestWebSocketFrameMasking:
    """Tests for WebSocket frame masking/unmasking."""

    def _create_protocol(self):
        """Create a WebSocketProtocol instance for testing."""
        from gunicorn.asgi.websocket import WebSocketProtocol
        return WebSocketProtocol(None, {}, None, mock.Mock())

    def test_unmask_simple(self):
        """Test basic unmasking operation."""
        protocol = self._create_protocol()

        # Mask key and masked "Hello"
        masking_key = bytes([0x37, 0xfa, 0x21, 0x3d])
        # H=0x48, e=0x65, l=0x6c, l=0x6c, o=0x6f
        # Masked: 0x48^0x37=0x7f, 0x65^0xfa=0x9f, 0x6c^0x21=0x4d, 0x6c^0x3d=0x51, 0x6f^0x37=0x58
        masked_data = bytes([0x7f, 0x9f, 0x4d, 0x51, 0x58])

        unmasked = protocol._unmask(masked_data, masking_key)
        assert unmasked == b"Hello"

    def test_unmask_empty(self):
        """Test unmasking empty payload."""
        protocol = self._create_protocol()

        masking_key = bytes([0x37, 0xfa, 0x21, 0x3d])
        unmasked = protocol._unmask(b"", masking_key)

        assert unmasked == b""

    def test_unmask_longer_message(self):
        """Test unmasking message longer than mask key."""
        protocol = self._create_protocol()

        # The mask cycles every 4 bytes
        masking_key = bytes([0x01, 0x02, 0x03, 0x04])
        message = b"12345678"  # 8 bytes

        # Manually mask
        masked = bytes(b ^ masking_key[i % 4] for i, b in enumerate(message))

        # Unmask should give back original
        unmasked = protocol._unmask(masked, masking_key)
        assert unmasked == message

    def test_unmask_binary_data(self):
        """Test unmasking binary data."""
        protocol = self._create_protocol()

        masking_key = bytes([0xAB, 0xCD, 0xEF, 0x01])
        original = bytes([0x00, 0xFF, 0x80, 0x7F, 0x01])

        # Mask the data
        masked = bytes(b ^ masking_key[i % 4] for i, b in enumerate(original))

        # Unmask should give back original
        unmasked = protocol._unmask(masked, masking_key)
        assert unmasked == original


# ============================================================================
# WebSocket Frame Format Tests (RFC 6455 Section 5.2)
# ============================================================================

class TestWebSocketFrameFormat:
    """Tests for WebSocket frame format handling."""

    def test_frame_header_structure(self):
        """Test understanding of WebSocket frame header structure."""
        # First byte: FIN(1) + RSV1(1) + RSV2(1) + RSV3(1) + OPCODE(4)
        # Second byte: MASK(1) + PAYLOAD_LEN(7)

        # Text frame, FIN=1, no RSV bits, opcode=0x1
        first_byte = 0b10000001  # 0x81
        assert (first_byte >> 7) & 1 == 1  # FIN
        assert (first_byte >> 6) & 1 == 0  # RSV1
        assert (first_byte >> 5) & 1 == 0  # RSV2
        assert (first_byte >> 4) & 1 == 0  # RSV3
        assert first_byte & 0x0F == 1  # OPCODE (text)

    def test_payload_length_7bit(self):
        """Test 7-bit payload length encoding (0-125)."""
        # Payload length 100
        second_byte = 0b10000000 | 100  # MASK=1, length=100
        assert (second_byte >> 7) & 1 == 1  # MASK bit
        assert second_byte & 0x7F == 100  # Length

    def test_payload_length_16bit(self):
        """Test 16-bit payload length encoding (126 indicator)."""
        # Length 126 indicates next 2 bytes contain the length
        second_byte = 0b10000000 | 126  # MASK=1, length indicator=126
        assert second_byte & 0x7F == 126

        # Extended length as big-endian 16-bit
        extended_length = 1000
        packed = struct.pack("!H", extended_length)
        assert struct.unpack("!H", packed)[0] == 1000

    def test_payload_length_64bit(self):
        """Test 64-bit payload length encoding (127 indicator)."""
        # Length 127 indicates next 8 bytes contain the length
        second_byte = 0b10000000 | 127  # MASK=1, length indicator=127
        assert second_byte & 0x7F == 127

        # Extended length as big-endian 64-bit
        extended_length = 100000
        packed = struct.pack("!Q", extended_length)
        assert struct.unpack("!Q", packed)[0] == 100000


# ============================================================================
# WebSocket Protocol Instance Tests
# ============================================================================

class TestWebSocketProtocolInstance:
    """Tests for WebSocketProtocol instance state."""

    def _create_protocol(self, scope=None):
        """Create a WebSocketProtocol instance."""
        from gunicorn.asgi.websocket import WebSocketProtocol

        if scope is None:
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

    def test_initial_state(self):
        """Test initial protocol state."""
        protocol = self._create_protocol()

        assert protocol.accepted is False
        assert protocol.closed is False
        assert protocol.close_code is None
        assert protocol.close_reason == ""

    def test_fragment_state_initial(self):
        """Test initial fragment reassembly state."""
        protocol = self._create_protocol()

        assert protocol._fragments == []
        assert protocol._fragment_opcode is None


# ============================================================================
# WebSocket ASGI Message Format Tests
# ============================================================================

class TestWebSocketASGIMessages:
    """Tests for WebSocket ASGI message formats."""

    def test_websocket_connect_message(self):
        """Test websocket.connect message format."""
        message = {"type": "websocket.connect"}
        assert message["type"] == "websocket.connect"

    def test_websocket_accept_message(self):
        """Test websocket.accept message format."""
        message = {
            "type": "websocket.accept",
            "subprotocol": "graphql-ws",
            "headers": [
                (b"x-custom-header", b"value"),
            ],
        }

        assert message["type"] == "websocket.accept"
        assert message["subprotocol"] == "graphql-ws"

    def test_websocket_accept_minimal(self):
        """Test minimal websocket.accept message."""
        message = {"type": "websocket.accept"}
        assert message["type"] == "websocket.accept"

    def test_websocket_receive_text_message(self):
        """Test websocket.receive message with text."""
        message = {
            "type": "websocket.receive",
            "text": "Hello, WebSocket!",
        }

        assert message["type"] == "websocket.receive"
        assert "text" in message
        assert isinstance(message["text"], str)

    def test_websocket_receive_binary_message(self):
        """Test websocket.receive message with binary data."""
        message = {
            "type": "websocket.receive",
            "bytes": b"\x00\x01\x02\x03",
        }

        assert message["type"] == "websocket.receive"
        assert "bytes" in message
        assert isinstance(message["bytes"], bytes)

    def test_websocket_send_text_message(self):
        """Test websocket.send message with text."""
        message = {
            "type": "websocket.send",
            "text": "Response text",
        }

        assert message["type"] == "websocket.send"
        assert message["text"] == "Response text"

    def test_websocket_send_binary_message(self):
        """Test websocket.send message with binary."""
        message = {
            "type": "websocket.send",
            "bytes": b"\xFF\xFE\xFD",
        }

        assert message["type"] == "websocket.send"
        assert message["bytes"] == b"\xFF\xFE\xFD"

    def test_websocket_disconnect_message(self):
        """Test websocket.disconnect message format."""
        message = {
            "type": "websocket.disconnect",
            "code": 1000,
        }

        assert message["type"] == "websocket.disconnect"
        assert message["code"] == 1000

    def test_websocket_close_message(self):
        """Test websocket.close message format."""
        message = {
            "type": "websocket.close",
            "code": 1000,
            "reason": "Normal closure",
        }

        assert message["type"] == "websocket.close"
        assert message["code"] == 1000
        assert message["reason"] == "Normal closure"


# ============================================================================
# WebSocket Upgrade Detection Tests
# ============================================================================

class TestWebSocketUpgradeDetection:
    """Tests for WebSocket upgrade request detection."""

    def _create_protocol(self):
        """Create an ASGIProtocol instance for testing."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        from gunicorn.config import Config
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()

        return ASGIProtocol(worker)

    def _create_mock_request(self, method="GET", headers=None):
        """Create a mock HTTP request."""
        request = mock.Mock()
        request.method = method
        request.headers = headers or []
        return request

    def test_valid_websocket_upgrade(self):
        """Test detection of valid WebSocket upgrade request."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            method="GET",
            headers=[
                ("UPGRADE", "websocket"),
                ("CONNECTION", "upgrade"),
            ]
        )

        assert protocol._is_websocket_upgrade(request) is True

    def test_websocket_upgrade_case_insensitive(self):
        """Test WebSocket upgrade detection is case-insensitive."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            method="GET",
            headers=[
                ("UPGRADE", "WebSocket"),
                ("CONNECTION", "Upgrade"),
            ]
        )

        assert protocol._is_websocket_upgrade(request) is True

    def test_websocket_upgrade_connection_with_keep_alive(self):
        """Test WebSocket upgrade with Connection: upgrade, keep-alive."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            method="GET",
            headers=[
                ("UPGRADE", "websocket"),
                ("CONNECTION", "upgrade, keep-alive"),
            ]
        )

        assert protocol._is_websocket_upgrade(request) is True

    def test_not_websocket_wrong_method(self):
        """Test non-GET methods are not WebSocket upgrades."""
        protocol = self._create_protocol()

        for method in ["POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]:
            request = self._create_mock_request(
                method=method,
                headers=[
                    ("UPGRADE", "websocket"),
                    ("CONNECTION", "upgrade"),
                ]
            )
            assert protocol._is_websocket_upgrade(request) is False

    def test_not_websocket_missing_upgrade(self):
        """Test missing Upgrade header."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            method="GET",
            headers=[
                ("CONNECTION", "upgrade"),
            ]
        )

        assert protocol._is_websocket_upgrade(request) is False

    def test_not_websocket_missing_connection(self):
        """Test missing Connection header."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            method="GET",
            headers=[
                ("UPGRADE", "websocket"),
            ]
        )

        # Result should be falsy (None or False) when Connection header is missing
        assert not protocol._is_websocket_upgrade(request)

    def test_not_websocket_wrong_upgrade_value(self):
        """Test Upgrade header with wrong value."""
        protocol = self._create_protocol()
        request = self._create_mock_request(
            method="GET",
            headers=[
                ("UPGRADE", "h2c"),
                ("CONNECTION", "upgrade"),
            ]
        )

        assert protocol._is_websocket_upgrade(request) is False


# ============================================================================
# WebSocket Close Frame Tests
# ============================================================================

class TestWebSocketCloseFrame:
    """Tests for WebSocket close frame handling."""

    def test_close_frame_payload_format(self):
        """Test close frame payload format (code + reason)."""
        from gunicorn.asgi.websocket import CLOSE_NORMAL

        code = CLOSE_NORMAL
        reason = "Goodbye"

        # Close frame payload: 2-byte big-endian code + UTF-8 reason
        payload = struct.pack("!H", code) + reason.encode("utf-8")

        # Parse it back
        parsed_code = struct.unpack("!H", payload[:2])[0]
        parsed_reason = payload[2:].decode("utf-8")

        assert parsed_code == 1000
        assert parsed_reason == "Goodbye"

    def test_close_frame_empty_reason(self):
        """Test close frame with empty reason."""
        from gunicorn.asgi.websocket import CLOSE_NORMAL

        payload = struct.pack("!H", CLOSE_NORMAL)

        parsed_code = struct.unpack("!H", payload[:2])[0]
        parsed_reason = payload[2:].decode("utf-8")

        assert parsed_code == 1000
        assert parsed_reason == ""

    def test_close_frame_max_reason_length(self):
        """Test close frame reason max length (125 - 2 = 123 bytes)."""
        from gunicorn.asgi.websocket import CLOSE_NORMAL

        # Control frames have max 125 bytes payload
        # 2 bytes for code, leaving 123 for reason
        max_reason = "x" * 123

        payload = struct.pack("!H", CLOSE_NORMAL) + max_reason.encode("utf-8")

        assert len(payload) == 125  # Max control frame payload


# ============================================================================
# Async WebSocket Tests
# ============================================================================

class TestWebSocketAsync:
    """Async tests for WebSocket protocol."""

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
    async def test_receive_returns_from_queue(self):
        """Test that _receive returns items from queue."""
        protocol = self._create_protocol()

        # Put a message on the queue
        await protocol._receive_queue.put({"type": "websocket.connect"})

        # Receive should return it
        message = await protocol._receive()
        assert message["type"] == "websocket.connect"

    @pytest.mark.asyncio
    async def test_send_accept_sets_flag(self):
        """Test that sending accept sets the accepted flag."""
        protocol = self._create_protocol()

        # Configure mock transport
        protocol.transport.write = mock.Mock()

        await protocol._send({"type": "websocket.accept"})

        assert protocol.accepted is True

    @pytest.mark.asyncio
    async def test_send_accept_twice_raises(self):
        """Test that accepting twice raises RuntimeError."""
        protocol = self._create_protocol()
        protocol.transport.write = mock.Mock()

        await protocol._send({"type": "websocket.accept"})

        with pytest.raises(RuntimeError, match="already accepted"):
            await protocol._send({"type": "websocket.accept"})

    @pytest.mark.asyncio
    async def test_send_before_accept_raises(self):
        """Test that sending data before accept raises RuntimeError."""
        protocol = self._create_protocol()

        with pytest.raises(RuntimeError, match="not accepted"):
            await protocol._send({"type": "websocket.send", "text": "hello"})

    @pytest.mark.asyncio
    async def test_send_after_close_raises(self):
        """Test that sending after close raises RuntimeError."""
        protocol = self._create_protocol()
        protocol.transport.write = mock.Mock()

        await protocol._send({"type": "websocket.accept"})
        protocol.closed = True

        with pytest.raises(RuntimeError, match="closed"):
            await protocol._send({"type": "websocket.send", "text": "hello"})

    @pytest.mark.asyncio
    async def test_send_close_sets_flag(self):
        """Test that sending close sets the closed flag."""
        protocol = self._create_protocol()
        protocol.transport.write = mock.Mock()

        await protocol._send({"type": "websocket.close", "code": 1000})

        assert protocol.closed is True


# ============================================================================
# Callback-based Data Feeding Tests
# ============================================================================

class TestWebSocketCallbackDataFeeding:
    """Tests for callback-based data feeding (replaces StreamReader)."""

    def _create_protocol(self):
        """Create a WebSocketProtocol instance for testing."""
        from gunicorn.asgi.websocket import WebSocketProtocol
        return WebSocketProtocol(
            transport=mock.Mock(),
            scope={"type": "websocket", "headers": []},
            app=mock.AsyncMock(),
            log=mock.Mock(),
        )

    def test_initial_buffer_empty(self):
        """Test that initial buffer is empty."""
        protocol = self._create_protocol()
        assert len(protocol._buffer) == 0
        assert protocol._eof is False

    def test_feed_data_adds_to_buffer(self):
        """Test that feed_data adds bytes to buffer."""
        protocol = self._create_protocol()

        protocol.feed_data(b"Hello")
        assert bytes(protocol._buffer) == b"Hello"

        protocol.feed_data(b" World")
        assert bytes(protocol._buffer) == b"Hello World"

    def test_feed_data_ignores_empty(self):
        """Test that feed_data ignores empty data."""
        protocol = self._create_protocol()

        protocol.feed_data(b"")
        assert len(protocol._buffer) == 0

        protocol.feed_data(None)
        # Should not raise, just be ignored

    def test_feed_data_sets_event(self):
        """Test that feed_data sets the data event."""
        protocol = self._create_protocol()

        assert not protocol._data_event.is_set()
        protocol.feed_data(b"data")
        assert protocol._data_event.is_set()

    def test_feed_eof_sets_flag(self):
        """Test that feed_eof sets the EOF flag."""
        protocol = self._create_protocol()

        assert protocol._eof is False
        protocol.feed_eof()
        assert protocol._eof is True

    def test_feed_eof_sets_event(self):
        """Test that feed_eof sets the data event."""
        protocol = self._create_protocol()

        assert not protocol._data_event.is_set()
        protocol.feed_eof()
        assert protocol._data_event.is_set()


class TestWebSocketReadExact:
    """Tests for _read_exact method with callback-based buffer."""

    def _create_protocol(self):
        """Create a WebSocketProtocol instance for testing."""
        from gunicorn.asgi.websocket import WebSocketProtocol
        return WebSocketProtocol(
            transport=mock.Mock(),
            scope={"type": "websocket", "headers": []},
            app=mock.AsyncMock(),
            log=mock.Mock(),
        )

    @pytest.mark.asyncio
    async def test_read_exact_with_sufficient_data(self):
        """Test _read_exact returns data when buffer has enough."""
        protocol = self._create_protocol()

        # Pre-fill buffer
        protocol.feed_data(b"Hello World")

        result = await protocol._read_exact(5)
        assert result == b"Hello"
        assert bytes(protocol._buffer) == b" World"

    @pytest.mark.asyncio
    async def test_read_exact_consumes_buffer(self):
        """Test _read_exact properly consumes buffer."""
        protocol = self._create_protocol()

        protocol.feed_data(b"ABCDEFGH")

        result1 = await protocol._read_exact(3)
        assert result1 == b"ABC"

        result2 = await protocol._read_exact(3)
        assert result2 == b"DEF"

        assert bytes(protocol._buffer) == b"GH"

    @pytest.mark.asyncio
    async def test_read_exact_returns_none_on_eof(self):
        """Test _read_exact returns None when EOF with insufficient data."""
        protocol = self._create_protocol()

        protocol.feed_data(b"Hi")
        protocol.feed_eof()

        # Request more data than available after EOF
        result = await protocol._read_exact(10)
        assert result is None

    @pytest.mark.asyncio
    async def test_read_exact_waits_for_data(self):
        """Test _read_exact waits when buffer is insufficient."""
        import asyncio
        protocol = self._create_protocol()

        # Start read that needs more data
        read_task = asyncio.create_task(protocol._read_exact(10))

        # Give task a chance to start waiting
        await asyncio.sleep(0.01)
        assert not read_task.done()

        # Feed enough data
        protocol.feed_data(b"1234567890")

        result = await asyncio.wait_for(read_task, timeout=1.0)
        assert result == b"1234567890"

    @pytest.mark.asyncio
    async def test_read_exact_handles_incremental_data(self):
        """Test _read_exact handles data arriving in chunks."""
        import asyncio
        protocol = self._create_protocol()

        # Start read needing 10 bytes
        read_task = asyncio.create_task(protocol._read_exact(10))

        await asyncio.sleep(0.01)

        # Feed data incrementally
        protocol.feed_data(b"123")
        await asyncio.sleep(0.01)
        assert not read_task.done()

        protocol.feed_data(b"456")
        await asyncio.sleep(0.01)
        assert not read_task.done()

        protocol.feed_data(b"7890")

        result = await asyncio.wait_for(read_task, timeout=1.0)
        assert result == b"1234567890"

    @pytest.mark.asyncio
    async def test_read_exact_race_condition(self):
        """Test _read_exact handles race condition when data arrives during clear/wait gap.

        This tests the fix for the race condition where:
        1. Task A checks buffer, needs more data
        2. Task A clears _data_event
        3. Task B (data_received) calls feed_data(), sets event
        4. Task A would wait forever on cleared event - DEADLOCK

        The fix adds a buffer check after clear() to catch this case.
        """
        import asyncio
        protocol = self._create_protocol()

        # Pre-fill with partial data
        protocol.feed_data(b"12345")

        # Start read needing 10 bytes
        read_task = asyncio.create_task(protocol._read_exact(10))
        await asyncio.sleep(0.01)
        assert not read_task.done()

        # Simulate race: feed remaining data rapidly
        # In the buggy version, if data arrives right after clear() but before wait(),
        # the event gets set then immediately the wait() would block on a stale clear
        protocol.feed_data(b"67890")

        # Should complete without deadlock
        result = await asyncio.wait_for(read_task, timeout=1.0)
        assert result == b"1234567890"

    @pytest.mark.asyncio
    async def test_read_exact_multiple_feeds_before_wait(self):
        """Test _read_exact when all data arrives before wait starts."""
        import asyncio
        protocol = self._create_protocol()

        # Feed all data before starting read - should not block
        protocol.feed_data(b"Complete message here")

        result = await asyncio.wait_for(protocol._read_exact(8), timeout=0.1)
        assert result == b"Complete"

        # Buffer should have remainder
        assert bytes(protocol._buffer) == b" message here"

    @pytest.mark.asyncio
    async def test_read_exact_eof_during_wait(self):
        """Test _read_exact handles EOF arriving while waiting for data."""
        import asyncio
        protocol = self._create_protocol()

        # Start read needing more data than we'll provide
        read_task = asyncio.create_task(protocol._read_exact(100))

        await asyncio.sleep(0.01)
        assert not read_task.done()

        # Feed some data but not enough
        protocol.feed_data(b"partial")
        await asyncio.sleep(0.01)
        assert not read_task.done()

        # Signal EOF - should cause read to return None
        protocol.feed_eof()

        result = await asyncio.wait_for(read_task, timeout=1.0)
        assert result is None


# ============================================================================
# WebSocket Fragmented Message Tests (RFC 6455 Section 5.4)
# ============================================================================

class TestWebSocketFragmentedMessages:
    """Tests for WebSocket fragmented message handling."""

    def _create_protocol(self):
        """Create a WebSocketProtocol instance for testing."""
        from gunicorn.asgi.websocket import WebSocketProtocol
        return WebSocketProtocol(
            transport=mock.Mock(),
            scope={"type": "websocket", "headers": []},
            app=mock.AsyncMock(),
            log=mock.Mock(),
        )

    def _create_masked_frame(self, fin, opcode, payload, mask_key=None):
        """Create a masked WebSocket frame.

        Args:
            fin: FIN bit (1 for final, 0 for continuation)
            opcode: Frame opcode
            payload: Frame payload bytes
            mask_key: 4-byte masking key (generated if None)

        Returns:
            bytes: Complete masked frame
        """
        if mask_key is None:
            mask_key = bytes([0x37, 0xfa, 0x21, 0x3d])

        frame = bytearray()

        # First byte: FIN + RSV(000) + opcode
        frame.append((fin << 7) | opcode)

        # Second byte: MASK(1) + length
        length = len(payload)
        if length < 126:
            frame.append(0x80 | length)
        elif length < 65536:
            frame.append(0x80 | 126)
            frame.extend(struct.pack("!H", length))
        else:
            frame.append(0x80 | 127)
            frame.extend(struct.pack("!Q", length))

        # Masking key
        frame.extend(mask_key)

        # Masked payload
        masked_payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        frame.extend(masked_payload)

        return bytes(frame)

    @pytest.mark.asyncio
    async def test_fragmented_message_reassembly(self):
        """Test reassembly of fragmented text message with multiple continuation frames."""
        from gunicorn.asgi.websocket import (
            OPCODE_TEXT, OPCODE_CONTINUATION, OPCODE_CONTINUATION as CONT
        )
        import asyncio

        protocol = self._create_protocol()

        # Build fragmented message: "Hello" + " " + "World" + "!"
        # First frame: opcode=TEXT, FIN=0, payload="Hello"
        frame1 = self._create_masked_frame(fin=0, opcode=OPCODE_TEXT, payload=b"Hello")
        # Continuation frames: opcode=CONTINUATION, FIN=0
        frame2 = self._create_masked_frame(fin=0, opcode=CONT, payload=b" ")
        frame3 = self._create_masked_frame(fin=0, opcode=CONT, payload=b"World")
        # Final frame: opcode=CONTINUATION, FIN=1
        frame4 = self._create_masked_frame(fin=1, opcode=CONT, payload=b"!")

        # Feed all frames
        protocol.feed_data(frame1 + frame2 + frame3 + frame4)

        # Read frames - first 3 should return CONTINUATION with empty payload (waiting)
        result1 = await asyncio.wait_for(protocol._read_frame(), timeout=1.0)
        assert result1 == (OPCODE_CONTINUATION, b"")  # Fragment started

        result2 = await asyncio.wait_for(protocol._read_frame(), timeout=1.0)
        assert result2 == (OPCODE_CONTINUATION, b"")  # Fragment continued

        result3 = await asyncio.wait_for(protocol._read_frame(), timeout=1.0)
        assert result3 == (OPCODE_CONTINUATION, b"")  # Fragment continued

        # Final frame should return complete reassembled message with original opcode
        result4 = await asyncio.wait_for(protocol._read_frame(), timeout=1.0)
        assert result4 == (OPCODE_TEXT, b"Hello World!")

    @pytest.mark.asyncio
    async def test_control_frame_during_fragmentation(self):
        """Test that control frames (ping) can arrive during fragmented message.

        RFC 6455 Section 5.4: Control frames MAY be injected in the middle
        of a fragmented message.
        """
        from gunicorn.asgi.websocket import (
            OPCODE_TEXT, OPCODE_CONTINUATION, OPCODE_PING
        )
        import asyncio

        protocol = self._create_protocol()

        # Start fragmented message
        frame1 = self._create_masked_frame(fin=0, opcode=OPCODE_TEXT, payload=b"Hello")
        # Ping frame in the middle (control frames are always FIN=1)
        ping_frame = self._create_masked_frame(fin=1, opcode=OPCODE_PING, payload=b"ping")
        # Continue and finish fragmented message
        frame2 = self._create_masked_frame(fin=1, opcode=OPCODE_CONTINUATION, payload=b" World")

        protocol.feed_data(frame1 + ping_frame + frame2)

        # First read: fragment started (waiting for more)
        result1 = await asyncio.wait_for(protocol._read_frame(), timeout=1.0)
        assert result1 == (OPCODE_CONTINUATION, b"")

        # Second read: ping frame (control frames handled separately)
        result2 = await asyncio.wait_for(protocol._read_frame(), timeout=1.0)
        assert result2 == (OPCODE_PING, b"ping")

        # Third read: complete reassembled message
        result3 = await asyncio.wait_for(protocol._read_frame(), timeout=1.0)
        assert result3 == (OPCODE_TEXT, b"Hello World")
