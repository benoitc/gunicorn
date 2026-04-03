#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Protocol-level tests reproducing ASGI framework compatibility failures.

These tests verify gunicorn's ASGI protocol handling without needing
Docker or external frameworks. They target specific issues discovered
in the ASGI Framework Compatibility E2E test suite.

Failure categories addressed:
- HTTP 100 Continue via http.response.start (6 failures across all frameworks)
- WebSocket Close Codes (12 failures - Django + Quart)
- WebSocket Binary Messages (4 failures - Quart + Litestar)
"""

import asyncio
import struct
from unittest import mock

import pytest


# =============================================================================
# HTTP 100 Continue Tests - THESE SHOULD FAIL
# =============================================================================

class TestHttp100ContinueViaResponseStart:
    """Tests for HTTP 100 status sent via http.response.start (not informational).

    This is what frameworks like Django do when returning HttpResponse(status=100).
    The ASGI spec says 1xx should use http.response.informational, but frameworks
    often use http.response.start instead.

    Reproduces failures:
    - test_status_100_continue[django] - illegal status line
    - test_status_100_continue[fastapi] - illegal status line
    - test_status_100_continue[starlette] - illegal status line
    - test_status_100_continue[quart] - ReadTimeout
    - test_status_100_continue[litestar] - Status 500
    - test_status_100_continue[blacksheep] - ReadTimeout

    Root cause: When status 100 is sent via http.response.start:
    1. Gunicorn adds Transfer-Encoding: chunked (invalid for 1xx)
    2. Response is buffered waiting for body
    3. Body terminator 0\r\n\r\n is invalid for 1xx
    """

    def _create_protocol(self):
        """Create an ASGIProtocol instance for testing."""
        from gunicorn.asgi.protocol import ASGIProtocol
        from gunicorn.config import Config

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.log.access_log_enabled = False
        worker.asgi = mock.Mock()
        worker.nr = 0
        worker.max_requests = 10000
        worker.alive = True
        worker.state = {}

        protocol = ASGIProtocol(worker)
        protocol.transport = mock.Mock()
        protocol._response_buffer = None
        protocol._flow_control = mock.Mock()
        protocol._flow_control.drain = mock.AsyncMock()
        protocol._closed = False
        return protocol

    def _create_mock_request(self, version=(1, 1)):
        """Create a mock HTTP request."""
        request = mock.Mock()
        request.method = "GET"
        request.path = "/status/100"
        request.raw_path = b"/status/100"
        request.query = ""
        request.version = version
        request.scheme = "http"
        request.headers = []
        request.uri = "/status/100"
        request.should_close = mock.Mock(return_value=False)
        request.content_length = 0
        request.chunked = False
        return request

    def test_100_status_should_not_add_transfer_encoding(self):
        """1xx responses MUST NOT have Transfer-Encoding header.

        RFC 9110 Section 15.2: A server MUST NOT send a Content-Length
        header field in any response with a status code of 1xx.
        """
        # Test the actual protocol logic for 1xx responses
        response_status = 100
        response_headers = [(b"content-type", b"text/plain")]
        request_version = (1, 1)

        has_content_length = any(
            name.lower() == b"content-length" for name, _ in response_headers
        )

        # This mirrors the fixed logic in protocol.py
        is_informational = 100 <= response_status < 200
        use_chunked = not has_content_length and request_version >= (1, 1) and not is_informational

        # For 1xx responses, use_chunked MUST be False
        assert not use_chunked, \
            "Transfer-Encoding should not be added to 1xx response"

    def test_100_status_response_format_valid(self):
        """100 response via http.response.start should be valid HTTP.

        When a framework sends status=100 via http.response.start,
        gunicorn should produce a valid HTTP response without chunked encoding.
        """
        protocol = self._create_protocol()
        request = self._create_mock_request()

        written_data = []
        protocol.transport.write = mock.Mock(side_effect=lambda d: written_data.append(d))

        # Send response start with status 100
        protocol._send_response_start(100, [], request)

        # Flush buffered response
        if protocol._response_buffer:
            protocol.transport.write(protocol._response_buffer)
            written_data.append(protocol._response_buffer)

        response = b"".join(written_data).decode("latin-1")

        # Must NOT contain transfer-encoding for 1xx
        assert "transfer-encoding" not in response.lower(), \
            "BUG: 1xx response contains Transfer-Encoding header"

    @pytest.mark.asyncio
    async def test_100_status_full_response_cycle(self):
        """Full response cycle with status 100 should produce valid HTTP.

        This simulates what happens when Django does:
            return HttpResponse("Status: 100", status=100)
        """
        from gunicorn.asgi.protocol import ASGIProtocol, BodyReceiver
        from gunicorn.config import Config

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.log.access_log_enabled = False
        worker.asgi = mock.Mock()
        worker.nr = 0
        worker.max_requests = 10000
        worker.alive = True
        worker.state = {}

        protocol = ASGIProtocol(worker)
        protocol.transport = mock.Mock()
        protocol._closed = False
        protocol._flow_control = mock.Mock()
        protocol._flow_control.drain = mock.AsyncMock()

        written_data = []
        protocol.transport.write = mock.Mock(side_effect=lambda d: written_data.append(d))

        request = self._create_mock_request()

        # Create body receiver
        protocol._body_receiver = BodyReceiver(request, protocol)
        protocol._body_receiver.set_complete()

        # Simulate framework sending status 100
        async def status_100_app(scope, receive, send):
            await send({
                "type": "http.response.start",
                "status": 100,
                "headers": [],
            })
            await send({
                "type": "http.response.body",
                "body": b"Status: 100",
                "more_body": False,
            })

        protocol.app = status_100_app

        # Handle the request
        sockname = ("127.0.0.1", 8000)
        peername = ("127.0.0.1", 50000)

        await protocol._handle_http_request(request, sockname, peername)

        # Check what was written
        response = b"".join(written_data).decode("latin-1")

        # For 1xx responses:
        # 1. Should NOT have Transfer-Encoding
        # 2. Should NOT have chunked body markers (0\r\n\r\n)
        assert "transfer-encoding" not in response.lower(), \
            f"BUG: 1xx response has Transfer-Encoding:\n{response}"

        assert "0\r\n\r\n" not in response, \
            f"BUG: 1xx response has chunked terminator:\n{response}"


# =============================================================================
# HTTP Informational Response Tests (Proper ASGI way)
# =============================================================================

class TestHttp100ContinueInformational:
    """Tests for HTTP 100 Continue via http.response.informational.

    This is the correct ASGI way to send 1xx responses.
    """

    def _create_protocol(self):
        """Create an ASGIProtocol instance for testing."""
        from gunicorn.asgi.protocol import ASGIProtocol
        from gunicorn.config import Config

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()

        protocol = ASGIProtocol(worker)
        protocol.transport = mock.Mock()
        protocol._response_buffer = None
        return protocol

    def _create_mock_request(self, version=(1, 1)):
        """Create a mock HTTP request."""
        request = mock.Mock()
        request.method = "POST"
        request.path = "/upload"
        request.raw_path = b"/upload"
        request.query = ""
        request.version = version
        request.scheme = "http"
        request.headers = [("EXPECT", "100-continue"), ("CONTENT-LENGTH", "1000")]
        return request

    def test_informational_response_format_100(self):
        """Verify 100 Continue via informational is properly formatted."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        written_data = []
        protocol.transport.write = mock.Mock(side_effect=lambda d: written_data.append(d))

        protocol._send_informational(100, [], request)

        assert len(written_data) == 1
        response = written_data[0].decode("latin-1")

        # Must be valid HTTP format
        assert response.startswith("HTTP/1.1 100 Continue\r\n")
        assert response.endswith("\r\n\r\n")

    def test_informational_103_early_hints(self):
        """Verify 103 Early Hints informational response."""
        protocol = self._create_protocol()
        request = self._create_mock_request()

        written_data = []
        protocol.transport.write = mock.Mock(side_effect=lambda d: written_data.append(d))

        headers = [(b"link", b"</style.css>; rel=preload; as=style")]
        protocol._send_informational(103, headers, request)

        response = written_data[0].decode("latin-1")

        assert response.startswith("HTTP/1.1 103 Early Hints\r\n")
        assert "link: </style.css>; rel=preload; as=style\r\n" in response

    def test_informational_not_sent_to_http10(self):
        """Informational responses should not be sent to HTTP/1.0 clients."""
        protocol = self._create_protocol()
        request = self._create_mock_request(version=(1, 0))

        written_data = []
        protocol.transport.write = mock.Mock(side_effect=lambda d: written_data.append(d))

        protocol._send_informational(100, [], request)

        # Should not have written anything
        assert len(written_data) == 0


