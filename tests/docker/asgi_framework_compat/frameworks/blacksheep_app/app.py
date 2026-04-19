"""
BlackSheep ASGI Application for Compatibility Testing

Implements the contract endpoints for ASGI 3.0 compliance testing.
BlackSheep is a high-performance ASGI framework.
"""

import asyncio
import json
import time
from typing import Any

from blacksheep import Application, Request, WebSocket, StreamedContent, Content
from blacksheep.server.responses import Response, text, json as json_resp


app = Application()

# Lifespan state
lifespan_state = {
    "startup_called": False,
    "startup_time": None,
    "counter": 0,
    "custom_data": {},
}


@app.on_start
async def on_startup(application: Application) -> None:
    """Startup handler."""
    lifespan_state["startup_called"] = True
    lifespan_state["startup_time"] = time.time()
    lifespan_state["custom_data"]["initialized"] = True


@app.on_stop
async def on_shutdown(application: Application) -> None:
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
        elif key in ("state", "app", "_blacksheep"):
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
@app.router.get("/health")
async def health(request: Request) -> Response:
    """Health check endpoint."""
    return text("OK")


@app.router.get("/scope")
async def scope_endpoint(request: Request) -> Response:
    """Return full ASGI scope as JSON."""
    scope_data = serialize_scope(request.scope)
    return json_resp(scope_data)


@app.router.post("/echo")
async def echo(request: Request) -> Response:
    """Echo request body back."""
    body = await request.read()
    content_type = request.get_first_header(b"content-type")
    if content_type:
        ct = content_type
    else:
        ct = b"application/octet-stream"
    return Response(200, content=Content(ct, body))


@app.router.get("/headers")
async def headers_endpoint(request: Request) -> Response:
    """Return request headers as JSON."""
    headers_dict = {
        h[0].decode("latin-1"): h[1].decode("latin-1") for h in request.headers
    }
    return json_resp(headers_dict)


@app.router.get("/status/{code}")
async def status_endpoint(request: Request, code: int) -> Response:
    """Return specific HTTP status code."""
    return Response(code, content=Content(b"text/plain", f"Status: {code}".encode()))


@app.router.get("/streaming")
async def streaming(request: Request) -> Response:
    """Chunked streaming response."""

    async def generate():
        for i in range(10):
            yield f"chunk-{i}\n".encode()
            await asyncio.sleep(0.01)

    return Response(200, content=StreamedContent(b"text/plain", generate))


@app.router.get("/sse")
async def sse(request: Request) -> Response:
    """Server-Sent Events endpoint."""

    async def generate():
        for i in range(5):
            yield f"event: message\ndata: {json.dumps({'count': i})}\n\n".encode()
            await asyncio.sleep(0.01)
        yield b"event: done\ndata: {}\n\n"

    response = Response(200, content=StreamedContent(b"text/event-stream", generate))
    response.add_header(b"Cache-Control", b"no-cache")
    return response


@app.router.get("/large")
async def large(request: Request) -> Response:
    """Large response body."""
    size_param = request.query.get("size")
    size = int(size_param[0]) if size_param else 1024
    # Cap at 10MB for safety
    size = min(size, 10 * 1024 * 1024)
    return Response(200, content=Content(b"application/octet-stream", b"x" * size))


@app.router.get("/delay")
async def delay(request: Request) -> Response:
    """Delayed response."""
    seconds_param = request.query.get("seconds")
    seconds = float(seconds_param[0]) if seconds_param else 1.0
    # Cap at 30 seconds
    seconds = min(seconds, 30)
    await asyncio.sleep(seconds)
    return text(f"Delayed {seconds} seconds")


@app.router.get("/lifespan/state")
async def lifespan_state_endpoint(request: Request) -> Response:
    """Return lifespan startup state."""
    return json_resp(lifespan_state)


@app.router.get("/lifespan/counter")
async def lifespan_counter(request: Request) -> Response:
    """Increment and return counter."""
    lifespan_state["counter"] += 1
    return json_resp({"counter": lifespan_state["counter"]})


# WebSocket Endpoints
@app.router.ws("/ws/echo")
async def ws_echo(websocket: WebSocket) -> None:
    """Echo text messages."""
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_text()
            await websocket.send_text(message)
    except Exception:
        pass


@app.router.ws("/ws/echo-binary")
async def ws_echo_binary(websocket: WebSocket) -> None:
    """Echo binary messages."""
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_bytes()
            await websocket.send_bytes(message)
    except Exception:
        pass


@app.router.ws("/ws/scope")
async def ws_scope(websocket: WebSocket) -> None:
    """Send WebSocket scope on connect."""
    await websocket.accept()
    scope_data = serialize_scope(websocket.scope)
    await websocket.send_text(json.dumps(scope_data))
    await websocket.close()


@app.router.ws("/ws/subprotocol")
async def ws_subprotocol(websocket: WebSocket) -> None:
    """Subprotocol negotiation."""
    requested = websocket.scope.get("subprotocols", [])
    selected = requested[0] if requested else None
    await websocket.accept(subprotocol=selected)
    await websocket.send_text(json.dumps({"requested": requested, "selected": selected}))
    await websocket.close()


@app.router.ws("/ws/close")
async def ws_close(websocket: WebSocket) -> None:
    """Close with specific code."""
    await websocket.accept()
    query_string = websocket.scope.get("query_string", b"").decode()
    code = 1000
    for param in query_string.split("&"):
        if param.startswith("code="):
            code = int(param.split("=")[1])
            break
    await websocket.close(code=code)
