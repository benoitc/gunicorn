#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Framework integration test applications.

Tests integration with popular ASGI frameworks like Starlette and FastAPI.
These apps require the frameworks to be installed.
"""

import json
import os

# Framework availability flags
STARLETTE_AVAILABLE = False
FASTAPI_AVAILABLE = False

try:
    from starlette.applications import Starlette
    from starlette.responses import (
        JSONResponse,
        PlainTextResponse,
        StreamingResponse,
    )
    from starlette.routing import Route, WebSocketRoute
    from starlette.websockets import WebSocket
    STARLETTE_AVAILABLE = True
except ImportError:
    pass

try:
    from fastapi import FastAPI, Request, WebSocket as FastAPIWebSocket
    from fastapi.responses import (
        JSONResponse as FastAPIJSONResponse,
        StreamingResponse as FastAPIStreamingResponse,
    )
    FASTAPI_AVAILABLE = True
except ImportError:
    pass


# ============================================================================
# Pure ASGI Fallback App (when frameworks not available)
# ============================================================================

async def fallback_app(scope, receive, send):
    """Fallback ASGI app when frameworks are not installed."""
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
        return

    if scope["type"] != "http":
        return

    body = json.dumps({
        "error": "Framework not available",
        "starlette_available": STARLETTE_AVAILABLE,
        "fastapi_available": FASTAPI_AVAILABLE,
        "message": "Install starlette and/or fastapi to use this app",
    }).encode("utf-8")

    await send({
        "type": "http.response.start",
        "status": 503,
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


# ============================================================================
# Starlette Application
# ============================================================================

if STARLETTE_AVAILABLE:
    import asyncio

    async def starlette_homepage(request):
        """Starlette homepage."""
        return PlainTextResponse("Hello from Starlette!")

    async def starlette_json(request):
        """Return JSON response."""
        return JSONResponse({
            "framework": "starlette",
            "method": request.method,
            "path": request.url.path,
            "query_params": dict(request.query_params),
        })

    async def starlette_echo(request):
        """Echo request body."""
        body = await request.body()
        return PlainTextResponse(body.decode("utf-8", errors="replace"))

    async def starlette_headers(request):
        """Return request headers."""
        return JSONResponse(dict(request.headers))

    async def starlette_scope(request):
        """Return ASGI scope."""
        scope = request.scope
        scope_json = {
            "type": scope["type"],
            "asgi": scope["asgi"],
            "http_version": scope["http_version"],
            "method": scope["method"],
            "scheme": scope["scheme"],
            "path": scope["path"],
            "query_string": scope["query_string"].decode("latin-1"),
            "root_path": scope.get("root_path", ""),
            "headers": [
                [n.decode("latin-1"), v.decode("latin-1")]
                for n, v in scope["headers"]
            ],
            "server": list(scope["server"]) if scope.get("server") else None,
            "client": list(scope["client"]) if scope.get("client") else None,
        }
        return JSONResponse(scope_json)

    async def starlette_streaming(request):
        """Streaming response."""
        async def generate():
            for i in range(10):
                yield f"Chunk {i + 1}\n".encode("utf-8")
                await asyncio.sleep(0.1)

        return StreamingResponse(generate(), media_type="text/plain")

    async def starlette_websocket_endpoint(websocket: WebSocket):
        """WebSocket echo endpoint."""
        await websocket.accept()
        try:
            while True:
                data = await websocket.receive_text()
                await websocket.send_text(f"Starlette echo: {data}")
        except Exception:
            pass

    async def starlette_health(request):
        """Health check."""
        return PlainTextResponse("OK")

    # Lifespan context manager
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def starlette_lifespan(app):
        """Starlette lifespan context manager."""
        # Startup
        app.state.startup_time = asyncio.get_event_loop().time()
        app.state.started = True
        yield
        # Shutdown
        app.state.started = False

    starlette_routes = [
        Route("/", starlette_homepage),
        Route("/json", starlette_json),
        Route("/echo", starlette_echo, methods=["POST"]),
        Route("/headers", starlette_headers),
        Route("/scope", starlette_scope),
        Route("/streaming", starlette_streaming),
        Route("/health", starlette_health),
        WebSocketRoute("/ws/echo", starlette_websocket_endpoint),
    ]

    starlette_app = Starlette(
        routes=starlette_routes,
        lifespan=starlette_lifespan,
    )
else:
    starlette_app = fallback_app


# ============================================================================
# FastAPI Application
# ============================================================================

if FASTAPI_AVAILABLE:
    import asyncio
    from contextlib import asynccontextmanager
    from typing import Any, Dict

    @asynccontextmanager
    async def fastapi_lifespan(app: FastAPI):
        """FastAPI lifespan context manager."""
        # Startup
        app.state.startup_time = asyncio.get_event_loop().time()
        app.state.started = True
        yield
        # Shutdown
        app.state.started = False

    fastapi_app = FastAPI(
        title="ASGI Compliance Test - FastAPI",
        lifespan=fastapi_lifespan,
    )

    @fastapi_app.get("/")
    async def fastapi_root():
        """FastAPI homepage."""
        return {"message": "Hello from FastAPI!"}

    @fastapi_app.get("/json")
    async def fastapi_json(request: Request) -> Dict[str, Any]:
        """Return JSON response with request info."""
        return {
            "framework": "fastapi",
            "method": request.method,
            "path": str(request.url.path),
            "query_params": dict(request.query_params),
        }

    @fastapi_app.post("/echo")
    async def fastapi_echo(request: Request):
        """Echo request body."""
        body = await request.body()
        return FastAPIJSONResponse(content={
            "echo": body.decode("utf-8", errors="replace"),
            "length": len(body),
        })

    @fastapi_app.get("/headers")
    async def fastapi_headers(request: Request):
        """Return request headers."""
        return dict(request.headers)

    @fastapi_app.get("/scope")
    async def fastapi_scope(request: Request):
        """Return ASGI scope."""
        scope = request.scope
        return {
            "type": scope["type"],
            "asgi": scope["asgi"],
            "http_version": scope["http_version"],
            "method": scope["method"],
            "scheme": scope["scheme"],
            "path": scope["path"],
            "query_string": scope["query_string"].decode("latin-1"),
            "root_path": scope.get("root_path", ""),
            "server": list(scope["server"]) if scope.get("server") else None,
            "client": list(scope["client"]) if scope.get("client") else None,
        }

    @fastapi_app.get("/streaming")
    async def fastapi_streaming():
        """Streaming response."""
        async def generate():
            for i in range(10):
                yield f"Chunk {i + 1}\n"
                await asyncio.sleep(0.1)

        return FastAPIStreamingResponse(generate(), media_type="text/plain")

    @fastapi_app.get("/health")
    async def fastapi_health():
        """Health check."""
        return {"status": "ok"}

    @fastapi_app.get("/items/{item_id}")
    async def fastapi_get_item(item_id: int, q: str = None):
        """Path parameter example."""
        return {"item_id": item_id, "query": q}

    @fastapi_app.post("/items/")
    async def fastapi_create_item(request: Request):
        """Create item example."""
        body = await request.json()
        return {"created": body}

    @fastapi_app.websocket("/ws/echo")
    async def fastapi_websocket_echo(websocket: FastAPIWebSocket):
        """WebSocket echo endpoint."""
        await websocket.accept()
        try:
            while True:
                data = await websocket.receive_text()
                await websocket.send_text(f"FastAPI echo: {data}")
        except Exception:
            pass

else:
    fastapi_app = fallback_app


# ============================================================================
# Combined Application Router
# ============================================================================

async def combined_app(scope, receive, send):
    """Combined app that routes based on path prefix."""
    if scope["type"] == "lifespan":
        # Handle lifespan for both apps
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
        return

    path = scope.get("path", "")

    if path.startswith("/starlette"):
        # Strip prefix for Starlette
        scope = dict(scope)
        scope["path"] = path[10:] or "/"
        scope["raw_path"] = scope["path"].encode("latin-1")
        await starlette_app(scope, receive, send)
    elif path.startswith("/fastapi"):
        # Strip prefix for FastAPI
        scope = dict(scope)
        scope["path"] = path[8:] or "/"
        scope["raw_path"] = scope["path"].encode("latin-1")
        await fastapi_app(scope, receive, send)
    elif path == "/":
        # Root - show available apps
        body = json.dumps({
            "apps": {
                "starlette": {
                    "available": STARLETTE_AVAILABLE,
                    "prefix": "/starlette",
                },
                "fastapi": {
                    "available": FASTAPI_AVAILABLE,
                    "prefix": "/fastapi",
                },
            },
            "endpoints": {
                "starlette": ["/", "/json", "/echo", "/headers", "/scope", "/streaming", "/ws/echo"],
                "fastapi": ["/", "/json", "/echo", "/headers", "/scope", "/streaming", "/items/{id}", "/ws/echo"],
            },
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
    elif path == "/health":
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
    else:
        body = b"Not Found - use /starlette/* or /fastapi/* prefixes"
        await send({
            "type": "http.response.start",
            "status": 404,
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


# Export the apps
app = combined_app
