#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Simple ASGI test application for uWSGI protocol testing."""


async def app(scope, receive, send):
    """Simple ASGI application that echoes request info."""
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return

    if scope["type"] != "http":
        return

    # Read body
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if not message.get("more_body", False):
            break

    # Build response
    method = scope["method"]
    path = scope["path"]
    query = scope.get("query_string", b"").decode("utf-8")

    response_body = f"Method: {method}\nPath: {path}\nQuery: {query}\nBody: {body.decode('utf-8')}\n"
    response_bytes = response_body.encode("utf-8")

    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            [b"content-type", b"text/plain"],
            [b"content-length", str(len(response_bytes)).encode()],
        ],
    })
    await send({
        "type": "http.response.body",
        "body": response_bytes,
    })
