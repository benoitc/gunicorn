#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
WebSocket compliance integration tests for ASGI.

Tests RFC 6455 WebSocket protocol compliance including handshake,
messaging, close codes, and subprotocol negotiation.
"""

import asyncio
import json

import pytest

pytestmark = [
    pytest.mark.docker,
    pytest.mark.asgi,
    pytest.mark.websocket,
    pytest.mark.integration,
]


# ============================================================================
# WebSocket Handshake Tests
# ============================================================================

@pytest.mark.asyncio
class TestWebSocketHandshake:
    """Test WebSocket handshake and connection establishment."""

    async def test_basic_connection(self, websocket_connect, gunicorn_url):
        """Test basic WebSocket connection."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/echo"
        async with await websocket_connect(ws_url) as ws:
            # Connection successful - verify by sending a message
            await ws.send("test")
            response = await ws.recv()
            assert response == "test"

    async def test_echo_after_connect(self, websocket_connect, gunicorn_url):
        """Test sending message after connection."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/echo"
        async with await websocket_connect(ws_url) as ws:
            await ws.send("hello")
            response = await ws.recv()
            assert response == "hello"

    async def test_connection_path_preserved(self, websocket_connect, gunicorn_url):
        """Test that connection path is preserved in scope."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/scope"
        async with await websocket_connect(ws_url) as ws:
            response = await ws.recv()
            scope = json.loads(response)
            assert scope["path"] == "/ws/scope"

    async def test_connection_with_query_string(self, websocket_connect, gunicorn_url):
        """Test connection with query string."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/scope?foo=bar&baz=qux"
        async with await websocket_connect(ws_url) as ws:
            response = await ws.recv()
            scope = json.loads(response)
            assert "foo=bar" in scope["query_string"]
            assert "baz=qux" in scope["query_string"]


# ============================================================================
# Text Message Tests
# ============================================================================

@pytest.mark.asyncio
class TestTextMessages:
    """Test WebSocket text message handling."""

    async def test_echo_text(self, websocket_connect, gunicorn_url):
        """Test echoing text message."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/echo"
        async with await websocket_connect(ws_url) as ws:
            await ws.send("Hello, WebSocket!")
            response = await ws.recv()
            assert response == "Hello, WebSocket!"

    async def test_echo_unicode(self, websocket_connect, gunicorn_url):
        """Test echoing unicode text."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/echo"
        async with await websocket_connect(ws_url) as ws:
            message = "Hello \u4e16\u754c! \U0001f600"  # Hello World in Chinese + emoji
            await ws.send(message)
            response = await ws.recv()
            assert response == message

    async def test_echo_empty_string(self, websocket_connect, gunicorn_url):
        """Test echoing empty string."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/echo"
        async with await websocket_connect(ws_url) as ws:
            await ws.send("")
            response = await ws.recv()
            assert response == ""

    async def test_multiple_messages(self, websocket_connect, gunicorn_url):
        """Test sending multiple messages."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/echo"
        async with await websocket_connect(ws_url) as ws:
            messages = ["first", "second", "third"]
            for msg in messages:
                await ws.send(msg)
                response = await ws.recv()
                assert response == msg

    async def test_rapid_messages(self, websocket_connect, gunicorn_url):
        """Test sending messages rapidly."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/echo"
        async with await websocket_connect(ws_url) as ws:
            count = 100
            for i in range(count):
                await ws.send(f"message {i}")

            for i in range(count):
                response = await ws.recv()
                assert f"message {i}" == response


# ============================================================================
# Binary Message Tests
# ============================================================================