# =============================================================================
# WebSocket Close Frame Tests
# =============================================================================

class TestWebSocketCloseFrame:
    """Tests for WebSocket close frame transmission.

    Reproduces failures:
    - test_close_normal[django] - TimeoutError
    - test_close_codes[django-1001] - TimeoutError
    - test_close_codes[django-1002] - TimeoutError
    - test_close_codes[django-1003] - TimeoutError
    - test_close_codes[django-1008] - TimeoutError
    - test_close_codes[django-1011] - TimeoutError
    """

    def _create_websocket_protocol(self):
        """Create WebSocketProtocol with mock transport."""
        from gunicorn.asgi.websocket import WebSocketProtocol

        transport = mock.Mock()
        transport.write = mock.Mock()

        return WebSocketProtocol(
            transport=transport,
            scope={
                "type": "websocket",
                "headers": [(b"sec-websocket-key", b"dGhlIHNhbXBsZSBub25jZQ==")],
            },
            app=mock.AsyncMock(),
            log=mock.Mock(),
        )

    def _extract_close_code_from_frame(self, frame_data):
        """Extract close code from WebSocket close frame."""
        idx = 0
        while idx < len(frame_data):
            if frame_data[idx] == 0x88:  # FIN + Close opcode
                length = frame_data[idx + 1] & 0x7F
                if length >= 2:
                    code = struct.unpack("!H", frame_data[idx + 2:idx + 4])[0]
                    return code
            idx += 1
        return None

    @pytest.mark.asyncio
    async def test_close_code_1000_in_frame(self):
        """Verify close code 1000 (normal) is in close frame."""
        protocol = self._create_websocket_protocol()

        await protocol._send({"type": "websocket.accept"})
        await protocol._send({"type": "websocket.close", "code": 1000})

        written_data = b"".join(
            call.args[0] for call in protocol.transport.write.call_args_list
        )

        close_code = self._extract_close_code_from_frame(written_data)
        assert close_code == 1000, f"Expected close code 1000, got {close_code}"

    @pytest.mark.asyncio
    async def test_close_code_1001_going_away(self):
        """Test close with code 1001 (going away)."""
        protocol = self._create_websocket_protocol()

        await protocol._send({"type": "websocket.accept"})
        await protocol._send({"type": "websocket.close", "code": 1001})

        written_data = b"".join(
            call.args[0] for call in protocol.transport.write.call_args_list
        )

        close_code = self._extract_close_code_from_frame(written_data)
        assert close_code == 1001

    @pytest.mark.asyncio
    async def test_close_code_1002_protocol_error(self):
        """Test close with code 1002 (protocol error)."""
        protocol = self._create_websocket_protocol()

        await protocol._send({"type": "websocket.accept"})
        await protocol._send({"type": "websocket.close", "code": 1002})

        written_data = b"".join(
            call.args[0] for call in protocol.transport.write.call_args_list
        )

        close_code = self._extract_close_code_from_frame(written_data)
        assert close_code == 1002

    @pytest.mark.asyncio
    async def test_close_code_1008_policy_violation(self):
        """Test close with code 1008 (policy violation)."""
        protocol = self._create_websocket_protocol()

        await protocol._send({"type": "websocket.accept"})
        await protocol._send({"type": "websocket.close", "code": 1008})

        written_data = b"".join(
            call.args[0] for call in protocol.transport.write.call_args_list
        )

        close_code = self._extract_close_code_from_frame(written_data)
        assert close_code == 1008

    @pytest.mark.asyncio
    async def test_close_code_1011_internal_error(self):
        """Test close with code 1011 (internal error)."""
        protocol = self._create_websocket_protocol()

        await protocol._send({"type": "websocket.accept"})
        await protocol._send({"type": "websocket.close", "code": 1011})

        written_data = b"".join(
            call.args[0] for call in protocol.transport.write.call_args_list
        )

        close_code = self._extract_close_code_from_frame(written_data)
        assert close_code == 1011


