"""
WebSocket routing for Django Channels.
"""

from django.urls import path
from consumers import (
    EchoConsumer,
    EchoBinaryConsumer,
    ScopeConsumer,
    SubprotocolConsumer,
    CloseConsumer,
)

websocket_urlpatterns = [
    path("ws/echo", EchoConsumer.as_asgi()),
    path("ws/echo-binary", EchoBinaryConsumer.as_asgi()),
    path("ws/scope", ScopeConsumer.as_asgi()),
    path("ws/subprotocol", SubprotocolConsumer.as_asgi()),
    path("ws/close", CloseConsumer.as_asgi()),
]