@pytest.mark.asyncio
class TestBinaryMessages:
    """Test WebSocket binary message handling."""

    async def test_echo_binary(self, websocket_connect, gunicorn_url):
        """Test echoing binary message."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/echo-binary"
        async with await websocket_connect(ws_url) as ws:
            data = b"\x00\x01\x02\x03\x04\x05"
            await ws.send(data)
            response = await ws.recv()
            assert response == data

    async def test_echo_binary_large(self, websocket_connect, gunicorn_url):
        """Test echoing larger binary message."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/echo-binary"
        async with await websocket_connect(ws_url) as ws:
            data = bytes(range(256)) * 100  # 25.6KB
            await ws.send(data)
            response = await ws.recv()
            assert response == data

    async def test_text_to_binary_conversion(self, websocket_connect, gunicorn_url):
        """Test text converted to binary in binary endpoint."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/echo-binary"
        async with await websocket_connect(ws_url) as ws:
            await ws.send("hello")
            response = await ws.recv()
            assert response == b"hello"


# ============================================================================
# Subprotocol Negotiation Tests
# ============================================================================

@pytest.mark.asyncio
class TestSubprotocols:
    """Test WebSocket subprotocol negotiation."""

    async def test_single_subprotocol(self, websocket_connect, gunicorn_url):
        """Test single subprotocol negotiation."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/subprotocol"
        async with await websocket_connect(ws_url, subprotocols=["json"]) as ws:
            response = await ws.recv()
            data = json.loads(response)
            assert data["selected"] == "json"
            assert data["requested"] == ["json"]

    async def test_multiple_subprotocols(self, websocket_connect, gunicorn_url):
        """Test multiple subprotocol negotiation."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/subprotocol"
        async with await websocket_connect(ws_url, subprotocols=["wamp", "json"]) as ws:
            response = await ws.recv()
            data = json.loads(response)
            # Server prefers json over wamp
            assert data["selected"] == "json"
            assert set(data["requested"]) == {"wamp", "json"}

    async def test_preferred_subprotocol(self, websocket_connect, gunicorn_url):
        """Test server-preferred subprotocol selection."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/subprotocol"
        async with await websocket_connect(ws_url, subprotocols=["json", "graphql-ws"]) as ws:
            response = await ws.recv()
            data = json.loads(response)
            # Server prefers graphql-ws
            assert data["selected"] == "graphql-ws"

    async def test_no_subprotocol(self, websocket_connect, gunicorn_url):
        """Test connection without subprotocol."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/subprotocol"
        async with await websocket_connect(ws_url) as ws:
            response = await ws.recv()
            data = json.loads(response)
            assert data["selected"] is None
            assert data["requested"] == []


# ============================================================================
# Close Code Tests
# ============================================================================

@pytest.mark.asyncio
class TestCloseCodes:
    """Test WebSocket close code handling."""

    async def test_normal_close(self, websocket_connect, gunicorn_url):
        """Test normal close (1000)."""
        websockets = pytest.importorskip("websockets")

        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/close?code=1000"
        async with await websocket_connect(ws_url) as ws:
            try:
                await ws.recv()
            except websockets.exceptions.ConnectionClosed as e:
                assert e.code == 1000

    async def test_going_away_close(self, websocket_connect, gunicorn_url):
        """Test going away close (1001)."""
        websockets = pytest.importorskip("websockets")

        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/close?code=1001"
        async with await websocket_connect(ws_url) as ws:
            try:
                await ws.recv()
            except websockets.exceptions.ConnectionClosed as e:
                assert e.code == 1001

    async def test_protocol_error_close(self, websocket_connect, gunicorn_url):
        """Test protocol error close (1002)."""
        websockets = pytest.importorskip("websockets")

        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/close?code=1002"
        async with await websocket_connect(ws_url) as ws:
            try:
                await ws.recv()
            except websockets.exceptions.ConnectionClosed as e:
                assert e.code == 1002

    async def test_close_with_reason(self, websocket_connect, gunicorn_url):
        """Test close with reason message."""
        websockets = pytest.importorskip("websockets")

        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/close?code=1000&reason=goodbye"
        async with await websocket_connect(ws_url) as ws:
            try:
                await ws.recv()
            except websockets.exceptions.ConnectionClosed as e:
                assert e.code == 1000
                assert e.reason == "goodbye"

    async def test_application_close_code(self, websocket_connect, gunicorn_url):
        """Test application-defined close code (4000+)."""
        websockets = pytest.importorskip("websockets")

        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/close?code=4001"
        async with await websocket_connect(ws_url) as ws:
            try:
                await ws.recv()
            except websockets.exceptions.ConnectionClosed as e:
                assert e.code == 4001


# ============================================================================
# Connection Rejection Tests
# ============================================================================

@pytest.mark.asyncio
class TestConnectionRejection:
    """Test WebSocket connection rejection."""

    async def test_reject_connection(self, websocket_connect, gunicorn_url):
        """Test connection rejection."""
        websockets = pytest.importorskip("websockets")

        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/reject"
        # websockets v16+ raises InvalidStatus, older versions raise InvalidStatusCode
        with pytest.raises((websockets.exceptions.InvalidStatus, Exception)):
            async with await websocket_connect(ws_url):
                pass


# ============================================================================
# WebSocket Scope Tests
# ============================================================================

@pytest.mark.asyncio
class TestWebSocketScope:
    """Test WebSocket ASGI scope correctness."""

    async def test_scope_type(self, websocket_connect, gunicorn_url):
        """Test scope type is 'websocket'."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/scope"
        async with await websocket_connect(ws_url) as ws:
            response = await ws.recv()
            scope = json.loads(response)
            assert scope["type"] == "websocket"

    async def test_scope_asgi_version(self, websocket_connect, gunicorn_url):
        """Test scope has ASGI version."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/scope"
        async with await websocket_connect(ws_url) as ws:
            response = await ws.recv()
            scope = json.loads(response)
            assert "asgi" in scope
            assert "version" in scope["asgi"]

    async def test_scope_http_version(self, websocket_connect, gunicorn_url):
        """Test scope has HTTP version."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/scope"
        async with await websocket_connect(ws_url) as ws:
            response = await ws.recv()
            scope = json.loads(response)
            assert scope["http_version"] in ["1.0", "1.1", "2"]

    async def test_scope_scheme(self, websocket_connect, gunicorn_url):
        """Test scope scheme is 'ws'."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/scope"
        async with await websocket_connect(ws_url) as ws:
            response = await ws.recv()
            scope = json.loads(response)
            assert scope["scheme"] == "ws"

    async def test_scope_server(self, websocket_connect, gunicorn_url):
        """Test scope has server info."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/scope"
        async with await websocket_connect(ws_url) as ws:
            response = await ws.recv()
            scope = json.loads(response)
            assert scope["server"] is not None
            assert len(scope["server"]) == 2  # (host, port)

    async def test_scope_client(self, websocket_connect, gunicorn_url):
        """Test scope has client info."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/scope"
        async with await websocket_connect(ws_url) as ws:
            response = await ws.recv()
            scope = json.loads(response)
            assert scope["client"] is not None
            assert len(scope["client"]) == 2  # (host, port)

    async def test_scope_headers(self, websocket_connect, gunicorn_url):
        """Test scope has headers."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/scope"
        async with await websocket_connect(
            ws_url,
            additional_headers={"X-Custom-Header": "test-value"}
        ) as ws:
            response = await ws.recv()
            scope = json.loads(response)
            headers = {name.lower(): value for name, value in scope["headers"]}
            assert "x-custom-header" in headers
            assert headers["x-custom-header"] == "test-value"


