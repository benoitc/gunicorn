#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
HTTP/2 ASGI application demonstrating priority and trailers.

This example shows how to:
- Access stream priority information from HTTP/2 requests
- Send response trailers (useful for gRPC, checksums, etc.)

Run with:
    cd examples/http2_features
    docker compose up --build

Test with:
    python test_http2.py

Or manually:
    curl -k --http2 https://localhost:8443/
    curl -k --http2 https://localhost:8443/priority
    curl -k --http2 https://localhost:8443/trailers
"""

import json
import hashlib


async def app(scope, receive, send):
    """ASGI application demonstrating HTTP/2 priority and trailers."""

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
            print("HTTP/2 features app starting...")
            await send({"type": "lifespan.startup.complete"})
        elif message["type"] == "lifespan.shutdown":
            print("HTTP/2 features app shutting down...")
            await send({"type": "lifespan.shutdown.complete"})
            return


async def handle_http(scope, receive, send):
    """Route HTTP requests to handlers."""
    path = scope["path"]
    method = scope["method"]

    if path == "/" and method == "GET":
        await handle_index(scope, receive, send)
    elif path == "/priority" and method == "GET":
        await handle_priority(scope, receive, send)
    elif path == "/trailers" and method in ("GET", "POST"):
        await handle_trailers(scope, receive, send)
    elif path == "/combined" and method in ("GET", "POST"):
        await handle_combined(scope, receive, send)
    elif path == "/health" and method == "GET":
        await send_response(send, 200, b"OK")
    else:
        await send_response(send, 404, b"Not Found\n")


async def handle_index(scope, receive, send):
    """Show available endpoints and HTTP/2 features."""
    extensions = scope.get("extensions", {})
    http_version = scope.get("http_version", "1.1")

    info = {
        "message": "HTTP/2 Features Demo",
        "http_version": http_version,
        "endpoints": {
            "/": "This info page",
            "/priority": "Shows stream priority information",
            "/trailers": "Demonstrates response trailers with checksum",
            "/combined": "Shows both priority and trailers",
            "/health": "Health check endpoint",
        },
        "extensions": list(extensions.keys()),
    }

    body = json.dumps(info, indent=2).encode() + b"\n"
    await send_response(send, 200, body, content_type=b"application/json")


async def handle_priority(scope, receive, send):
    """Return stream priority information.

    HTTP/2 allows clients to indicate relative importance of requests.
    Gunicorn exposes this through the http.response.priority extension.
    """
    extensions = scope.get("extensions", {})
    priority_info = extensions.get("http.response.priority")

    if priority_info:
        response = {
            "http_version": scope.get("http_version", "1.1"),
            "priority": {
                "weight": priority_info["weight"],
                "depends_on": priority_info["depends_on"],
                "description": (
                    f"Weight {priority_info['weight']}/256 - "
                    f"{'high' if priority_info['weight'] > 128 else 'normal' if priority_info['weight'] > 64 else 'low'} priority"
                ),
            },
            "note": "Priority is advisory - use for scheduling hints",
        }
    else:
        response = {
            "http_version": scope.get("http_version", "1.1"),
            "priority": None,
            "note": "Priority information only available for HTTP/2 requests",
        }

    body = json.dumps(response, indent=2).encode() + b"\n"
    await send_response(send, 200, body, content_type=b"application/json")


async def handle_trailers(scope, receive, send):
    """Demonstrate response trailers.

    Trailers are headers sent after the response body.
    Common uses: gRPC status codes, checksums, timing info.
    """
    extensions = scope.get("extensions", {})
    supports_trailers = "http.response.trailers" in extensions

    # Read request body if POST
    body_data = b""
    if scope["method"] == "POST":
        body_data = await read_body(receive)

    # Generate response
    response_body = body_data if body_data else b"Hello from HTTP/2 with trailers!\n"

    # Calculate checksum for trailer
    checksum = hashlib.md5(response_body).hexdigest()

    if supports_trailers:
        # Send response announcing trailers
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"application/octet-stream"),
                (b"trailer", b"content-md5, x-processing-time"),
            ],
        })

        # Send body
        await send({
            "type": "http.response.body",
            "body": response_body,
            "more_body": False,
        })

        # Send trailers
        await send({
            "type": "http.response.trailers",
            "headers": [
                (b"content-md5", checksum.encode()),
                (b"x-processing-time", b"42ms"),
            ],
        })
    else:
        # HTTP/1.1 fallback - include checksum in regular headers
        response = {
            "message": "Trailers not supported (HTTP/1.1)",
            "data": response_body.decode("utf-8", errors="replace"),
            "checksum_in_header": checksum,
        }
        body = json.dumps(response, indent=2).encode() + b"\n"
        await send_response(
            send, 200, body,
            content_type=b"application/json",
            extra_headers=[(b"x-checksum", checksum.encode())]
        )


async def handle_combined(scope, receive, send):
    """Show both priority and trailers in one response.

    This demonstrates a realistic scenario like gRPC where
    priority affects scheduling and trailers carry status.
    """
    extensions = scope.get("extensions", {})
    priority_info = extensions.get("http.response.priority")
    supports_trailers = "http.response.trailers" in extensions

    # Build response showing all HTTP/2 features
    response = {
        "http_version": scope.get("http_version", "1.1"),
        "priority": None,
        "trailers_supported": supports_trailers,
    }

    if priority_info:
        response["priority"] = {
            "weight": priority_info["weight"],
            "depends_on": priority_info["depends_on"],
        }

    response_body = json.dumps(response, indent=2).encode() + b"\n"
    checksum = hashlib.md5(response_body).hexdigest()

    if supports_trailers:
        # Full HTTP/2 response with trailers
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"application/json"),
                (b"trailer", b"content-md5, x-status"),
            ],
        })

        await send({
            "type": "http.response.body",
            "body": response_body,
            "more_body": False,
        })

        await send({
            "type": "http.response.trailers",
            "headers": [
                (b"content-md5", checksum.encode()),
                (b"x-status", b"success"),
            ],
        })
    else:
        await send_response(send, 200, response_body, content_type=b"application/json")


async def send_response(send, status, body, content_type=b"text/plain", extra_headers=None):
    """Send a simple HTTP response."""
    headers = [
        (b"content-type", content_type),
        (b"content-length", str(len(body)).encode()),
    ]
    if extra_headers:
        headers.extend(extra_headers)

    await send({
        "type": "http.response.start",
        "status": status,
        "headers": headers,
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
