#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
WebSocket test application for ASGI compliance testing.

Provides various WebSocket endpoints to test RFC 6455 compliance,
message handling, and protocol features.
"""

import json


async def app(scope, receive, send):
    """Main ASGI WebSocket application with multiple test endpoints."""
    if scope["type"] == "lifespan":
        await handle_lifespan(scope, receive, send)
        return

    if scope["type"] != "websocket":
        # Return 404 for non-WebSocket requests
        if scope["type"] == "http":
            await send_http_error(send, 404, "WebSocket endpoints only")
        return

    path = scope["path"]

    # Route to appropriate handler
    if path == "/ws/echo":
        await handle_echo(scope, receive, send)
    elif path == "/ws/echo-binary":
        await handle_echo_binary(scope, receive, send)
    elif path == "/ws/subprotocol":
        await handle_subprotocol(scope, receive, send)
    elif path.startswith("/ws/close"):
        await handle_close(scope, receive, send)
    elif path == "/ws/scope":
        await handle_scope(scope, receive, send)
    elif path == "/ws/reject":
        await handle_reject(scope, receive, send)
    elif path == "/ws/ping":
        await handle_ping(scope, receive, send)
    elif path == "/ws/broadcast":
        await handle_broadcast(scope, receive, send)
    elif path == "/ws/large":
        await handle_large_message(scope, receive, send)
    elif path == "/ws/fragmented":
        await handle_fragmented(scope, receive, send)
    elif path == "/ws/delay":
        await handle_delay(scope, receive, send)
    else:
        # Accept but immediately close for unknown paths
        await handle_unknown(scope, receive, send)


async def handle_lifespan(scope, receive, send):
    """Handle ASGI lifespan events."""
    while True:
        message = await receive()
        if message["type"] == "lifespan.startup":
            await send({"type": "lifespan.startup.complete"})
        elif message["type"] == "lifespan.shutdown":
            await send({"type": "lifespan.shutdown.complete"})
            return


async def handle_echo(scope, receive, send):
    """Echo text messages back to the client."""
    # Wait for connection
    message = await receive()
    if message["type"] != "websocket.connect":
        return

    # Accept the connection
    await send({"type": "websocket.accept"})

    # Echo messages until disconnect
    while True:
        message = await receive()

        if message["type"] == "websocket.receive":
            # Echo back text messages
            if "text" in message:
                await send({
                    "type": "websocket.send",
                    "text": message["text"],
                })
            elif "bytes" in message:
                # Convert binary to text for echo
                await send({
                    "type": "websocket.send",
                    "text": message["bytes"].decode("utf-8", errors="replace"),
                })

        elif message["type"] == "websocket.disconnect":
            break


async def handle_echo_binary(scope, receive, send):
    """Echo binary messages back to the client."""
    message = await receive()
    if message["type"] != "websocket.connect":
        return

    await send({"type": "websocket.accept"})

    while True:
        message = await receive()

        if message["type"] == "websocket.receive":
            if "bytes" in message:
                await send({
                    "type": "websocket.send",
                    "bytes": message["bytes"],
                })
            elif "text" in message:
                # Convert text to binary for echo
                await send({
                    "type": "websocket.send",
                    "bytes": message["text"].encode("utf-8"),
                })

        elif message["type"] == "websocket.disconnect":
            break


async def handle_subprotocol(scope, receive, send):
    """Negotiate WebSocket subprotocol."""
    message = await receive()
    if message["type"] != "websocket.connect":
        return

    # Get requested subprotocols
    requested = scope.get("subprotocols", [])

    # Prefer graphql-ws, then json, then first available
    selected = None
    preferred = ["graphql-ws", "json", "wamp"]

    for proto in preferred:
        if proto in requested:
            selected = proto
            break

    if not selected and requested:
        selected = requested[0]

    # Accept with selected subprotocol
    accept_msg = {"type": "websocket.accept"}
    if selected:
        accept_msg["subprotocol"] = selected

    await send(accept_msg)

    # Send confirmation message
    response = {
        "requested": requested,
        "selected": selected,
    }
    await send({
        "type": "websocket.send",
        "text": json.dumps(response),
    })

    # Wait for disconnect
    while True:
        message = await receive()
        if message["type"] == "websocket.disconnect":
            break


async def handle_close(scope, receive, send):
    """Close connection with specific code from query parameter."""
    message = await receive()
    if message["type"] != "websocket.connect":
        return

    await send({"type": "websocket.accept"})

    # Parse close code from query string
    query = scope["query_string"].decode("latin-1")
    close_code = 1000  # Normal closure
    close_reason = ""

    for param in query.split("&"):
        if param.startswith("code="):
            try:
                close_code = int(param[5:])
            except ValueError:
                pass
        elif param.startswith("reason="):
            close_reason = param[7:]

    # Send close with specified code
    close_msg = {
        "type": "websocket.close",
        "code": close_code,
    }
    if close_reason:
        close_msg["reason"] = close_reason

    await send(close_msg)


async def handle_scope(scope, receive, send):
    """Return WebSocket scope as JSON."""
    message = await receive()
    if message["type"] != "websocket.connect":
        return

    await send({"type": "websocket.accept"})

    # Create JSON-serializable scope
    scope_json = {
        "type": scope["type"],
        "asgi": scope["asgi"],
        "http_version": scope["http_version"],
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
        "subprotocols": scope.get("subprotocols", []),
    }

    await send({
        "type": "websocket.send",
        "text": json.dumps(scope_json, indent=2),
    })

    # Wait for disconnect
    while True:
        message = await receive()
        if message["type"] == "websocket.disconnect":
            break


async def handle_reject(scope, receive, send):
    """Reject the WebSocket connection."""
    message = await receive()
    if message["type"] != "websocket.connect":
        return

    # Close without accepting - this rejects the connection
    await send({
        "type": "websocket.close",
        "code": 1008,  # Policy violation
        "reason": "Connection rejected",
    })


async def handle_ping(scope, receive, send):
    """Echo ping messages (handled at protocol level, but test app behavior)."""
    message = await receive()
    if message["type"] != "websocket.connect":
        return

    await send({"type": "websocket.accept"})

    # Send a message indicating ping/pong is handled at protocol level
    await send({
        "type": "websocket.send",
        "text": json.dumps({
            "info": "Ping/pong is handled at the protocol level",
            "note": "Send any message to test echo",
        }),
    })

    while True:
        message = await receive()

        if message["type"] == "websocket.receive":
            # Echo back
            if "text" in message:
                await send({"type": "websocket.send", "text": message["text"]})
            elif "bytes" in message:
                await send({"type": "websocket.send", "bytes": message["bytes"]})

        elif message["type"] == "websocket.disconnect":
            break


async def handle_broadcast(scope, receive, send):
    """Simple broadcast simulation - echo message multiple times."""
    message = await receive()
    if message["type"] != "websocket.connect":
        return

    await send({"type": "websocket.accept"})

    # Parse broadcast count from query
    query = scope["query_string"].decode("latin-1")
    count = 3  # Default

    for param in query.split("&"):
        if param.startswith("count="):
            try:
                count = int(param[6:])
                count = min(count, 100)  # Limit
            except ValueError:
                pass

    while True:
        message = await receive()

        if message["type"] == "websocket.receive":
            text = message.get("text", "")

            # "Broadcast" by sending multiple copies
            for i in range(count):
                await send({
                    "type": "websocket.send",
                    "text": json.dumps({
                        "copy": i + 1,
                        "of": count,
                        "message": text,
                    }),
                })

        elif message["type"] == "websocket.disconnect":
            break


async def handle_large_message(scope, receive, send):
    """Test large message handling."""
    message = await receive()
    if message["type"] != "websocket.connect":
        return

    await send({"type": "websocket.accept"})

    # Parse size from query
    query = scope["query_string"].decode("latin-1")
    size = 64 * 1024  # 64KB default

    for param in query.split("&"):
        if param.startswith("size="):
            try:
                size = int(param[5:])
                size = min(size, 1024 * 1024)  # 1MB limit
            except ValueError:
                pass

    # Send large message
    large_data = "x" * size
    await send({
        "type": "websocket.send",
        "text": large_data,
    })

    # Echo any received messages
    while True:
        message = await receive()

        if message["type"] == "websocket.receive":
            if "text" in message:
                response = {
                    "received_length": len(message["text"]),
                    "sent_length": size,
                }
                await send({
                    "type": "websocket.send",
                    "text": json.dumps(response),
                })

        elif message["type"] == "websocket.disconnect":
            break


async def handle_fragmented(scope, receive, send):
    """Test fragmented message handling (assembled by protocol)."""
    message = await receive()
    if message["type"] != "websocket.connect":
        return

    await send({"type": "websocket.accept"})

    await send({
        "type": "websocket.send",
        "text": json.dumps({
            "info": "Fragmented frames are assembled at protocol level",
            "note": "This app receives complete messages",
        }),
    })

    # Echo messages with length info
    while True:
        message = await receive()

        if message["type"] == "websocket.receive":
            if "text" in message:
                await send({
                    "type": "websocket.send",
                    "text": json.dumps({
                        "received": message["text"],
                        "length": len(message["text"]),
                        "type": "text",
                    }),
                })
            elif "bytes" in message:
                await send({
                    "type": "websocket.send",
                    "text": json.dumps({
                        "length": len(message["bytes"]),
                        "type": "binary",
                    }),
                })

        elif message["type"] == "websocket.disconnect":
            break


async def handle_delay(scope, receive, send):
    """Test delayed responses."""
    import asyncio

    message = await receive()
    if message["type"] != "websocket.connect":
        return

    await send({"type": "websocket.accept"})

    # Parse delay from query
    query = scope["query_string"].decode("latin-1")
    delay = 1.0

    for param in query.split("&"):
        if param.startswith("seconds="):
            try:
                delay = float(param[8:])
                delay = min(delay, 30.0)  # 30s limit
            except ValueError:
                pass

    while True:
        message = await receive()

        if message["type"] == "websocket.receive":
            await asyncio.sleep(delay)
            if "text" in message:
                await send({
                    "type": "websocket.send",
                    "text": json.dumps({
                        "delayed_by": delay,
                        "message": message["text"],
                    }),
                })

        elif message["type"] == "websocket.disconnect":
            break


async def handle_unknown(scope, receive, send):
    """Handle unknown WebSocket paths - accept then close."""
    message = await receive()
    if message["type"] != "websocket.connect":
        return

    await send({"type": "websocket.accept"})
    await send({
        "type": "websocket.send",
        "text": json.dumps({
            "error": "Unknown path",
            "path": scope["path"],
        }),
    })
    await send({
        "type": "websocket.close",
        "code": 1000,
    })


async def send_http_error(send, status, message):
    """Send HTTP error response (for non-WebSocket requests)."""
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