# ============================================================================
# Large Message Tests
# ============================================================================

@pytest.mark.asyncio
class TestLargeMessages:
    """Test large WebSocket message handling."""

    async def test_receive_large_message(self, websocket_connect, gunicorn_url):
        """Test receiving large message from server."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/large?size=65536"
        async with await websocket_connect(ws_url) as ws:
            response = await ws.recv()
            assert len(response) == 65536
            assert response == "x" * 65536

    async def test_send_large_message(self, websocket_connect, gunicorn_url):
        """Test sending large message to server."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/large?size=1024"
        async with await websocket_connect(ws_url) as ws:
            # First receive server's large message
            _ = await ws.recv()

            # Send our large message
            large_data = "y" * 100000
            await ws.send(large_data)

            response = await ws.recv()
            data = json.loads(response)
            assert data["received_length"] == 100000

    async def test_various_sizes(self, websocket_connect, gunicorn_url):
        """Test various message sizes."""
        sizes = [1, 100, 1000, 10000, 50000]

        for size in sizes:
            ws_url = gunicorn_url.replace("http://", "ws://") + f"/ws/large?size={size}"
            async with await websocket_connect(ws_url) as ws:
                response = await ws.recv()
                assert len(response) == size, f"Expected {size}, got {len(response)}"


# ============================================================================
# Broadcast/Multiple Message Tests
# ============================================================================

@pytest.mark.asyncio
class TestBroadcast:
    """Test broadcast-style multiple message sending."""

    async def test_broadcast_default_count(self, websocket_connect, gunicorn_url):
        """Test broadcast with default count (3)."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/broadcast"
        async with await websocket_connect(ws_url) as ws:
            await ws.send("test message")

            responses = []
            for _ in range(3):
                response = await ws.recv()
                responses.append(json.loads(response))

            assert len(responses) == 3
            for i, resp in enumerate(responses):
                assert resp["copy"] == i + 1
                assert resp["of"] == 3
                assert resp["message"] == "test message"

    async def test_broadcast_custom_count(self, websocket_connect, gunicorn_url):
        """Test broadcast with custom count."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/broadcast?count=5"
        async with await websocket_connect(ws_url) as ws:
            await ws.send("hello")

            responses = []
            for _ in range(5):
                response = await ws.recv()
                responses.append(json.loads(response))

            assert len(responses) == 5


