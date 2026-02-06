#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Main ASGI application for compliance testing.

Routes requests to appropriate test applications based on path prefix.
This is the primary entry point for Docker-based integration tests.
"""

import json
import time

from .http_app import app as http_app
from .websocket_app import app as websocket_app
from .streaming_app import app as streaming_app
from .lifespan_app import app as lifespan_app
from .framework_apps import combined_app as framework_app


# Global state for lifespan
_app_state = {
    "started": False,
    "startup_time": None,
}


async def app(scope, receive, send):
    """Main routing application.

    Routes based on path prefix:
    - /http/* -> HTTP test endpoints
    - /ws/* -> WebSocket test endpoints
    - /stream/* -> Streaming test endpoints
    - /lifespan/* -> Lifespan test endpoints
    - /framework/* -> Framework integration tests
    - / -> Root with info
    - /health -> Health check
    """
    if scope["type"] == "lifespan":
        await handle_lifespan(scope, receive, send)
        return

    path = scope.get("path", "")

    # WebSocket handling - check scope type
    if scope["type"] == "websocket":
        if path.startswith("/ws/"):
            await websocket_app(scope, receive, send)
        elif path.startswith("/framework/"):
            # Route to framework WebSocket handlers
            new_scope = dict(scope)
            new_scope["path"] = path[10:] or "/"
            new_scope["raw_path"] = new_scope["path"].encode("latin-1")
            await framework_app(new_scope, receive, send)
        else:
            await websocket_app(scope, receive, send)
        return

    # HTTP routing
    if scope["type"] == "http":
        if path == "/" or path == "":
            await handle_root(scope, receive, send)
        elif path == "/health":
            await handle_health(scope, receive, send)
        elif path == "/info":
            await handle_info(scope, receive, send)
        elif path.startswith("/http/"):
            # Route to HTTP app, stripping prefix
            new_scope = dict(scope)
            new_scope["path"] = path[5:] or "/"
            new_scope["raw_path"] = new_scope["path"].encode("latin-1")
            await http_app(new_scope, receive, send)
        elif path.startswith("/stream/"):
            # Route to streaming app, stripping prefix
            new_scope = dict(scope)
            new_scope["path"] = path[7:] or "/"
            new_scope["raw_path"] = new_scope["path"].encode("latin-1")
            await streaming_app(new_scope, receive, send)
        elif path.startswith("/lifespan/"):
            # Route to lifespan app, stripping prefix
            new_scope = dict(scope)
            new_scope["path"] = path[9:] or "/"
            new_scope["raw_path"] = new_scope["path"].encode("latin-1")
            await lifespan_app(new_scope, receive, send)
        elif path.startswith("/framework/"):
            # Route to framework app, stripping prefix
            new_scope = dict(scope)
            new_scope["path"] = path[10:] or "/"
            new_scope["raw_path"] = new_scope["path"].encode("latin-1")
            await framework_app(new_scope, receive, send)
        else:
            # Try direct routing to http_app for convenience
            await http_app(scope, receive, send)


async def handle_lifespan(scope, receive, send):
    """Handle ASGI lifespan events."""
    global _app_state

    while True:
        message = await receive()

        if message["type"] == "lifespan.startup":
            _app_state["started"] = True
            _app_state["startup_time"] = time.time()

            # Initialize state if available
            if "state" in scope:
                scope["state"]["main_app_started"] = True
                scope["state"]["startup_time"] = _app_state["startup_time"]

            await send({"type": "lifespan.startup.complete"})

        elif message["type"] == "lifespan.shutdown":
            _app_state["started"] = False

            if "state" in scope:
                scope["state"]["main_app_started"] = False

            await send({"type": "lifespan.shutdown.complete"})
            return


async def handle_root(scope, receive, send):
    """Root endpoint with routing information."""
    await drain_body(receive)

    info = {
        "app": "ASGI Compliance Testbed",
        "version": "1.0.0",
        "routes": {
            "/": "This info page",
            "/health": "Health check endpoint",
            "/info": "Detailed server info",
            "/http/*": "HTTP test endpoints",
            "/ws/*": "WebSocket test endpoints",
            "/stream/*": "Streaming test endpoints",
            "/lifespan/*": "Lifespan protocol tests",
            "/framework/*": "Framework integration tests",
        },
        "http_endpoints": [
            "/http/echo", "/http/headers", "/http/scope",
            "/http/status?code=XXX", "/http/large", "/http/method",
            "/http/query", "/http/post-json", "/http/delay",
            "/http/early-hints", "/http/cookies", "/http/redirect",
        ],
        "websocket_endpoints": [
            "/ws/echo", "/ws/echo-binary", "/ws/subprotocol",
            "/ws/close?code=XXX", "/ws/scope", "/ws/reject",
            "/ws/ping", "/ws/broadcast", "/ws/large", "/ws/delay",
        ],
        "streaming_endpoints": [
            "/stream/streaming", "/stream/sse", "/stream/chunked",
            "/stream/slow-stream", "/stream/large-stream",
            "/stream/ndjson", "/stream/echo-stream",
        ],
        "lifespan_endpoints": [
            "/lifespan/state", "/lifespan/lifespan-info",
            "/lifespan/counter", "/lifespan/health",
        ],
        "framework_endpoints": [
            "/framework/starlette/*", "/framework/fastapi/*",
        ],
    }

    body = json.dumps(info, indent=2).encode("utf-8")

    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({
        "type": "http.response.body",
        "body": body,
        "more_body": False,
    })


async def handle_health(scope, receive, send):
    """Health check endpoint."""
    await drain_body(receive)

    body = b"OK"

    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            (b"content-type", b"text/plain"),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({
        "type": "http.response.body",
        "body": body,
        "more_body": False,
    })


async def handle_info(scope, receive, send):
    """Detailed server information."""
    await drain_body(receive)

    info = {
        "started": _app_state["started"],
        "startup_time": _app_state["startup_time"],
        "uptime": time.time() - _app_state["startup_time"] if _app_state["startup_time"] else None,
        "scope_state_available": "state" in scope,
        "asgi": scope.get("asgi", {}),
        "server": list(scope["server"]) if scope.get("server") else None,
    }

    if "state" in scope:
        info["state_keys"] = list(scope["state"].keys())

    body = json.dumps(info, indent=2).encode("utf-8")

    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({
        "type": "http.response.body",
        "body": body,
        "more_body": False,
    })


async def drain_body(receive):
    """Drain the request body."""
    while True:
        message = await receive()
        if not message.get("more_body", False):
            break
