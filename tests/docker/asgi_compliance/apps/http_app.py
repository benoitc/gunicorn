#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
HTTP test application for ASGI compliance testing.

Provides various endpoints to test HTTP request/response handling,
headers, body processing, and ASGI scope inspection.
"""

import json
import time


async def app(scope, receive, send):
    """Main ASGI HTTP application with multiple test endpoints."""
    if scope["type"] == "lifespan":
        await handle_lifespan(scope, receive, send)
        return

    if scope["type"] != "http":
        return

    path = scope["path"]
    method = scope["method"]

    # Route to appropriate handler
    if path == "/":
        await handle_root(scope, receive, send)
    elif path == "/echo":
        await handle_echo(scope, receive, send)
    elif path == "/headers":
        await handle_headers(scope, receive, send)
    elif path == "/scope":
        await handle_scope(scope, receive, send)
    elif path.startswith("/status"):
        await handle_status(scope, receive, send)
    elif path == "/large":
        await handle_large(scope, receive, send)
    elif path == "/method":
        await handle_method(scope, receive, send)
    elif path == "/query":
        await handle_query(scope, receive, send)
    elif path == "/post-json":
        await handle_post_json(scope, receive, send)
    elif path == "/delay":
        await handle_delay(scope, receive, send)
    elif path == "/health":
        await handle_health(scope, receive, send)
    elif path == "/early-hints":
        await handle_early_hints(scope, receive, send)
    elif path == "/cookies":
        await handle_cookies(scope, receive, send)
    elif path == "/redirect":
        await handle_redirect(scope, receive, send)
    else:
        await handle_not_found(scope, receive, send)


async def handle_lifespan(scope, receive, send):
    """Handle ASGI lifespan events."""
    while True:
        message = await receive()
        if message["type"] == "lifespan.startup":
            # Store startup time in state if available
            if "state" in scope:
                scope["state"]["started_at"] = time.time()
            await send({"type": "lifespan.startup.complete"})
        elif message["type"] == "lifespan.shutdown":
            await send({"type": "lifespan.shutdown.complete"})
            return


async def handle_root(scope, receive, send):
    """Handle root path - basic response."""
    body = b"Hello, ASGI!"

    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            (b"content-type", b"text/plain; charset=utf-8"),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({
        "type": "http.response.body",
        "body": body,
        "more_body": False,
    })


async def handle_echo(scope, receive, send):
    """Echo back the request body."""
    # Read the full request body
    body_parts = []
    while True:
        message = await receive()
        body = message.get("body", b"")
        if body:
            body_parts.append(body)
        if not message.get("more_body", False):
            break

    response_body = b"".join(body_parts)

    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            (b"content-type", b"application/octet-stream"),
            (b"content-length", str(len(response_body)).encode()),
        ],
    })
    await send({
        "type": "http.response.body",
        "body": response_body,
        "more_body": False,
    })


async def handle_headers(scope, receive, send):
    """Return request headers as JSON."""
    # Drain request body
    await drain_body(receive)

    # Convert headers to JSON-serializable format
    headers_dict = {}
    for name, value in scope["headers"]:
        name_str = name.decode("latin-1")
        value_str = value.decode("latin-1")
        if name_str in headers_dict:
            # Handle multiple headers with same name
            if isinstance(headers_dict[name_str], list):
                headers_dict[name_str].append(value_str)
            else:
                headers_dict[name_str] = [headers_dict[name_str], value_str]
        else:
            headers_dict[name_str] = value_str

    response_body = json.dumps(headers_dict, indent=2).encode("utf-8")

    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(response_body)).encode()),
        ],
    })
    await send({
        "type": "http.response.body",
        "body": response_body,
        "more_body": False,
    })


async def handle_scope(scope, receive, send):
    """Return ASGI scope as JSON for inspection."""
    # Drain request body
    await drain_body(receive)

    # Create a JSON-serializable version of the scope
    scope_json = {
        "type": scope["type"],
        "asgi": scope["asgi"],
        "http_version": scope["http_version"],
        "method": scope["method"],
        "scheme": scope["scheme"],
        "path": scope["path"],
        "raw_path": scope["raw_path"].decode("latin-1") if scope.get("raw_path") else None,
        "query_string": scope["query_string"].decode("latin-1") if scope.get("query_string") else "",
        "root_path": scope.get("root_path", ""),
        "headers": [
            [name.decode("latin-1"), value.decode("latin-1")]
            for name, value in scope["headers"]
        ],
        "server": list(scope["server"]) if scope.get("server") else None,
        "client": list(scope["client"]) if scope.get("client") else None,
    }

    # Include extensions if present
    if "extensions" in scope:
        scope_json["extensions"] = {}
        for ext_name, ext_value in scope["extensions"].items():
            if isinstance(ext_value, dict):
                scope_json["extensions"][ext_name] = ext_value
            else:
                scope_json["extensions"][ext_name] = str(ext_value)

    # Include state keys if present
    if "state" in scope:
        scope_json["state_keys"] = list(scope["state"].keys())

    response_body = json.dumps(scope_json, indent=2).encode("utf-8")

    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(response_body)).encode()),
        ],
    })
    await send({
        "type": "http.response.body",
        "body": response_body,
        "more_body": False,
    })


async def handle_status(scope, receive, send):
    """Return specific HTTP status code from query parameter."""
    # Drain request body
    await drain_body(receive)

    # Parse query string for status code
    query = scope["query_string"].decode("latin-1")
    status_code = 200

    for param in query.split("&"):
        if param.startswith("code="):
            try:
                status_code = int(param[5:])
            except ValueError:
                status_code = 400

    # Status code validation
    if status_code < 100 or status_code >= 600:
        status_code = 400

    body = f"Status: {status_code}".encode("utf-8")

    await send({
        "type": "http.response.start",
        "status": status_code,
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


async def handle_large(scope, receive, send):
    """Return a large response (1MB by default)."""
    # Drain request body
    await drain_body(receive)

    # Parse query string for size
    query = scope["query_string"].decode("latin-1")
    size = 1024 * 1024  # 1MB default

    for param in query.split("&"):
        if param.startswith("size="):
            try:
                size = int(param[5:])
                # Limit to 10MB
                size = min(size, 10 * 1024 * 1024)
            except ValueError:
                pass

    # Generate response body
    body = b"x" * size

    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            (b"content-type", b"application/octet-stream"),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({
        "type": "http.response.body",
        "body": body,
        "more_body": False,
    })


async def handle_method(scope, receive, send):
    """Return the HTTP method used."""
    # Drain request body
    await drain_body(receive)

    method = scope["method"]
    body = json.dumps({"method": method}).encode("utf-8")

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


async def handle_query(scope, receive, send):
    """Return parsed query parameters."""
    # Drain request body
    await drain_body(receive)

    query = scope["query_string"].decode("latin-1")
    params = {}

    if query:
        for param in query.split("&"):
            if "=" in param:
                key, value = param.split("=", 1)
                # Handle multiple values for same key
                if key in params:
                    if isinstance(params[key], list):
                        params[key].append(value)
                    else:
                        params[key] = [params[key], value]
                else:
                    params[key] = value
            else:
                params[param] = ""

    body = json.dumps({
        "raw": query,
        "params": params,
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


async def handle_post_json(scope, receive, send):
    """Parse JSON body and return it."""
    if scope["method"] != "POST":
        await send_error(send, 405, "Method Not Allowed")
        return

    # Read request body
    body_parts = []
    while True:
        message = await receive()
        body = message.get("body", b"")
        if body:
            body_parts.append(body)
        if not message.get("more_body", False):
            break

    request_body = b"".join(body_parts)

    try:
        data = json.loads(request_body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        await send_error(send, 400, f"Invalid JSON: {e}")
        return

    response = {
        "received": data,
        "type": type(data).__name__,
    }
    response_body = json.dumps(response).encode("utf-8")

    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(response_body)).encode()),
        ],
    })
    await send({
        "type": "http.response.body",
        "body": response_body,
        "more_body": False,
    })


async def handle_delay(scope, receive, send):
    """Respond after a delay (for timeout testing)."""
    import asyncio

    # Drain request body
    await drain_body(receive)

    # Parse delay from query string
    query = scope["query_string"].decode("latin-1")
    delay = 1.0  # Default 1 second

    for param in query.split("&"):
        if param.startswith("seconds="):
            try:
                delay = float(param[8:])
                # Limit to 30 seconds
                delay = min(delay, 30.0)
            except ValueError:
                pass

    await asyncio.sleep(delay)

    body = json.dumps({"delayed": delay}).encode("utf-8")

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


async def handle_early_hints(scope, receive, send):
    """Send 103 Early Hints before the response."""
    await drain_body(receive)

    # Send 103 Early Hints
    await send({
        "type": "http.response.informational",
        "status": 103,
        "headers": [
            (b"link", b"</style.css>; rel=preload; as=style"),
            (b"link", b"</script.js>; rel=preload; as=script"),
        ],
    })

    # Send actual response
    body = b"Response with Early Hints"

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


async def handle_cookies(scope, receive, send):
    """Set and return cookies."""
    await drain_body(receive)

    # Parse query for cookie values to set
    query = scope["query_string"].decode("latin-1")
    cookies_to_set = []

    for param in query.split("&"):
        if param.startswith("set="):
            cookie_value = param[4:]
            cookies_to_set.append((b"set-cookie", cookie_value.encode()))

    # Get existing cookies from request
    request_cookies = {}
    for name, value in scope["headers"]:
        if name == b"cookie":
            cookie_str = value.decode("latin-1")
            for cookie in cookie_str.split(";"):
                cookie = cookie.strip()
                if "=" in cookie:
                    k, v = cookie.split("=", 1)
                    request_cookies[k] = v

    response = {
        "request_cookies": request_cookies,
        "set_cookies": [c[1].decode() for c in cookies_to_set],
    }
    body = json.dumps(response).encode("utf-8")

    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
    ]
    headers.extend(cookies_to_set)

    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": headers,
    })
    await send({
        "type": "http.response.body",
        "body": body,
        "more_body": False,
    })


async def handle_redirect(scope, receive, send):
    """Redirect to another URL."""
    await drain_body(receive)

    # Parse query for redirect target
    query = scope["query_string"].decode("latin-1")
    location = "/"
    status = 302

    for param in query.split("&"):
        if param.startswith("to="):
            location = param[3:]
        elif param.startswith("status="):
            try:
                status = int(param[7:])
                if status not in (301, 302, 303, 307, 308):
                    status = 302
            except ValueError:
                pass

    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"location", location.encode()),
            (b"content-length", b"0"),
        ],
    })
    await send({
        "type": "http.response.body",
        "body": b"",
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