# ============================================================================
# Delayed Response Tests
# ============================================================================

@pytest.mark.asyncio
class TestDelayedResponses:
    """Test WebSocket delayed responses."""

    async def test_delayed_response(self, websocket_connect, gunicorn_url):
        """Test delayed response."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/delay?seconds=0.5"
        async with await websocket_connect(ws_url) as ws:
            import time
            start = time.time()
            await ws.send("ping")
            response = await asyncio.wait_for(ws.recv(), timeout=5.0)
            elapsed = time.time() - start

            assert elapsed >= 0.4  # Allow some tolerance
            data = json.loads(response)
            assert data["delayed_by"] == 0.5
            assert data["message"] == "ping"

    async def test_minimal_delay(self, websocket_connect, gunicorn_url):
        """Test with minimal delay."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/delay?seconds=0.1"
        async with await websocket_connect(ws_url) as ws:
            await ws.send("quick")
            response = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(response)
            assert data["delayed_by"] == 0.1


# ============================================================================
# Fragmented Message Tests
# ============================================================================

@pytest.mark.asyncio
class TestFragmentedMessages:
    """Test fragmented WebSocket message handling."""

    async def test_fragmented_endpoint(self, websocket_connect, gunicorn_url):
        """Test fragmented message info endpoint."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/fragmented"
        async with await websocket_connect(ws_url) as ws:
            # First receive info message
            info = await ws.recv()
            data = json.loads(info)
            assert "info" in data

    async def test_message_reassembly(self, websocket_connect, gunicorn_url):
        """Test that messages are reassembled correctly."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/fragmented"
        async with await websocket_connect(ws_url) as ws:
            # Skip info message
            await ws.recv()

            # Send message
            await ws.send("complete message")
            response = await ws.recv()
            data = json.loads(response)

            assert data["received"] == "complete message"
            assert data["length"] == len("complete message")
            assert data["type"] == "text"


# ============================================================================
# Proxy WebSocket Tests
# ============================================================================

@pytest.mark.asyncio
class TestProxyWebSocket:
    """Test WebSocket through nginx proxy."""

    async def test_proxy_echo(self, websocket_connect, nginx_url):
        """Test echo through proxy."""
        ws_url = nginx_url.replace("http://", "ws://") + "/ws/echo"
        async with await websocket_connect(ws_url) as ws:
            await ws.send("proxied message")
            response = await ws.recv()
            assert response == "proxied message"

    async def test_proxy_binary(self, websocket_connect, nginx_url):
        """Test binary echo through proxy."""
        ws_url = nginx_url.replace("http://", "ws://") + "/ws/echo-binary"
        async with await websocket_connect(ws_url) as ws:
            data = b"\x00\x01\x02\x03"
            await ws.send(data)
            response = await ws.recv()
            assert response == data

    async def test_proxy_subprotocol(self, websocket_connect, nginx_url):
        """Test subprotocol through proxy."""
        ws_url = nginx_url.replace("http://", "ws://") + "/ws/subprotocol"
        async with await websocket_connect(ws_url, subprotocols=["json"]) as ws:
            response = await ws.recv()
            data = json.loads(response)
            assert data["selected"] == "json"

    async def test_proxy_scope(self, websocket_connect, nginx_url):
        """Test scope through proxy."""
        ws_url = nginx_url.replace("http://", "ws://") + "/ws/scope"
        async with await websocket_connect(ws_url) as ws:
            response = await ws.recv()
            scope = json.loads(response)
            assert scope["type"] == "websocket"
            assert scope["path"] == "/ws/scope"


# ============================================================================
# HTTPS WebSocket Tests
# ============================================================================

