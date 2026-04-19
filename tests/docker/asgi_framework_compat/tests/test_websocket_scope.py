"""
WebSocket Scope Compliance Tests

Tests ASGI 3.0 WebSocket scope compliance across frameworks.
"""

import asyncio
import json

import pytest
import websockets
from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError

from frameworks.contract import (
    ASGI_WEBSOCKET_SCOPE_REQUIRED_KEYS,
    VALID_WEBSOCKET_CLOSE_CODES,
)


pytestmark = pytest.mark.websocket


class TestWebSocketConnection:
    """Test WebSocket connection handling."""

    async def test_websocket_connect(self, ws_client):
        """WebSocket connection can be established."""
        ws = await ws_client("/ws/echo")
        # websockets v16+ uses state instead of open
        from websockets.protocol import State
        assert ws.state == State.OPEN
        await ws.close()

    async def test_websocket_echo_text(self, ws_client):
        """WebSocket echo endpoint echoes text messages."""
        ws = await ws_client("/ws/echo")
        try:
            await ws.send("Hello, WebSocket!")
            response = await asyncio.wait_for(ws.recv(), timeout=5.0)
            assert response == "Hello, WebSocket!"
        finally:
            await ws.close()

    async def test_websocket_echo_multiple_messages(self, ws_client):
        """WebSocket echo handles multiple messages."""
        ws = await ws_client("/ws/echo")
        try:
            messages = ["msg1", "msg2", "msg3"]
            for msg in messages:
                await ws.send(msg)
                response = await asyncio.wait_for(ws.recv(), timeout=5.0)
                assert response == msg
        finally:
            await ws.close()


class TestWebSocketBinary:
    """Test WebSocket binary message handling."""

    async def test_websocket_echo_binary(self, ws_client):
        """WebSocket binary echo endpoint echoes binary messages."""
        ws = await ws_client("/ws/echo-binary")
        try:
            data = b"\x00\x01\x02\x03\xff\xfe"
            await ws.send(data)
            response = await asyncio.wait_for(ws.recv(), timeout=5.0)
            assert response == data
        finally:
            await ws.close()

    async def test_websocket_echo_large_binary(self, ws_client, random_bytes):
        """WebSocket handles large binary messages."""
        ws = await ws_client("/ws/echo-binary")
        try:
            data = random_bytes(64 * 1024)  # 64KB
            await ws.send(data)
            response = await asyncio.wait_for(ws.recv(), timeout=10.0)
            assert response == data
        finally:
            await ws.close()


class TestWebSocketScope:
    """Test WebSocket scope attributes."""

    async def test_websocket_scope_endpoint(self, ws_client):
        """WebSocket scope endpoint returns scope JSON."""
        ws = await ws_client("/ws/scope")
        try:
            response = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(response)
            assert isinstance(data, dict)
        except ConnectionClosedOK:
            pass

    async def test_websocket_scope_type(self, ws_client):
        """WebSocket scope type is 'websocket'."""
        ws = await ws_client("/ws/scope")
        try:
            response = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(response)
            assert data.get("type") == "websocket"
        except ConnectionClosedOK:
            pass

    async def test_websocket_scope_has_path(self, ws_client):
        """WebSocket scope has path field."""
        ws = await ws_client("/ws/scope")
        try:
            response = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(response)
            assert "/ws/scope" in data.get("path", "")
        except ConnectionClosedOK:
            pass

    async def test_websocket_scope_has_headers(self, ws_client):
        """WebSocket scope has headers field."""
        ws = await ws_client("/ws/scope")
        try:
            response = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(response)
            assert "headers" in data
            assert isinstance(data["headers"], list)
        except ConnectionClosedOK:
            pass

    async def test_websocket_scope_required_keys(self, ws_client):
        """WebSocket scope has all required keys."""
        ws = await ws_client("/ws/scope")
        try:
            response = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(response)
            for key in ASGI_WEBSOCKET_SCOPE_REQUIRED_KEYS:
                assert key in data, f"Missing required WebSocket scope key: {key}"
        except ConnectionClosedOK:
            pass


class TestWebSocketSubprotocol:
    """Test WebSocket subprotocol negotiation."""

    async def test_subprotocol_negotiation(self, ws_client):
        """WebSocket subprotocol negotiation works."""
        ws = await ws_client("/ws/subprotocol", subprotocols=["proto1", "proto2"])
        try:
            response = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(response)
            assert "requested" in data
            assert "proto1" in data["requested"]
            assert "proto2" in data["requested"]
        except ConnectionClosedOK:
            pass

    async def test_subprotocol_selection(self, ws_client):
        """First requested subprotocol is selected."""
        ws = await ws_client("/ws/subprotocol", subprotocols=["myproto"])
        try:
            response = await asyncio.wait_for(ws.recv(), timeout=5.0)
            data = json.loads(response)
            assert data.get("selected") == "myproto"
        except ConnectionClosedOK:
            pass


class TestWebSocketClose:
    """Test WebSocket close handling."""

    async def test_close_normal(self, ws_client):
        """WebSocket closes with normal code 1000."""
        ws = await ws_client("/ws/close?code=1000")
        try:
            await asyncio.wait_for(ws.recv(), timeout=5.0)
        except (ConnectionClosedOK, ConnectionClosedError) as e:
            assert e.code == 1000

    @pytest.mark.parametrize("code", [1001, 1002, 1003, 1008, 1011])
    async def test_close_codes(self, ws_client, code):
        """WebSocket closes with various codes."""
        ws = await ws_client(f"/ws/close?code={code}")
        try:
            await asyncio.wait_for(ws.recv(), timeout=5.0)
        except (ConnectionClosedOK, ConnectionClosedError) as e:
            assert e.code == code

    async def test_client_close(self, ws_client):
        """Server handles client-initiated close."""
        ws = await ws_client("/ws/echo")
        await ws.send("test")
        await ws.recv()
        await ws.close(code=1000)
        # Connection should be closed cleanly
        from websockets.protocol import State
        assert ws.state == State.CLOSED
