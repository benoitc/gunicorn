#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""The ASGI application every server variant runs.

One app, so gunicorn's native worker, gunicorn with Uvicorn's worker and
Uvicorn itself answer exactly the same thing. Routes:

    /            13-byte text body, Content-Length (the main workload)
    /a%20b/c     same body; a percent-encoded target
    /large       1 MiB body, Content-Length
    /stream      16 x 4 KiB chunks, no Content-Length (chunked)
    /echo        reads the whole request body, answers its length
"""

SMALL = b"Hello, World!"
LARGE = b"x" * (1024 * 1024)
CHUNK = b"y" * 4096

_SMALL_HEADERS = [(b"content-type", b"text/plain"),
                  (b"content-length", str(len(SMALL)).encode())]
_LARGE_HEADERS = [(b"content-type", b"application/octet-stream"),
                  (b"content-length", str(len(LARGE)).encode())]


async def app(scope, receive, send):
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

    path = scope["path"]
    if path == "/large":
        await send({"type": "http.response.start", "status": 200,
                    "headers": _LARGE_HEADERS})
        await send({"type": "http.response.body", "body": LARGE})
        return
    if path == "/stream":
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/octet-stream")]})
        for _ in range(15):
            await send({"type": "http.response.body", "body": CHUNK,
                        "more_body": True})
        await send({"type": "http.response.body", "body": CHUNK})
        return
    if path == "/echo":
        size = 0
        while True:
            message = await receive()
            size += len(message.get("body", b""))
            if not message.get("more_body"):
                break
        body = str(size).encode()
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/plain"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
        return

    # "/" and the percent-encoded target
    await send({"type": "http.response.start", "status": 200,
                "headers": _SMALL_HEADERS})
    await send({"type": "http.response.body", "body": SMALL})
