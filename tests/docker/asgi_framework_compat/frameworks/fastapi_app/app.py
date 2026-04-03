"""
FastAPI ASGI Application for Compatibility Testing

Implements the contract endpoints for ASGI 3.0 compliance testing.
"""

import asyncio
import json
import sys
import traceback
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse, Response, StreamingResponse, JSONResponse


# Lifespan state
lifespan_state = {
    "startup_called": False,
    "startup_time": None,
    "counter": 0,
    "custom_data": {},
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    import time

    lifespan_state["startup_called"] = True
    lifespan_state["startup_time"] = time.time()
    lifespan_state["custom_data"]["initialized"] = True
    yield
    lifespan_state["shutdown_called"] = True


app = FastAPI(lifespan=lifespan)


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
                 "extensions", "_cookies", "fastapi_astack"}

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
@app.get("/health")
async def health():
    """Health check endpoint."""
    return PlainTextResponse("OK")


@app.get("/scope")
async def scope_endpoint(request: Request):
    """Return full ASGI scope as JSON."""
    try:
        scope_data = serialize_scope(request.scope)
        return JSONResponse(scope_data)
    except Exception as e:
        traceback.print_exc()
        return PlainTextResponse(f"Error: {e}", status_code=500)


@app.post("/echo")
async def echo(request: Request):
    """Echo request body back."""
    body = await request.body()
    content_type = request.headers.get("content-type", "application/octet-stream")
    return Response(content=body, media_type=content_type)


@app.get("/headers")
async def headers_endpoint(request: Request):
    """Return request headers as JSON."""
    headers_dict = dict(request.headers)
    return headers_dict


@app.get("/status/{code}")
async def status_endpoint(code: int):
    """Return specific HTTP status code."""
    return PlainTextResponse(f"Status: {code}", status_code=code)


@app.get("/streaming")
async def streaming():
    """Chunked streaming response."""

    async def generate():
        for i in range(10):
            yield f"chunk-{i}\n"
            await asyncio.sleep(0.01)

    return StreamingResponse(generate(), media_type="text/plain")


@app.get("/sse")
async def sse():
    """Server-Sent Events endpoint."""

    async def generate():
        for i in range(5):
            yield f"event: message\ndata: {json.dumps({'count': i})}\n\n"
            await asyncio.sleep(0.01)
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/large")
async def large(size: int = 1024):
    """Large response body."""
    # Cap at 10MB for safety
    size = min(size, 10 * 1024 * 1024)
    return Response(content=b"x" * size, media_type="application/octet-stream")


@app.get("/delay")
async def delay(seconds: float = 1.0):
    """Delayed response."""
    # Cap at 30 seconds
    seconds = min(seconds, 30)
    await asyncio.sleep(seconds)
    return PlainTextResponse(f"Delayed {seconds} seconds")


@app.get("/lifespan/state")
async def lifespan_state_endpoint():
    """Return lifespan startup state."""
    return lifespan_state


@app.get("/lifespan/counter")
async def lifespan_counter():
    """Increment and return counter."""
    lifespan_state["counter"] += 1
    return {"counter": lifespan_state["counter"]}


# WebSocket Endpoints
@app.websocket("/ws/echo")
async def ws_echo(websocket: WebSocket):
    """Echo text messages."""
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_text()
            await websocket.send_text(message)
    except WebSocketDisconnect:
        pass


@app.websocket("/ws/echo-binary")
async def ws_echo_binary(websocket: WebSocket):
    """Echo binary messages."""
    await websocket.accept()
    try:
        while True:
            message = await websocket.receive_bytes()
            await websocket.send_bytes(message)
    except WebSocketDisconnect:
        pass


@app.websocket("/ws/scope")
async def ws_scope(websocket: WebSocket):
    """Send WebSocket scope on connect."""
    await websocket.accept()
    try:
        scope_data = serialize_scope(websocket.scope)
        await websocket.send_json(scope_data)
    except Exception as e:
        await websocket.send_text(f"Error: {e}")
    await websocket.close()


@app.websocket("/ws/subprotocol")
async def ws_subprotocol(websocket: WebSocket):
    """Subprotocol negotiation."""
    requested = websocket.scope.get("subprotocols", [])
    selected = requested[0] if requested else None
    await websocket.accept(subprotocol=selected)
    await websocket.send_json({"requested": requested, "selected": selected})
    await websocket.close()


@app.websocket("/ws/close")
async def ws_close(websocket: WebSocket):
    """Close with specific code."""
    await websocket.accept()
    query_string = websocket.scope.get("query_string", b"").decode()
    code = 1000
    for param in query_string.split("&"):
        if param.startswith("code="):
            code = int(param.split("=")[1])
            break
    await websocket.close(code=code)