@pytest.mark.ssl
@pytest.mark.asyncio
class TestSecureWebSocket:
    """Test WebSocket over SSL/TLS."""

    async def test_wss_connection(self, websocket_connect, gunicorn_ssl_url):
        """Test WSS connection."""
        ws_url = gunicorn_ssl_url.replace("https://", "wss://") + "/ws/echo"
        async with await websocket_connect(ws_url) as ws:
            await ws.send("secure message")
            response = await ws.recv()
            assert response == "secure message"

    async def test_wss_scope_scheme(self, websocket_connect, gunicorn_ssl_url):
        """Test WSS scope has correct scheme."""
        ws_url = gunicorn_ssl_url.replace("https://", "wss://") + "/ws/scope"
        async with await websocket_connect(ws_url) as ws:
            response = await ws.recv()
            scope = json.loads(response)
            assert scope["scheme"] == "wss"

    async def test_wss_through_proxy(self, websocket_connect, nginx_ssl_url):
        """Test WSS through nginx proxy."""
        ws_url = nginx_ssl_url.replace("https://", "wss://") + "/ws/echo"
        async with await websocket_connect(ws_url) as ws:
            await ws.send("secure proxied")
            response = await ws.recv()
            assert response == "secure proxied"


# ============================================================================
# Concurrent Connection Tests
# ============================================================================

@pytest.mark.asyncio
class TestConcurrentConnections:
    """Test concurrent WebSocket connections."""

    async def test_multiple_concurrent_connections(self, websocket_connect, gunicorn_url):
        """Test multiple concurrent WebSocket connections."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/echo"

        async def echo_task(task_id):
            async with await websocket_connect(ws_url) as ws:
                message = f"task-{task_id}"
                await ws.send(message)
                response = await ws.recv()
                assert response == message
                return task_id

        # Run 10 concurrent connections
        tasks = [echo_task(i) for i in range(10)]
        results = await asyncio.gather(*tasks)
        assert len(results) == 10
        assert set(results) == set(range(10))

    async def test_concurrent_different_endpoints(self, websocket_connect, gunicorn_url):
        """Test concurrent connections to different endpoints."""
        base_ws = gunicorn_url.replace("http://", "ws://")

        async def echo_text():
            async with await websocket_connect(base_ws + "/ws/echo") as ws:
                await ws.send("text")
                return await ws.recv()

        async def echo_binary():
            async with await websocket_connect(base_ws + "/ws/echo-binary") as ws:
                await ws.send(b"binary")
                return await ws.recv()

        async def get_scope():
            async with await websocket_connect(base_ws + "/ws/scope") as ws:
                return await ws.recv()

        results = await asyncio.gather(
            echo_text(),
            echo_binary(),
            get_scope(),
        )

        assert results[0] == "text"
        assert results[1] == b"binary"
        scope = json.loads(results[2])
        assert scope["type"] == "websocket"


# ============================================================================
# Edge Cases
# ============================================================================

@pytest.mark.asyncio
class TestWebSocketEdgeCases:
    """Test WebSocket edge cases."""

    async def test_unknown_path(self, websocket_connect, gunicorn_url):
        """Test connection to unknown path."""
        websockets = pytest.importorskip("websockets")

        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/unknown-path"
        async with await websocket_connect(ws_url) as ws:
            response = await ws.recv()
            data = json.loads(response)
            assert data["error"] == "Unknown path"

            # Connection will be closed
            try:
                await ws.recv()
            except websockets.exceptions.ConnectionClosed:
                pass

    async def test_special_characters_in_message(self, websocket_connect, gunicorn_url):
        """Test messages with special characters."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/echo"
        async with await websocket_connect(ws_url) as ws:
            special = "!@#$%^&*()_+-=[]{}|;':\",./<>?\n\t\r"
            await ws.send(special)
            response = await ws.recv()
            assert response == special

    async def test_null_bytes_in_binary(self, websocket_connect, gunicorn_url):
        """Test binary message with null bytes."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/echo-binary"
        async with await websocket_connect(ws_url) as ws:
            data = b"\x00\x00\x00"
            await ws.send(data)
            response = await ws.recv()
            assert response == data

    async def test_json_message(self, websocket_connect, gunicorn_url):
        """Test JSON in text message."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/echo"
        async with await websocket_connect(ws_url) as ws:
            payload = json.dumps({"key": "value", "number": 42, "list": [1, 2, 3]})
            await ws.send(payload)
            response = await ws.recv()
            assert json.loads(response) == {"key": "value", "number": 42, "list": [1, 2, 3]}

    async def test_rapid_close_reconnect(self, websocket_connect, gunicorn_url):
        """Test rapid close and reconnect."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/echo"

        for i in range(5):
            async with await websocket_connect(ws_url) as ws:
                await ws.send(f"iteration {i}")
                response = await ws.recv()
                assert response == f"iteration {i}"
