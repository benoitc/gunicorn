#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
WebSocket ASGI application example.

Run with:
    gunicorn -k asgi examples.asgi.websocket_app:app

Test with:
    # Using websocat (install with: cargo install websocat)
    websocat ws://127.0.0.1:8000/ws

    # Or using Python websockets library
    python -c "
    import asyncio
    import websockets
    async def test():
        async with websockets.connect('ws://127.0.0.1:8000/ws') as ws:
            await ws.send('Hello')
            print(await ws.recv())
    asyncio.run(test())
    "
"""


async def app(scope, receive, send):
    """ASGI application with WebSocket support."""

    if scope["type"] == "lifespan":
        await handle_lifespan(scope, receive, send)
    elif scope["type"] == "http":
        await handle_http(scope, receive, send)
    elif scope["type"] == "websocket":
        await handle_websocket(scope, receive, send)
    else:
        raise ValueError(f"Unknown scope type: {scope['type']}")


async def handle_lifespan(scope, receive, send):
    """Handle lifespan events."""
    while True:
        message = await receive()
        if message["type"] == "lifespan.startup":
            await send({"type": "lifespan.startup.complete"})
        elif message["type"] == "lifespan.shutdown":
            await send({"type": "lifespan.shutdown.complete"})
            return


async def handle_http(scope, receive, send):
    """Handle HTTP requests - serve a simple HTML page for WebSocket testing."""
    path = scope["path"]

    if path == "/":
        html = HTML_PAGE.encode()
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"text/html"),
                (b"content-length", str(len(html)).encode()),
            ],
        })
        await send({
            "type": "http.response.body",
            "body": html,
        })
    else:
        await send({
            "type": "http.response.start",
            "status": 404,
            "headers": [(b"content-type", b"text/plain")],
        })
        await send({
            "type": "http.response.body",
            "body": b"Not Found",
        })


async def handle_websocket(scope, receive, send):
    """Handle WebSocket connections."""
    path = scope["path"]

    if path == "/ws":
        await echo_websocket(scope, receive, send)
    elif path == "/ws/chat":
        await chat_websocket(scope, receive, send)
    else:
        # Reject the connection
        await send({"type": "websocket.close", "code": 4004})


async def echo_websocket(scope, receive, send):
    """Echo WebSocket - sends back whatever it receives."""
    # Wait for connection
    message = await receive()
    if message["type"] != "websocket.connect":
        return

    # Accept the connection
    await send({"type": "websocket.accept"})

    # Echo loop
    try:
        while True:
            message = await receive()

            if message["type"] == "websocket.disconnect":
                break

            if message["type"] == "websocket.receive":
                if "text" in message:
                    # Echo text back
                    await send({
                        "type": "websocket.send",
                        "text": f"Echo: {message['text']}"
                    })
                elif "bytes" in message:
                    # Echo bytes back
                    await send({
                        "type": "websocket.send",
                        "bytes": message["bytes"]
                    })
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        try:
            await send({"type": "websocket.close", "code": 1000})
        except Exception:
            pass


async def chat_websocket(scope, receive, send):
    """Chat WebSocket - simple broadcast example."""
    message = await receive()
    if message["type"] != "websocket.connect":
        return

    await send({
        "type": "websocket.accept",
        "subprotocol": "chat"
    })

    await send({
        "type": "websocket.send",
        "text": "Welcome to the chat! Send messages and they will be echoed back."
    })

    try:
        while True:
            message = await receive()

            if message["type"] == "websocket.disconnect":
                break

            if message["type"] == "websocket.receive" and "text" in message:
                text = message["text"]
                await send({
                    "type": "websocket.send",
                    "text": f"[You]: {text}"
                })
    except Exception:
        pass


HTML_PAGE = """<!DOCTYPE html>
<html>
<head>
    <title>WebSocket Test</title>
    <style>
        body { font-family: sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }
        #messages { border: 1px solid #ccc; height: 300px; overflow-y: auto; padding: 10px; margin-bottom: 10px; }
        #input { width: 80%; padding: 10px; }
        button { padding: 10px 20px; }
        .sent { color: blue; }
        .received { color: green; }
        .error { color: red; }
    </style>
</head>
<body>
    <h1>WebSocket Test</h1>
    <div id="messages"></div>
    <input type="text" id="input" placeholder="Type a message...">
    <button onclick="sendMessage()">Send</button>
    <button onclick="connectWS()">Connect</button>
    <button onclick="disconnectWS()">Disconnect</button>

    <script>
        let ws = null;
        const messages = document.getElementById('messages');
        const input = document.getElementById('input');

        function log(msg, className) {
            const div = document.createElement('div');
            div.className = className || '';
            div.textContent = msg;
            messages.appendChild(div);
            messages.scrollTop = messages.scrollHeight;
        }

        function connectWS() {
            if (ws) {
                log('Already connected', 'error');
                return;
            }
            ws = new WebSocket('ws://' + window.location.host + '/ws');
            ws.onopen = () => log('Connected!', 'received');
            ws.onclose = () => { log('Disconnected', 'error'); ws = null; };
            ws.onerror = (e) => log('Error: ' + e, 'error');
            ws.onmessage = (e) => log(e.data, 'received');
        }

        function disconnectWS() {
            if (ws) ws.close();
        }

        function sendMessage() {
            if (!ws) { log('Not connected', 'error'); return; }
            const msg = input.value;
            if (!msg) return;
            ws.send(msg);
            log('Sent: ' + msg, 'sent');
            input.value = '';
        }

        input.onkeypress = (e) => { if (e.key === 'Enter') sendMessage(); };

        // Auto-connect
        connectWS();
    </script>
</body>
</html>
"""