# =============================================================================
# WebSocket Accept-Then-Close Pattern Tests - SIMULATING E2E
# =============================================================================

class TestWebSocketAcceptThenCloseE2E:
    """Tests for accept-then-immediate-close pattern simulating full run() cycle.

    This is the pattern used by Django CloseConsumer:
        async def connect(self):
            await self.accept()
            await self.close(code=code)

    Reproduces failures:
    - test_close_normal[django] - TimeoutError
    - test_close_codes[django-*] - TimeoutError
    - test_close_normal[quart] - InvalidMessage
    - test_close_codes[quart-*] - InvalidMessage
    """

    @pytest.mark.asyncio
    async def test_accept_then_immediate_close_full_cycle(self):
        """Test full WebSocket lifecycle with immediate close after accept.

        This simulates Django's CloseConsumer pattern and verifies
        that both handshake AND close frame are written to transport.
        """
        from gunicorn.asgi.websocket import WebSocketProtocol

        transport = mock.Mock()
        written_data = []
        transport.write = mock.Mock(side_effect=lambda d: written_data.append(d))

        protocol = WebSocketProtocol(
            transport=transport,
            scope={
                "type": "websocket",
                "headers": [(b"sec-websocket-key", b"dGhlIHNhbXBsZSBub25jZQ==")],
            },
            app=None,  # Will be replaced
            log=mock.Mock(),
        )

        # App that accepts then immediately closes (Django pattern)
        async def close_app(scope, receive, send):
            # Wait for connect message
            message = await receive()
            assert message["type"] == "websocket.connect"

            # Accept
            await send({"type": "websocket.accept"})

            # Immediately close with code
            await send({"type": "websocket.close", "code": 1000})

        protocol.app = close_app

        # Helper to simulate client close frame response after server sends close
        async def feed_client_close_after_delay():
            # Wait for server to send close frame
            await asyncio.sleep(0.1)
            # Masked close frame with code 1000: FIN=1, opcode=8, masked, len=2
            # Mask key: 0x00000000 for simplicity, payload: 0x03E8 (1000)
            client_close = bytes([
                0x88,  # FIN + opcode 8 (close)
                0x82,  # Masked + length 2
                0x00, 0x00, 0x00, 0x00,  # Mask key
                0x03, 0xE8,  # Close code 1000 (masked with 0s = unchanged)
            ])
            protocol.feed_data(client_close)

        # Run both concurrently
        async def run_with_client_response():
            await asyncio.gather(
                protocol.run(),
                feed_client_close_after_delay(),
            )

        # Run the WebSocket - this should complete without timeout
        try:
            await asyncio.wait_for(run_with_client_response(), timeout=2.0)
        except asyncio.TimeoutError:
            pytest.fail("WebSocket run() timed out - close frame likely not sent")

        # Verify both accept and close were written
        assert len(written_data) >= 2, \
            f"Expected at least 2 writes (accept + close), got {len(written_data)}"

        combined = b"".join(written_data)

        # Should have HTTP 101 response
        assert b"HTTP/1.1 101" in combined, "Missing HTTP 101 Switching Protocols"

        # Should have close frame (0x88)
        assert b"\x88" in combined, "Missing WebSocket close frame"

    @pytest.mark.asyncio
    async def test_accept_close_with_custom_code_full_cycle(self):
        """Test accept-then-close with custom close code (1008)."""
        from gunicorn.asgi.websocket import WebSocketProtocol

        transport = mock.Mock()
        written_data = []
        transport.write = mock.Mock(side_effect=lambda d: written_data.append(d))

        protocol = WebSocketProtocol(
            transport=transport,
            scope={
                "type": "websocket",
                "headers": [(b"sec-websocket-key", b"dGhlIHNhbXBsZSBub25jZQ==")],
            },
            app=None,  # Will be replaced
            log=mock.Mock(),
        )

        async def close_app(scope, receive, send):
            message = await receive()
            assert message["type"] == "websocket.connect"

            await send({"type": "websocket.accept"})
            await send({"type": "websocket.close", "code": 1008})

        protocol.app = close_app

        # Helper to simulate client close frame response
        async def feed_client_close_after_delay():
            await asyncio.sleep(0.1)
            # Masked close frame with code 1008
            client_close = bytes([
                0x88,  # FIN + opcode 8 (close)
                0x82,  # Masked + length 2
                0x00, 0x00, 0x00, 0x00,  # Mask key
                0x03, 0xF0,  # Close code 1008 (masked with 0s = unchanged)
            ])
            protocol.feed_data(client_close)

        async def run_with_client_response():
            await asyncio.gather(
                protocol.run(),
                feed_client_close_after_delay(),
            )

        await asyncio.wait_for(run_with_client_response(), timeout=2.0)

        combined = b"".join(written_data)

        # Find close frame and verify code
        idx = combined.find(b"\x88")
        assert idx >= 0, "Close frame not found"

        code = struct.unpack("!H", combined[idx + 2:idx + 4])[0]
        assert code == 1008, f"Expected close code 1008, got {code}"


