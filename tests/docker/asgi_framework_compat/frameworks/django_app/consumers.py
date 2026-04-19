"""
Django Channels WebSocket consumers for ASGI compatibility testing.
"""

import json
from channels.generic.websocket import AsyncWebsocketConsumer


def serialize_scope(scope: dict) -> dict:
    """Convert ASGI scope to JSON-serializable dict."""
    result = {}
    for key, value in scope.items():
        if key == "headers":
            result[key] = [
                [h[0].decode("latin-1"), h[1].decode("latin-1")] for h in value
            ]
        elif key == "query_string":
            result[key] = value.decode("latin-1") if value else ""
        elif key == "server":
            result[key] = list(value) if value else None
        elif key == "client":
            result[key] = list(value) if value else None
        elif key == "asgi":
            result[key] = dict(value)
        elif key in ("state", "app", "url_route", "path_remaining"):
            continue
        elif isinstance(value, bytes):
            result[key] = value.decode("latin-1")
        else:
            try:
                json.dumps(value)
                result[key] = value
            except (TypeError, ValueError):
                continue
    return result


class EchoConsumer(AsyncWebsocketConsumer):
    """Echo text messages."""

    async def connect(self):
        await self.accept()

    async def receive(self, text_data=None, bytes_data=None):
        if text_data:
            await self.send(text_data=text_data)

    async def disconnect(self, close_code):
        pass


class EchoBinaryConsumer(AsyncWebsocketConsumer):
    """Echo binary messages."""

    async def connect(self):
        await self.accept()

    async def receive(self, text_data=None, bytes_data=None):
        if bytes_data:
            await self.send(bytes_data=bytes_data)

    async def disconnect(self, close_code):
        pass


class ScopeConsumer(AsyncWebsocketConsumer):
    """Send WebSocket scope on connect."""

    async def connect(self):
        await self.accept()
        scope_data = serialize_scope(self.scope)
        await self.send(text_data=json.dumps(scope_data))
        await self.close()

    async def disconnect(self, close_code):
        pass


class SubprotocolConsumer(AsyncWebsocketConsumer):
    """Subprotocol negotiation."""

    async def connect(self):
        requested = self.scope.get("subprotocols", [])
        selected = requested[0] if requested else None
        await self.accept(subprotocol=selected)
        await self.send(text_data=json.dumps({
            "requested": requested,
            "selected": selected
        }))
        await self.close()

    async def disconnect(self, close_code):
        pass


class CloseConsumer(AsyncWebsocketConsumer):
    """Close with specific code."""

    async def connect(self):
        await self.accept()
        query_string = self.scope.get("query_string", b"").decode()
        code = 1000
        for param in query_string.split("&"):
            if param.startswith("code="):
                code = int(param.split("=")[1])
                break
        await self.close(code=code)

    async def disconnect(self, close_code):
        pass
