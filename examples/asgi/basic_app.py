#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Basic ASGI application example.

Run with:
    gunicorn -k asgi examples.asgi.basic_app:app

Test with:
    curl http://127.0.0.1:8000/
    curl http://127.0.0.1:8000/hello
    curl -X POST http://127.0.0.1:8000/echo -d "test data"
"""


async def app(scope, receive, send):
    """Simple ASGI application demonstrating basic functionality."""

    if scope["type"] == "lifespan":
        await handle_lifespan(scope, receive, send)
    elif scope["type"] == "http":
        await handle_http(scope, receive, send)
    else:
        raise ValueError(f"Unknown scope type: {scope['type']}")


async def handle_lifespan(scope, receive, send):
    """Handle lifespan events (startup/shutdown)."""
    while True:
        message = await receive()
        if message["type"] == "lifespan.startup":
            print("ASGI application starting up...")
            await send({"type": "lifespan.startup.complete"})
        elif message["type"] == "lifespan.shutdown":
            print("ASGI application shutting down...")
            await send({"type": "lifespan.shutdown.complete"})
            return


async def handle_http(scope, receive, send):
    """Handle HTTP requests."""
    path = scope["path"]
    method = scope["method"]

    if path == "/" and method == "GET":
        await send_response(send, 200, b"Welcome to gunicorn ASGI!\n")

    elif path == "/hello" and method == "GET":
        name = get_query_param(scope, "name", "World")
        body = f"Hello, {name}!\n".encode()
        await send_response(send, 200, body)

    elif path == "/echo" and method == "POST":
        body = await read_body(receive)
        await send_response(send, 200, body, content_type=b"application/octet-stream")

    elif path == "/headers":
        headers_info = format_headers(scope["headers"])
        await send_response(send, 200, headers_info.encode())

    elif path == "/info":
        info = format_request_info(scope)
        await send_response(send, 200, info.encode(), content_type=b"application/json")

    else:
        await send_response(send, 404, b"Not Found\n")


async def send_response(send, status, body, content_type=b"text/plain"):
    """Send an HTTP response."""
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", content_type),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({
        "type": "http.response.body",
        "body": body,
    })


async def read_body(receive):
    """Read the full request body."""
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if not message.get("more_body", False):
            break
    return body


def get_query_param(scope, name, default=None):
    """Get a query parameter value."""
    query_string = scope.get("query_string", b"").decode()
    for param in query_string.split("&"):
        if "=" in param:
            key, value = param.split("=", 1)
            if key == name:
                return value
    return default


def format_headers(headers):
    """Format headers for display."""
    lines = ["Request Headers:"]
    for name, value in headers:
        lines.append(f"  {name.decode()}: {value.decode()}")
    return "\n".join(lines) + "\n"


def format_request_info(scope):
    """Format request info as JSON."""
    import json
    info = {
        "method": scope["method"],
        "path": scope["path"],
        "query_string": scope.get("query_string", b"").decode(),
        "http_version": scope["http_version"],
        "scheme": scope["scheme"],
        "server": list(scope.get("server") or []),
        "client": list(scope.get("client") or []),
        "root_path": scope.get("root_path", ""),
    }
    return json.dumps(info, indent=2) + "\n"
