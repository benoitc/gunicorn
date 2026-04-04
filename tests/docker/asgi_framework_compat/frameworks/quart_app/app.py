"""
Quart ASGI Application for Compatibility Testing

Implements the contract endpoints for ASGI 3.0 compliance testing.
Quart is a Flask-like async framework built on ASGI.
"""

import asyncio
import json
import time

from quart import Quart, request, websocket, Response, make_response


app = Quart(__name__)

# Lifespan state
lifespan_state = {
    "startup_called": False,
    "startup_time": None,
    "counter": 0,
    "custom_data": {},
}


@app.before_serving
async def startup():
    """Startup handler."""
    lifespan_state["startup_called"] = True
    lifespan_state["startup_time"] = time.time()
    lifespan_state["custom_data"]["initialized"] = True


@app.after_serving
async def shutdown():
    """Shutdown handler."""
    lifespan_state["shutdown_called"] = True


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
        elif key in ("state", "app", "_quart"):
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


# HTTP Endpoints
@app.route("/health")
async def health():
    """Health check endpoint."""
    return "OK", 200


@app.route("/scope")
async def scope_endpoint():
    """Return full ASGI scope as JSON."""
    # Access the ASGI scope via request
    scope = request.scope
    scope_data = serialize_scope(scope)
    return scope_data


@app.route("/echo", methods=["POST"])
async def echo():
    """Echo request body back."""
    body = await request.get_data()
    content_type = request.headers.get("content-type", "application/octet-stream")
    response = await make_response(body)
    response.headers["Content-Type"] = content_type
    return response


@app.route("/headers")
async def headers_endpoint():
    """Return request headers as JSON."""
    # Normalize header keys to lowercase for consistency
    headers_dict = {k.lower(): v for k, v in request.headers.items()}
    return headers_dict


@app.route("/status/<int:code>")
async def status_endpoint(code: int):
    """Return specific HTTP status code."""
    return f"Status: {code}", code


@app.route("/streaming")
async def streaming():
    """Chunked streaming response."""

    async def generate():
        for i in range(10):
            yield f"chunk-{i}\n"
            await asyncio.sleep(0.01)

    return generate(), 200, {"Content-Type": "text/plain"}


@app.route("/sse")
async def sse():
    """Server-Sent Events endpoint."""

    async def generate():
        for i in range(5):
            yield f"event: message\ndata: {json.dumps({'count': i})}\n\n"
            await asyncio.sleep(0.01)
        yield "event: done\ndata: {}\n\n"

    return generate(), 200, {"Content-Type": "text/event-stream", "Cache-Control": "no-cache"}


@app.route("/large")
async def large():
    """Large response body."""
    size = request.args.get("size", 1024, type=int)
    # Cap at 10MB for safety
    size = min(size, 10 * 1024 * 1024)
    response = await make_response(b"x" * size)
    response.headers["Content-Type"] = "application/octet-stream"
    return response


@app.route("/delay")
async def delay():
    """Delayed response."""
    seconds = request.args.get("seconds", 1.0, type=float)
    # Cap at 30 seconds
    seconds = min(seconds, 30)
    await asyncio.sleep(seconds)
    return f"Delayed {seconds} seconds"


@app.route("/lifespan/state")
async def lifespan_state_endpoint():
    """Return lifespan startup state."""
    return lifespan_state


@app.route("/lifespan/counter")
async def lifespan_counter():
    """Increment and return counter."""
    lifespan_state["counter"] += 1
    return {"counter": lifespan_state["counter"]}


# WebSocket Endpoints
@app.websocket("/ws/echo")
async def ws_echo():
    """Echo text messages."""
    while True:
        message = await websocket.receive()
        await websocket.send(message)


@app.websocket("/ws/echo-binary")
async def ws_echo_binary():
    """Echo binary messages."""
    while True:
        message = await websocket.receive()
        await websocket.send(message)


@app.websocket("/ws/scope")
async def ws_scope():
    """Send WebSocket scope on connect."""
    scope_data = serialize_scope(websocket.scope)
    await websocket.send_json(scope_data)


@app.websocket("/ws/subprotocol")
async def ws_subprotocol():
    """Subprotocol negotiation."""
    requested = websocket.scope.get("subprotocols", [])
    selected = requested[0] if requested else None
    # Note: Quart handles subprotocol via accept() but we need to check how
    await websocket.send_json({"requested": requested, "selected": selected})


@app.websocket("/ws/close")
async def ws_close():
    """Close with specific code."""
    query_string = websocket.scope.get("query_string", b"").decode()
    code = 1000
    for param in query_string.split("&"):
        if param.startswith("code="):
            code = int(param.split("=")[1])
            break
    await websocket.accept()
    await websocket.close(code)
