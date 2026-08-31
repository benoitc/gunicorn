"""Minimal ASGI application for h2spec conformance runs."""


async def app(scope, receive, send):
    if scope["type"] != "http":
        return
    while True:
        message = await receive()
        if not message.get("more_body", False):
            break
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"text/plain")],
    })
    await send({"type": "http.response.body", "body": b"ok"})
