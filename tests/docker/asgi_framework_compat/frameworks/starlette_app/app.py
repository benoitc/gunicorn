"""
Starlette ASGI Application for Compatibility Testing

Implements the contract endpoints for ASGI 3.0 compliance testing.
"""

import asyncio
import json
import sys
import traceback
from contextlib import asynccontextmanager
from typing import Any

from starlette.applications import Starlette
from starlette.responses import (
    JSONResponse,
    PlainTextResponse,
    Response,
    StreamingResponse,
)
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket


# Lifespan state
lifespan_state = {
    "startup_called": False,
    "startup_time": None,
    "counter": 0,
    "custom_data": {},
}


@asynccontextmanager
async def lifespan(app):
    """Lifespan context manager for startup/shutdown."""
    import time

    lifespan_state["startup_called"] = True
    lifespan_state["startup_time"] = time.time()
    lifespan_state["custom_data"]["initialized"] = True
    yield
    lifespan_state["shutdown_called"] = True


def safe_json_serialize(obj: Any) -> Any:
    """Recursively convert an object to JSON-serializable form."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    elif isinstance(obj, bytes):
        return obj.decode("latin-1")
    elif isinstance(obj, (list, tuple)):
        return [safe_json_serialize(item) for item in obj]
    elif isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            # Only include string keys
            if isinstance(k, str):
                result[k] = safe_json_serialize(v)
        return result
    else:
        # Skip non-serializable types
        return None


def serialize_scope(scope: dict) -> dict:
    """Convert ASGI scope to JSON-serializable dict."""
    result = {}

    # Keys to explicitly skip (non-serializable objects)
    skip_keys = {"state", "app", "router", "endpoint", "path_params", "route",
                 "extensions", "_cookies"}

    for key, value in scope.items():
        if key in skip_keys:
            continue

        try:
            if key == "headers":
                result[key] = [
                    [h[0].decode("latin-1"), h[1].decode("latin-1")] for h in value
                ]
            elif key == "query_string":
                result[key] = value.decode("latin-1") if value else ""
            elif key == "raw_path":
                result[key] = value.decode("latin-1") if value else ""
            elif key == "server":
                result[key] = list(value) if value else None
            elif key == "client":
                result[key] = list(value) if value else None
            elif key == "asgi":
                # Only serialize simple values from asgi dict
                result[key] = {
                    k: v for k, v in value.items()
                    if isinstance(k, str) and isinstance(v, (str, int, float, bool, type(None)))
                }
            elif isinstance(value, bytes):
                result[key] = value.decode("latin-1")
            elif isinstance(value, (str, int, float, bool, type(None))):
                result[key] = value
            elif isinstance(value, (list, tuple)):
                serialized = safe_json_serialize(value)
                if serialized is not None:
                    result[key] = serialized
            elif isinstance(value, dict):
                serialized = safe_json_serialize(value)
                if serialized is not None:
                    result[key] = serialized
            # Skip other types
        except Exception as e:
            print(f"Error serializing key {key}: {e}", file=sys.stderr)
            continue
    return result


# HTTP Endpoints
async def health(request):
    """Health check endpoint."""
    return PlainTextResponse("OK")


async def scope_endpoint(request):
    """Return full ASGI scope as JSON."""
    try:
        scope_data = serialize_scope(request.scope)
        return JSONResponse(scope_data)
    except Exception as e:
        traceback.print_exc()
        return PlainTextResponse(f"Error: {e}", status_code=500)


async def echo(request):
    """Echo request body back."""
    body = await request.body()
    content_type = request.headers.get("content-type", "application/octet-stream")
    return Response(content=body, media_type=content_type)


async def headers_endpoint(request):
    """Return request headers as JSON."""
    headers_dict = dict(request.headers)
    return JSONResponse(headers_dict)


async def status_endpoint(request):
    """Return specific HTTP status code."""
    code = int(request.path_params["code"])
    return PlainTextResponse(f"Status: {code}", status_code=code)


async def streaming(request):
    """Chunked streaming response."""

    async def generate():
        for i in range(10):
            yield f"chunk-{i}\n"
            await asyncio.sleep(0.01)

    return StreamingResponse(generate(), media_type="text/plain")


async def sse(request):
    """Server-Sent Events endpoint."""

    async def generate():
        for i in range(5):
            yield f"event: message\ndata: {json.dumps({'count': i})}\n\n"
            await asyncio.sleep(0.01)
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


async def large(request):
    """Large response body."""
    size = int(request.query_params.get("size", 1024))
    # Cap at 10MB for safety
    size = min(size, 10 * 1024 * 1024)
    return Response(content=b"x" * size, media_type="application/octet-stream")


async def delay(request):
    """Delayed response."""
    seconds = float(request.query_params.get("seconds", 1))
    # Cap at 30 seconds
    seconds = min(seconds, 30)
    await asyncio.sleep(seconds)
    return PlainTextResponse(f"Delayed {seconds} seconds")


async def lifespan_state_endpoint(request):
    """Return lifespan startup state."""
    return JSONResponse(lifespan_state)


async def lifespan_counter(request):
    """Increment and return counter."""
    lifespan_state["counter"] += 1
    return JSONResponse({"counter": lifespan_state["counter"]})


# WebSocket Endpoints
async def ws_echo(websocket: WebSocket):
    """Echo text messages."""
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_text()
            await websocket.send_text(message)
    except Exception:
        pass


async def ws_echo_binary(websocket: WebSocket):
    """Echo binary messages."""
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_bytes()
            await websocket.send_bytes(message)
    except Exception:
        pass


async def ws_scope(websocket: WebSocket):
    """Send WebSocket scope on connect."""
    await websocket.accept()
    try:
        scope_data = serialize_scope(websocket.scope)
        await websocket.send_json(scope_data)
    except Exception as e:
        await websocket.send_text(f"Error: {e}")
    await websocket.close()


async def ws_subprotocol(websocket: WebSocket):
    """Subprotocol negotiation."""
    # Get requested subprotocols from scope
    requested = websocket.scope.get("subprotocols", [])
    # Select first one if available
    selected = requested[0] if requested else None
    await websocket.accept(subprotocol=selected)
    await websocket.send_json(
        {"requested": requested, "selected": selected}
    )
    await websocket.close()


async def ws_close(websocket: WebSocket):
    """Close with specific code."""
    await websocket.accept()
    # Get close code from query string
    query_string = websocket.scope.get("query_string", b"").decode()
    code = 1000
    for param in query_string.split("&"):
        if param.startswith("code="):
            code = int(param.split("=")[1])
            break
    await websocket.close(code=code)


# Routes
routes = [
    # HTTP endpoints
    Route("/health", health),
    Route("/scope", scope_endpoint),
    Route("/echo", echo, methods=["POST"]),
    Route("/headers", headers_endpoint),
    Route("/status/{code:int}", status_endpoint),
    Route("/streaming", streaming),
    Route("/sse", sse),
    Route("/large", large),
    Route("/delay", delay),
    Route("/lifespan/state", lifespan_state_endpoint),
    Route("/lifespan/counter", lifespan_counter),
    # WebSocket endpoints
    WebSocketRoute("/ws/echo", ws_echo),
    WebSocketRoute("/ws/echo-binary", ws_echo_binary),
    WebSocketRoute("/ws/scope", ws_scope),
    WebSocketRoute("/ws/subprotocol", ws_subprotocol),
    WebSocketRoute("/ws/close", ws_close),
]

app = Starlette(routes=routes, lifespan=lifespan)
