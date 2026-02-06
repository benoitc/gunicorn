#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Lifespan test application for ASGI compliance testing.

Tests the ASGI lifespan protocol including startup, shutdown,
and state sharing between lifespan and request handlers.
"""

import json
import os
import time


# Module-level state to track lifespan events (fallback if scope state unavailable)
_lifespan_state = {
    "startup_called": False,
    "startup_complete": False,
    "shutdown_called": False,
    "startup_time": None,
    "startup_count": 0,
    "request_count": 0,
}


async def app(scope, receive, send):
    """Main ASGI application with lifespan support."""
    if scope["type"] == "lifespan":
        await handle_lifespan(scope, receive, send)
        return

    if scope["type"] != "http":
        return

    path = scope["path"]

    if path == "/":
        await handle_root(scope, receive, send)
    elif path == "/state":
        await handle_state(scope, receive, send)
    elif path == "/lifespan-info":
        await handle_lifespan_info(scope, receive, send)
    elif path == "/counter":
        await handle_counter(scope, receive, send)
    elif path == "/health":
        await handle_health(scope, receive, send)
    else:
        await handle_not_found(scope, receive, send)


async def handle_lifespan(scope, receive, send):
    """Handle ASGI lifespan protocol."""
    global _lifespan_state

    while True:
        message = await receive()

        if message["type"] == "lifespan.startup":
            _lifespan_state["startup_called"] = True
            _lifespan_state["startup_time"] = time.time()
            _lifespan_state["startup_count"] += 1

            # Check for failure trigger via environment
            if os.environ.get("LIFESPAN_FAIL_STARTUP") == "1":
                await send({
                    "type": "lifespan.startup.failed",
                    "message": "Startup failed (triggered by environment)",
                })
                return

            # Initialize state if available
            if "state" in scope:
                scope["state"]["lifespan_started"] = True
                scope["state"]["startup_time"] = _lifespan_state["startup_time"]
                scope["state"]["db_connection"] = "simulated_connection"
                scope["state"]["cache"] = {}
                scope["state"]["request_count"] = 0

            _lifespan_state["startup_complete"] = True

            await send({"type": "lifespan.startup.complete"})

        elif message["type"] == "lifespan.shutdown":
            _lifespan_state["shutdown_called"] = True

            # Cleanup state if available
            if "state" in scope:
                scope["state"]["lifespan_stopped"] = True
                scope["state"]["shutdown_time"] = time.time()

            await send({"type": "lifespan.shutdown.complete"})
            return


async def handle_root(scope, receive, send):
    """Root endpoint."""
    await drain_body(receive)

    _lifespan_state["request_count"] += 1

    # Increment request count in state if available
    if "state" in scope and "request_count" in scope["state"]:
        scope["state"]["request_count"] += 1

    body = b"Lifespan Test App"

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


async def handle_state(scope, receive, send):
    """Return the current state (from scope or module-level)."""
    await drain_body(receive)

    _lifespan_state["request_count"] += 1

    # Collect state information
    state_info = {
        "module_state": {
            "startup_called": _lifespan_state["startup_called"],
            "startup_complete": _lifespan_state["startup_complete"],
            "shutdown_called": _lifespan_state["shutdown_called"],
            "startup_time": _lifespan_state["startup_time"],
            "startup_count": _lifespan_state["startup_count"],
            "request_count": _lifespan_state["request_count"],
        },
        "scope_state_available": "state" in scope,
    }

    if "state" in scope:
        # Serialize scope state (only simple types)
        scope_state = {}
        for key, value in scope["state"].items():
            try:
                json.dumps(value)  # Test if serializable
                scope_state[key] = value
            except (TypeError, ValueError):
                scope_state[key] = str(type(value).__name__)

        state_info["scope_state"] = scope_state

    body = json.dumps(state_info, indent=2, default=str).encode("utf-8")

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


async def handle_lifespan_info(scope, receive, send):
    """Return lifespan-specific information."""
    await drain_body(receive)

    info = {
        "lifespan_supported": True,
        "startup_complete": _lifespan_state["startup_complete"],
        "scope_state_present": "state" in scope,
        "uptime_seconds": None,
    }

    if _lifespan_state["startup_time"]:
        info["uptime_seconds"] = time.time() - _lifespan_state["startup_time"]

    if "state" in scope:
        info["state_keys"] = list(scope["state"].keys())
        if "db_connection" in scope["state"]:
            info["db_connection_status"] = "active"

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


async def handle_counter(scope, receive, send):
    """Increment and return a counter (tests state persistence)."""
    await drain_body(receive)

    _lifespan_state["request_count"] += 1

    counter_value = _lifespan_state["request_count"]

    # Also track in scope state if available
    if "state" in scope:
        scope["state"]["request_count"] = scope["state"].get("request_count", 0) + 1
        counter_value = scope["state"]["request_count"]

    body = json.dumps({
        "counter": counter_value,
        "source": "scope_state" if "state" in scope else "module_state",
    }).encode("utf-8")

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
    """Health check that verifies lifespan startup completed."""
    await drain_body(receive)

    if not _lifespan_state["startup_complete"]:
        body = b"Lifespan not started"
        status = 503
    else:
        body = b"OK"
        status = 200

    await send({
        "type": "http.response.start",
        "status": status,
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


async def handle_not_found(scope, receive, send):
    """Handle 404 Not Found."""
    await drain_body(receive)
    await send_error(send, 404, "Not Found")


async def drain_body(receive):
    """Drain the request body."""
    while True:
        message = await receive()
        if not message.get("more_body", False):
            break


async def send_error(send, status, message):
    """Send an error response."""
    body = message.encode("utf-8")

    await send({
        "type": "http.response.start",
        "status": status,
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


# Application factory for explicit lifespan support
def create_app():
    """Create the ASGI application."""
    return app