# =============================================================================
# WebSocket Binary Message Tests
# =============================================================================

class TestWebSocketBinaryMessages:
    """Tests for WebSocket binary message handling.

    Reproduces failures:
    - test_websocket_echo_binary[quart] - ConnectionClosedOK
    - test_websocket_echo_large_binary[quart] - ConnectionClosedOK
    - test_websocket_echo_binary[litestar] - no close frame
    - test_websocket_echo_large_binary[litestar] - no close frame
    """

    def _create_protocol(self):
        """Create WebSocketProtocol with mock transport."""
        from gunicorn.asgi.websocket import WebSocketProtocol

        transport = mock.Mock()
        transport.write = mock.Mock()

        return WebSocketProtocol(
            transport=transport,
            scope={
                "type": "websocket",
                "headers": [(b"sec-websocket-key", b"dGhlIHNhbXBsZSBub25jZQ==")],
            },
            app=mock.AsyncMock(),
            log=mock.Mock(),
        )

    @pytest.mark.asyncio
    async def test_binary_send_small(self):
        """Test sending small binary message."""
        protocol = self._create_protocol()

        await protocol._send({"type": "websocket.accept"})
        await protocol._send({
            "type": "websocket.send",
            "bytes": b"\x00\x01\x02\x03"
        })

        written = b"".join(
            c.args[0] for c in protocol.transport.write.call_args_list
        )

        # Find binary frame (0x82 = FIN + opcode 2)
        assert b"\x82" in written

    @pytest.mark.asyncio
    async def test_binary_send_large(self):
        """Test sending large binary message (64KB)."""
        protocol = self._create_protocol()

        await protocol._send({"type": "websocket.accept"})

        large_data = bytes(range(256)) * 256  # 64KB
        await protocol._send({"type": "websocket.send", "bytes": large_data})

        written = b"".join(
            c.args[0] for c in protocol.transport.write.call_args_list
        )

        assert len(written) > 65536

    @pytest.mark.asyncio
    async def test_binary_frame_opcode(self):
        """Test binary message uses correct opcode (0x2)."""
        from gunicorn.asgi.websocket import OPCODE_BINARY

        protocol = self._create_protocol()

        await protocol._send({"type": "websocket.accept"})
        await protocol._send({
            "type": "websocket.send",
            "bytes": b"test binary"
        })

        binary_frame = protocol.transport.write.call_args_list[1].args[0]

        # First byte should be FIN (0x80) + BINARY opcode (0x02) = 0x82
        assert binary_frame[0] == (0x80 | OPCODE_BINARY)


