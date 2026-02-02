#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Streaming test application for ASGI compliance testing.

Provides endpoints for testing chunked transfer encoding,
Server-Sent Events (SSE), and streaming responses.
"""

import asyncio
import json
import time


async def app(scope, receive, send):
    """Main ASGI streaming application."""
    if scope["type"] == "lifespan":
        await handle_lifespan(scope, receive, send)
        return

    if scope["type"] != "http":
        return

    path = scope["path"]

    # Route to appropriate handler
    if path == "/streaming":
        await handle_streaming(scope, receive, send)
    elif path == "/sse":
        await handle_sse(scope, receive, send)
    elif path == "/chunked":
        await handle_chunked(scope, receive, send)
    elif path == "/slow-stream":
        await handle_slow_stream(scope, receive, send)
    elif path == "/large-stream":
        await handle_large_stream(scope, receive, send)
    elif path == "/infinite":
        await handle_infinite(scope, receive, send)
    elif path == "/echo-stream":
        await handle_echo_stream(scope, receive, send)
    elif path == "/ndjson":
        await handle_ndjson(scope, receive, send)
    elif path == "/health":
        await handle_health(scope, receive, send)
    else:
        await handle_not_found(scope, receive, send)


async def handle_lifespan(scope, receive, send):
    """Handle ASGI lifespan events."""
    while True:
        message = await receive()
        if message["type"] == "lifespan.startup":
            await send({"type": "lifespan.startup.complete"})
        elif message["type"] == "lifespan.shutdown":
            await send({"type": "lifespan.shutdown.complete"})
            return


async def handle_streaming(scope, receive, send):
    """Basic streaming response without Content-Length."""
    await drain_body(receive)

    # Parse chunk count from query
    query = scope["query_string"].decode("latin-1")
    chunks = 5

    for param in query.split("&"):
        if param.startswith("chunks="):
            try:
                chunks = int(param[7:])
                chunks = min(chunks, 100)
            except ValueError:
                pass

    # Start response without Content-Length (triggers chunked encoding)
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            (b"content-type", b"text/plain"),
            # No content-length - server should use chunked encoding
        ],
    })

    # Send chunks
    for i in range(chunks):
        chunk = f"Chunk {i + 1} of {chunks}\n".encode("utf-8")
        await send({
            "type": "http.response.body",
            "body": chunk,
            "more_body": i < chunks - 1,
        })

    # Final empty body to signal end (if not already done)
    if chunks == 0:
        await send({
            "type": "http.response.body",
            "body": b"",
            "more_body": False,
        })


async def handle_sse(scope, receive, send):
    """Server-Sent Events stream."""
    await drain_body(receive)

    # Parse event count from query
    query = scope["query_string"].decode("latin-1")
    events = 5
    delay = 0.5

    for param in query.split("&"):
        if param.startswith("events="):
            try:
                events = int(param[7:])
                events = min(events, 100)
            except ValueError:
                pass
        elif param.startswith("delay="):
            try:
                delay = float(param[6:])
                delay = min(delay, 5.0)
            except ValueError:
                pass

    # SSE response headers
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            (b"content-type", b"text/event-stream"),
            (b"cache-control", b"no-cache"),
            (b"connection", b"keep-alive"),
            (b"x-accel-buffering", b"no"),  # Disable nginx buffering
        ],
    })

    # Send SSE events
    for i in range(events):
        event_data = {
            "id": i + 1,
            "total": events,
            "timestamp": time.time(),
        }

        # Format as SSE
        sse_message = f"id: {i + 1}\nevent: message\ndata: {json.dumps(event_data)}\n\n"

        await send({
            "type": "http.response.body",
            "body": sse_message.encode("utf-8"),
            "more_body": i < events - 1,
        })

        if i < events - 1:
            await asyncio.sleep(delay)

    # Send final empty body if needed
    if events == 0:
        await send({
            "type": "http.response.body",
            "body": b"",
            "more_body": False,
        })


async def handle_chunked(scope, receive, send):
    """Explicit chunked response with variable chunk sizes."""
    await drain_body(receive)

    # Parse parameters from query
    query = scope["query_string"].decode("latin-1")
    chunk_sizes = [100, 500, 1000, 50, 200]  # Default varied sizes

    for param in query.split("&"):
        if param.startswith("sizes="):
            try:
                sizes_str = param[6:]
                chunk_sizes = [int(s) for s in sizes_str.split(",")]
                chunk_sizes = [min(s, 100000) for s in chunk_sizes]  # 100KB max per chunk
            except ValueError:
                pass

    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            (b"content-type", b"application/octet-stream"),
        ],
    })

    # Send chunks of specified sizes
    for i, size in enumerate(chunk_sizes):
        chunk = bytes([i % 256] * size)
        await send({
            "type": "http.response.body",
            "body": chunk,
            "more_body": i < len(chunk_sizes) - 1,
        })


async def handle_slow_stream(scope, receive, send):
    """Slow streaming response with configurable delays."""
    await drain_body(receive)

    query = scope["query_string"].decode("latin-1")
    chunks = 10
    delay = 0.5

    for param in query.split("&"):
        if param.startswith("chunks="):
            try:
                chunks = int(param[7:])
                chunks = min(chunks, 50)
            except ValueError:
                pass
        elif param.startswith("delay="):
            try:
                delay = float(param[6:])
                delay = min(delay, 5.0)
            except ValueError:
                pass

    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            (b"content-type", b"text/plain"),
        ],
    })

    for i in range(chunks):
        timestamp = time.time()
        chunk = f"[{timestamp:.3f}] Slow chunk {i + 1}/{chunks}\n".encode("utf-8")

        await send({
            "type": "http.response.body",
            "body": chunk,
            "more_body": i < chunks - 1,
        })

        if i < chunks - 1:
            await asyncio.sleep(delay)


async def handle_large_stream(scope, receive, send):
    """Stream a large response in chunks."""
    await drain_body(receive)

    query = scope["query_string"].decode("latin-1")
    total_size = 1024 * 1024  # 1MB default
    chunk_size = 64 * 1024  # 64KB chunks

    for param in query.split("&"):
        if param.startswith("size="):
            try:
                total_size = int(param[5:])
                total_size = min(total_size, 100 * 1024 * 1024)  # 100MB max
            except ValueError:
                pass
        elif param.startswith("chunk="):
            try:
                chunk_size = int(param[6:])
                chunk_size = min(chunk_size, 1024 * 1024)  # 1MB max chunk
            except ValueError:
                pass

    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            (b"content-type", b"application/octet-stream"),
        ],
    })

    sent = 0
    while sent < total_size:
        remaining = total_size - sent
        current_chunk_size = min(chunk_size, remaining)
        chunk = b"x" * current_chunk_size
        sent += current_chunk_size

        await send({
            "type": "http.response.body",
            "body": chunk,
            "more_body": sent < total_size,
        })


async def handle_infinite(scope, receive, send):
    """Infinite stream (until client disconnects or limit reached)."""
    await drain_body(receive)

    query = scope["query_string"].decode("latin-1")
    max_chunks = 1000  # Safety limit
    delay = 0.1

    for param in query.split("&"):
        if param.startswith("max="):
            try:
                max_chunks = int(param[4:])
                max_chunks = min(max_chunks, 10000)
            except ValueError:
                pass
        elif param.startswith("delay="):
            try:
                delay = float(param[6:])
                delay = max(delay, 0.01)  # Min 10ms
            except ValueError:
                pass

    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            (b"content-type", b"text/plain"),
        ],
    })

    try:
        for i in range(max_chunks):
            chunk = f"Infinite stream chunk {i + 1}\n".encode("utf-8")

            await send({
                "type": "http.response.body",
                "body": chunk,
                "more_body": i < max_chunks - 1,
            })

            if i < max_chunks - 1:
                await asyncio.sleep(delay)
    except Exception:
        # Client disconnected
        pass


async def handle_echo_stream(scope, receive, send):
    """Echo request body as a stream."""
    # Start response immediately
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            (b"content-type", b"application/octet-stream"),
        ],
    })

    # Stream request body to response
    chunk_count = 0
    while True:
        message = await receive()
        body = message.get("body", b"")
        more_body = message.get("more_body", False)

        if body:
            chunk_count += 1
            # Add chunk info prefix
            prefix = f"[chunk {chunk_count}]: ".encode("utf-8")
            await send({
                "type": "http.response.body",
                "body": prefix + body + b"\n",
                "more_body": True,
            })

        if not more_body:
            break

    # Final chunk with summary
    summary = f"Total chunks received: {chunk_count}\n".encode("utf-8")
    await send({
        "type": "http.response.body",
        "body": summary,
        "more_body": False,
    })


async def handle_ndjson(scope, receive, send):
    """Newline-delimited JSON stream."""
    await drain_body(receive)

    query = scope["query_string"].decode("latin-1")
    records = 10
    delay = 0.2

    for param in query.split("&"):
        if param.startswith("records="):
            try:
                records = int(param[8:])
                records = min(records, 1000)
            except ValueError:
                pass
        elif param.startswith("delay="):
            try:
                delay = float(param[6:])
                delay = min(delay, 5.0)
            except ValueError:
                pass

    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            (b"content-type", b"application/x-ndjson"),
        ],
    })

    for i in range(records):
        record = {
            "id": i + 1,
            "timestamp": time.time(),
            "data": f"Record {i + 1}",
        }

        line = json.dumps(record) + "\n"

        await send({
            "type": "http.response.body",
            "body": line.encode("utf-8"),
            "more_body": i < records - 1,
        })

        if i < records - 1 and delay > 0:
            await asyncio.sleep(delay)


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


async def handle_not_found(scope, receive, send):
    """Handle 404 Not Found."""
    await drain_body(receive)

    body = b"Not Found"

    await send({
        "type": "http.response.start",
        "status": 404,
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


async def drain_body(receive):
    """Drain the request body."""
    while True:
        message = await receive()
        if not message.get("more_body", False):
            break
