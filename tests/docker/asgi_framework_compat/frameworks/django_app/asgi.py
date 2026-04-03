"""
ASGI config for Django compatibility testing.
"""

import os
import time

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")

import django
django.setup()

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application
from routing import websocket_urlpatterns

# Lifespan state - shared across the application
lifespan_state = {
    "startup_called": False,
    "startup_time": None,
    "counter": 0,
    "custom_data": {},
}


class LifespanMiddleware:
    """Custom lifespan handler for Django."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    lifespan_state["startup_called"] = True
                    lifespan_state["startup_time"] = time.time()
                    lifespan_state["custom_data"]["initialized"] = True
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    lifespan_state["shutdown_called"] = True
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        else:
            # Make lifespan_state available to views
            scope["lifespan_state"] = lifespan_state
            await self.app(scope, receive, send)


# Get Django ASGI application
django_asgi_app = get_asgi_application()

# Combine HTTP and WebSocket routing
application = LifespanMiddleware(
    ProtocolTypeRouter({
        "http": django_asgi_app,
        "websocket": URLRouter(websocket_urlpatterns),
    })
)