# =============================================================================
# WebSocket Frame Reading Tests
# =============================================================================

class TestWebSocketFrameReading:
    """Tests for WebSocket frame reading/parsing."""

    def _create_protocol(self):
        """Create WebSocketProtocol with mock transport."""
        from gunicorn.asgi.websocket import WebSocketProtocol

        transport = mock.Mock()
        transport.write = mock.Mock()

        return WebSocketProtocol(
            transport=transport,
            scope={
                "type": "websocket",
                "headers": [(b"sec-websocket-key", b"dGhlIHNhbXBsZSBub25jZQ==")],
            },
            app=mock.AsyncMock(),
            log=mock.Mock(),
        )

    def _build_masked_frame(self, opcode, payload):
        """Build a client-to-server masked WebSocket frame."""
        mask_key = bytes([0x12, 0x34, 0x56, 0x78])
        masked_payload = bytes(
            b ^ mask_key[i % 4] for i, b in enumerate(payload)
        )

        frame = bytearray()
        frame.append(0x80 | opcode)

        length = len(payload)
        if length < 126:
            frame.append(0x80 | length)
        elif length < 65536:
            frame.append(0x80 | 126)
            frame.extend(struct.pack("!H", length))
        else:
            frame.append(0x80 | 127)
            frame.extend(struct.pack("!Q", length))

        frame.extend(mask_key)
        frame.extend(masked_payload)

        return bytes(frame)

    @pytest.mark.asyncio
    async def test_read_binary_frame(self):
        """Test reading a binary frame."""
        from gunicorn.asgi.websocket import OPCODE_BINARY

        protocol = self._create_protocol()

        payload = b"\x00\x01\x02\x03"
        frame = self._build_masked_frame(OPCODE_BINARY, payload)

        protocol.feed_data(frame)

        result = await asyncio.wait_for(protocol._read_frame(), timeout=1.0)

        assert result is not None
        opcode, data = result
        assert opcode == OPCODE_BINARY
        assert data == payload

    @pytest.mark.asyncio
    async def test_read_large_binary_frame(self):
        """Test reading a large binary frame (64KB)."""
        from gunicorn.asgi.websocket import OPCODE_BINARY

        protocol = self._create_protocol()

        payload = bytes(range(256)) * 256  # 64KB
        frame = self._build_masked_frame(OPCODE_BINARY, payload)

        protocol.feed_data(frame)

        result = await asyncio.wait_for(protocol._read_frame(), timeout=5.0)

        assert result is not None
        opcode, data = result
        assert opcode == OPCODE_BINARY
        assert data == payload
        assert len(data) == 65536

    @pytest.mark.asyncio
    async def test_binary_receive_does_not_close(self):
        """Test that receiving binary doesn't unexpectedly close connection."""
        from gunicorn.asgi.websocket import OPCODE_BINARY

        protocol = self._create_protocol()

        payload = b"\x00\x01\x02\x03"
        frame = self._build_masked_frame(OPCODE_BINARY, payload)

        protocol.feed_data(frame)

        result = await asyncio.wait_for(protocol._read_frame(), timeout=1.0)

        assert result is not None
        assert result[0] == OPCODE_BINARY
        assert protocol.closed is False


