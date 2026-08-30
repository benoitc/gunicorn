"""WSGI and ASGI applications for the live HTTP/2 tests."""

import asyncio

BIG = b"x" * (4 * 1024 * 1024)


def wsgi(environ, start_response):
    path = environ["PATH_INFO"]
    if path == "/echo":
        body = environ["wsgi.input"].read()
        start_response("200 OK", [("content-type", "application/octet-stream")])
        return [body]
    if path == "/big":
        start_response("200 OK", [("content-type", "application/octet-stream")])
        return [BIG[i:i + 65536] for i in range(0, len(BIG), 65536)]
    if path == "/explode":
        start_response("200 OK", [("content-type", "text/plain")])

        def gen():
            yield b"first"
            raise RuntimeError("boom after headers")
        return gen()
    if path == "/headers":
        start_response("200 OK", [("content-type", "text/plain"), ("x-marker", "present")])
        return [b"ok"]
    if path == "/chunks":
        start_response("200 OK", [("content-type", "text/plain")])
        return [b"a", b"b", b""]
    start_response("200 OK", [("content-type", "text/plain")])
    return [b"ok"]


async def asgi(scope, receive, send):
    if scope["type"] != "http":
        return
    path = scope["path"]

    async def start(status=200, headers=()):
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"text/plain")] + list(headers)})

    if path == "/echo":
        body = b""
        while True:
            msg = await receive()
            body += msg.get("body", b"")
            if not msg.get("more_body"):
                break
        await start()
        await send({"type": "http.response.body", "body": body})
        return
    if path == "/big":
        await start()
        for i in range(0, len(BIG), 65536):
            await send({"type": "http.response.body", "body": BIG[i:i + 65536],
                        "more_body": True})
        await send({"type": "http.response.body", "body": b""})
        return
    if path == "/explode":
        await start()
        await send({"type": "http.response.body", "body": b"first", "more_body": True})
        raise RuntimeError("boom after headers")
    if path == "/headers":
        await start(headers=[(b"x-marker", b"present")])
        await send({"type": "http.response.body", "body": b"ok"})
        return
    if path == "/chunks":
        await start()
        await send({"type": "http.response.body", "body": b"a", "more_body": True})
        await send({"type": "http.response.body", "body": b"b", "more_body": True})
        await send({"type": "http.response.body", "body": b""})
        return
    if path == "/listen":
        async def listen():
            while True:
                msg = await receive()
                if msg["type"] == "http.disconnect":
                    return
        task = asyncio.get_running_loop().create_task(listen())
        await asyncio.sleep(0.2)
        await start()
        await send({"type": "http.response.body", "body": b"ok"})
        task.cancel()
        return
    await receive()
    await start()
    await send({"type": "http.response.body", "body": b"ok"})
