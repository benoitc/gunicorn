#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Deterministic apps for the stress suite.

One module exposes a WSGI callable (``wsgi``) and an ASGI callable (``asgi``)
that answer the same endpoints, so the same load scenario drives every worker.
The ASGI callable also serves WebSocket routes, which only the asgi worker
supports.

Every response is verifiable under load:

* ``/echo`` returns the body it received and an ``X-Body-SHA256`` header of
  those exact bytes, so a client can prove the body was neither truncated nor
  corrupted.
* Every response echoes the request's ``X-Request-Id`` header, so a client can
  prove one request's response never carries another request's identifier.
"""

import asyncio
import hashlib
import json
import time

PATTERN = b"0123456789abcdef"
SMALL = b"gunicorn-stress-ok\n"
MAX_SIZE = 100 * 1024 * 1024
CHUNK = 65536


def _filled(size):
    """A deterministic body of ``size`` bytes."""
    if size <= 0:
        return b""
    reps = size // len(PATTERN) + 1
    return (PATTERN * reps)[:size]


def _int(value, default, cap):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    if n < 0:
        return default
    return min(n, cap)


# --------------------------------------------------------------------------- #
# WSGI
# --------------------------------------------------------------------------- #

def wsgi(environ, start_response):
    from urllib.parse import parse_qs

    path = environ.get("PATH_INFO", "/")
    query = parse_qs(environ.get("QUERY_STRING", ""))
    req_id = environ.get("HTTP_X_REQUEST_ID", "")
    base = [("x-request-id", req_id)]

    def respond(status, headers, body):
        start_response(status, base + headers)
        return body

    if path == "/health":
        return respond("200 OK", [("content-type", "text/plain")], [b"OK"])

    if path == "/small":
        return respond("200 OK", [("content-type", "text/plain")], [SMALL])

    if path == "/echo":
        length = int(environ.get("CONTENT_LENGTH") or 0)
        body = environ["wsgi.input"].read(length) if length else b""
        digest = hashlib.sha256(body).hexdigest()
        return respond(
            "200 OK",
            [("content-type", "application/octet-stream"), ("x-body-sha256", digest)],
            [body])

    if path == "/large":
        size = _int(query.get("size", [None])[0], 1024 * 1024, MAX_SIZE)
        body = _filled(size)
        digest = hashlib.sha256(body).hexdigest()
        start_response("200 OK", base + [
            ("content-type", "application/octet-stream"),
            ("content-length", str(size)), ("x-body-sha256", digest)])
        return (body[i:i + CHUNK] for i in range(0, len(body), CHUNK))

    if path == "/stream":
        chunks = _int(query.get("chunks", [None])[0], 10, 100000)
        start_response("200 OK", base + [("content-type", "text/plain")])

        def gen():
            for i in range(chunks):
                yield b"%d\n" % i
        return gen()

    if path == "/slow":
        ms = _int(query.get("ms", [None])[0], 100, 60000)
        time.sleep(ms / 1000.0)
        return respond("200 OK", [("content-type", "text/plain")], [b"slept"])

    if path == "/error":
        code = _int(query.get("code", [None])[0], 500, 599)
        return respond("%d Error" % code, [("content-type", "text/plain")],
                       [b"error"])

    if path == "/meta":
        payload = json.dumps({
            "method": environ.get("REQUEST_METHOD"),
            "path": path,
            "query": environ.get("QUERY_STRING", ""),
            "protocol": environ.get("SERVER_PROTOCOL"),
            "forwarded_for": environ.get("HTTP_X_FORWARDED_FOR", ""),
            "forwarded_proto": environ.get("HTTP_X_FORWARDED_PROTO", ""),
            "real_ip": environ.get("HTTP_X_REAL_IP", ""),
            "host": environ.get("HTTP_HOST", ""),
        }).encode()
        return respond("200 OK", [("content-type", "application/json")], [payload])

    return respond("404 Not Found", [("content-type", "text/plain")], [b"not found"])


# --------------------------------------------------------------------------- #
# ASGI
# --------------------------------------------------------------------------- #

async def asgi(scope, receive, send):
    if scope["type"] == "lifespan":
        await _lifespan(scope, receive, send)
        return
    if scope["type"] == "websocket":
        await _websocket(scope, receive, send)
        return
    if scope["type"] == "http":
        await _http(scope, receive, send)


async def _lifespan(scope, receive, send):
    while True:
        message = await receive()
        if message["type"] == "lifespan.startup":
            await send({"type": "lifespan.startup.complete"})
        elif message["type"] == "lifespan.shutdown":
            await send({"type": "lifespan.shutdown.complete"})
            return


def _query(scope):
    from urllib.parse import parse_qs
    return parse_qs(scope.get("query_string", b"").decode())


def _header(scope, name):
    key = name.lower().encode()
    for k, v in scope.get("headers", []):
        if k.lower() == key:
            return v.decode()
    return ""


async def _read_body(receive):
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if not message.get("more_body"):
            break
    return body


async def _http(scope, receive, send):
    path = scope["path"]
    query = _query(scope)
    req_id = _header(scope, "x-request-id")
    base = [(b"x-request-id", req_id.encode())]

    async def start(status, headers):
        await send({"type": "http.response.start", "status": status,
                    "headers": base + headers})

    async def body(data, more=False):
        await send({"type": "http.response.body", "body": data, "more_body": more})

    if path == "/health":
        await start(200, [(b"content-type", b"text/plain")])
        await body(b"OK")
        return

    if path == "/small":
        await start(200, [(b"content-type", b"text/plain")])
        await body(SMALL)
        return

    if path == "/echo":
        data = await _read_body(receive)
        digest = hashlib.sha256(data).hexdigest()
        await start(200, [(b"content-type", b"application/octet-stream"),
                          (b"x-body-sha256", digest.encode())])
        await body(data)
        return

    if path == "/large":
        size = _int(query.get("size", [None])[0], 1024 * 1024, MAX_SIZE)
        data = _filled(size)
        digest = hashlib.sha256(data).hexdigest()
        await start(200, [(b"content-type", b"application/octet-stream"),
                          (b"content-length", str(size).encode()),
                          (b"x-body-sha256", digest.encode())])
        for i in range(0, len(data), CHUNK):
            await body(data[i:i + CHUNK], more=i + CHUNK < len(data))
        if not data:
            await body(b"")
        return

    if path == "/stream":
        chunks = _int(query.get("chunks", [None])[0], 10, 100000)
        await start(200, [(b"content-type", b"text/plain")])
        for i in range(chunks):
            await body(b"%d\n" % i, more=True)
        await body(b"")
        return

    if path == "/slow":
        ms = _int(query.get("ms", [None])[0], 100, 60000)
        await asyncio.sleep(ms / 1000.0)
        await start(200, [(b"content-type", b"text/plain")])
        await body(b"slept")
        return

    if path == "/error":
        code = _int(query.get("code", [None])[0], 500, 599)
        await start(code, [(b"content-type", b"text/plain")])
        await body(b"error")
        return

    if path == "/meta":
        payload = json.dumps({
            "method": scope.get("method"),
            "path": path,
            "query": scope.get("query_string", b"").decode(),
            "protocol": scope.get("http_version"),
            "forwarded_for": _header(scope, "x-forwarded-for"),
            "forwarded_proto": _header(scope, "x-forwarded-proto"),
            "real_ip": _header(scope, "x-real-ip"),
            "host": _header(scope, "host"),
        }).encode()
        await start(200, [(b"content-type", b"application/json")])
        await body(payload)
        return

    await start(404, [(b"content-type", b"text/plain")])
    await body(b"not found")


async def _websocket(scope, receive, send):
    path = scope["path"]
    connect = await receive()
    if connect["type"] != "websocket.connect":
        return
    await send({"type": "websocket.accept"})

    if path == "/ws/close":
        await send({"type": "websocket.close", "code": 1000})
        return

    while True:
        message = await receive()
        if message["type"] == "websocket.disconnect":
            return
        if message["type"] != "websocket.receive":
            continue
        if path == "/ws/echo-binary":
            await send({"type": "websocket.send",
                        "bytes": message.get("bytes") or b""})
        elif path == "/ws/ping":
            await send({"type": "websocket.send", "text": "pong"})
        else:  # /ws/echo and /ws/long
            if message.get("text") is not None:
                await send({"type": "websocket.send", "text": message["text"]})
            else:
                await send({"type": "websocket.send",
                            "bytes": message.get("bytes") or b""})


# Module-level aliases so ``gunicorn stress_app:app`` works for either worker;
# the entrypoint picks ``stress_app:wsgi`` or ``stress_app:asgi`` by worker.
app = wsgi
application = wsgi