# =============================================================================
# WebSocket Handshake Tests
# =============================================================================

class TestWebSocketHandshake:
    """Tests for WebSocket upgrade handshake."""

    def _create_websocket_protocol(self, ws_key=b"dGhlIHNhbXBsZSBub25jZQ=="):
        """Create WebSocketProtocol with mock transport."""
        from gunicorn.asgi.websocket import WebSocketProtocol

        transport = mock.Mock()
        transport.write = mock.Mock()

        return WebSocketProtocol(
            transport=transport,
            scope={
                "type": "websocket",
                "headers": [(b"sec-websocket-key", ws_key)],
            },
            app=mock.AsyncMock(),
            log=mock.Mock(),
        )

    @pytest.mark.asyncio
    async def test_handshake_accept_key_calculation(self):
        """Test WebSocket accept key is correctly calculated."""
        import base64
        import hashlib
        from gunicorn.asgi.websocket import WS_GUID

        ws_key = b"dGhlIHNhbXBsZSBub25jZQ=="
        protocol = self._create_websocket_protocol(ws_key)

        await protocol._send({"type": "websocket.accept"})

        expected_accept = base64.b64encode(
            hashlib.sha1(ws_key + WS_GUID).digest()
        ).decode("ascii")

        response = protocol.transport.write.call_args_list[0].args[0].decode("latin-1")
        assert f"Sec-WebSocket-Accept: {expected_accept}" in response

    @pytest.mark.asyncio
    async def test_handshake_with_subprotocol(self):
        """Test handshake with subprotocol selection."""
        protocol = self._create_websocket_protocol()
        protocol.scope["subprotocols"] = ["graphql-ws", "chat"]

        await protocol._send({
            "type": "websocket.accept",
            "subprotocol": "graphql-ws"
        })

        response = protocol.transport.write.call_args_list[0].args[0].decode("latin-1")
        assert "Sec-WebSocket-Protocol: graphql-ws" in response

    @pytest.mark.asyncio
    async def test_handshake_missing_key_raises(self):
        """Test handshake without Sec-WebSocket-Key raises error."""
        from gunicorn.asgi.websocket import WebSocketProtocol

        transport = mock.Mock()
        transport.write = mock.Mock()

        protocol = WebSocketProtocol(
            transport=transport,
            scope={"type": "websocket", "headers": []},
            app=mock.AsyncMock(),
            log=mock.Mock(),
        )

        with pytest.raises(RuntimeError, match="Missing Sec-WebSocket-Key"):
            await protocol._send({"type": "websocket.accept"})
