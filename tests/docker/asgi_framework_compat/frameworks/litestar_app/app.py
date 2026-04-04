"""
Litestar ASGI Application for Compatibility Testing

Implements the contract endpoints for ASGI 3.0 compliance testing.
Litestar is a modern ASGI framework with extensive feature support.
"""

import asyncio
import json
import time
from typing import Any, Dict

from litestar import Litestar, Request, get, post
from litestar.connection import ASGIConnection
from litestar.handlers import websocket
from litestar.response import Response, Stream


# Lifespan state
lifespan_state = {
    "startup_called": False,
    "startup_time": None,
    "counter": 0,
    "custom_data": {},
}


async def on_startup(app: Litestar) -> None:
    """Startup handler."""
    lifespan_state["startup_called"] = True
    lifespan_state["startup_time"] = time.time()
    lifespan_state["custom_data"]["initialized"] = True


async def on_shutdown(app: Litestar) -> None:
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
        elif key in ("state", "app", "_litestar", "route_handler", "path_params"):
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
@get("/health")
async def health() -> str:
    """Health check endpoint."""
    return "OK"


@get("/scope")
async def scope_endpoint(request: Request) -> Dict[str, Any]:
    """Return full ASGI scope as JSON."""
    scope_data = serialize_scope(request.scope)
    return scope_data


@post("/echo")
async def echo(request: Request) -> Response:
    """Echo request body back."""
    # Read body using the receive callable to avoid Litestar's internal caching
    body_parts = []
    while True:
        message = await request.receive()
        body = message.get("body", b"")
        if body:
            body_parts.append(body)
        if not message.get("more_body", False):
            break
    body = b"".join(body_parts)
    # Access headers directly from scope to avoid Litestar's caching
    scope_headers = {name.decode("latin-1"): value.decode("latin-1")
                     for name, value in request.scope.get("headers", [])}
    content_type = scope_headers.get("content-type", "application/octet-stream")
    return Response(content=body, media_type=content_type, status_code=200)


@get("/headers")
async def headers_endpoint(request: Request) -> Dict[str, str]:
    """Return request headers as JSON."""
    # Access headers directly from scope to avoid Litestar's caching
    scope_headers = request.scope.get("headers", [])
    return {name.decode("latin-1"): value.decode("latin-1") for name, value in scope_headers}


@get("/status/{code:int}")
async def status_endpoint(code: int) -> Response:
    """Return specific HTTP status code."""
    # HTTP 204 No Content cannot have a body
    if code == 204:
        return Response(content=b"", status_code=204)
    return Response(content=f"Status: {code}", status_code=code)


@get("/streaming")
async def streaming() -> Stream:
    """Chunked streaming response."""

    async def generate():
        for i in range(10):
            yield f"chunk-{i}\n".encode()
            await asyncio.sleep(0.01)

    return Stream(generate(), media_type="text/plain")


@get("/sse")
async def sse() -> Stream:
    """Server-Sent Events endpoint."""

    async def generate():
        for i in range(5):
            yield f"event: message\ndata: {json.dumps({'count': i})}\n\n".encode()
            await asyncio.sleep(0.01)
        yield b"event: done\ndata: {}\n\n"

    return Stream(generate(), media_type="text/event-stream")


@get("/large")
async def large(size: int = 1024) -> Response:
    """Large response body."""
    # Cap at 10MB for safety
    size = min(size, 10 * 1024 * 1024)
    return Response(content=b"x" * size, media_type="application/octet-stream")


@get("/delay")
async def delay(seconds: float = 1.0) -> str:
    """Delayed response."""
    # Cap at 30 seconds
    seconds = min(seconds, 30)
    await asyncio.sleep(seconds)
    return f"Delayed {seconds} seconds"


@get("/lifespan/state")
async def lifespan_state_endpoint() -> Dict[str, Any]:
    """Return lifespan startup state."""
    return lifespan_state


@get("/lifespan/counter")
async def lifespan_counter() -> Dict[str, int]:
    """Increment and return counter."""
    lifespan_state["counter"] += 1
    return {"counter": lifespan_state["counter"]}


# WebSocket Endpoints using raw websocket handler
@websocket("/ws/echo")
async def ws_echo(socket: ASGIConnection) -> None:
    """Echo text messages."""
    await socket.accept()
    try:
        while True:
            data = await socket.receive_text()
            await socket.send_text(data)
    except Exception:
        pass


@websocket("/ws/echo-binary")
async def ws_echo_binary(socket: ASGIConnection) -> None:
    """Echo binary messages."""
    await socket.accept()
    try:
        while True:
            data = await socket.receive_bytes()
            await socket.send_bytes(data)
    except Exception:
        pass


@websocket("/ws/scope")
async def ws_scope_handler(socket: ASGIConnection) -> None:
    """Send WebSocket scope on connect."""
    await socket.accept()
    scope_data = serialize_scope(socket.scope)
    await socket.send_json(scope_data)
    await socket.close()


@websocket("/ws/subprotocol")
async def ws_subprotocol_handler(socket: ASGIConnection) -> None:
    """Subprotocol negotiation."""
    requested = socket.scope.get("subprotocols", [])
    selected = requested[0] if requested else None
    await socket.accept(subprotocols=selected)
    await socket.send_json({"requested": requested, "selected": selected})
    await socket.close()


@websocket("/ws/close")
async def ws_close_handler(socket: ASGIConnection) -> None:
    """Close with specific code."""
    await socket.accept()
    query_string = socket.scope.get("query_string", b"").decode()
    code = 1000
    for param in query_string.split("&"):
        if param.startswith("code="):
            code = int(param.split("=")[1])
            break
    await socket.close(code=code)


# Create app with lifespan handlers
app = Litestar(
    route_handlers=[
        health,
        scope_endpoint,
        echo,
        headers_endpoint,
        status_endpoint,
        streaming,
        sse,
        large,
        delay,
        lifespan_state_endpoint,
        lifespan_counter,
        ws_echo,
        ws_echo_binary,
        ws_scope_handler,
        ws_subprotocol_handler,
        ws_close_handler,
    ],
    on_startup=[on_startup],
    on_shutdown=[on_shutdown],
)
