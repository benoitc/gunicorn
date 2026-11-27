# ASGI Worker

Gunicorn includes a native ASGI worker that enables running async Python web frameworks
like FastAPI, Starlette, and Quart without external dependencies like Uvicorn.

## Quick Start

```bash
# Install gunicorn
pip install gunicorn

# Run an ASGI application
gunicorn myapp:app --worker-class asgi --workers 4
```

For FastAPI applications:

```bash
gunicorn main:app --worker-class asgi --bind 0.0.0.0:8000
```

## Features

The ASGI worker provides:

- **HTTP/1.1** with keepalive connections
- **HTTP/2** with multiplexing, over TLS or cleartext h2c behind a trusted proxy
- **WebSocket** support for real-time applications
- **Lifespan protocol** for startup/shutdown hooks
- **Optional fast HTTP parser** via C extension for high throughput
- **Optional uvloop** for improved event loop performance
- **SSL/TLS** support
- **uWSGI protocol** for nginx `uwsgi_pass` integration

## Configuration

### Worker Class

Set the worker class to `asgi`:

```bash
gunicorn myapp:app --worker-class asgi
```

Or in a configuration file:

```python
# gunicorn.conf.py
worker_class = "asgi"
```

### Event Loop

Control which asyncio event loop implementation to use:

| Value    | Description |
|----------|-------------|
| `auto`   | Use uvloop if available, otherwise asyncio (default) |
| `asyncio`| Use Python's built-in asyncio event loop |
| `uvloop` | Use uvloop (must be installed separately) |

```bash
gunicorn myapp:app --worker-class asgi --asgi-loop uvloop
```

To use uvloop, install it first:

```bash
pip install uvloop
```

### Lifespan Protocol

The lifespan protocol lets your application run code at startup and shutdown.
This is essential for frameworks that need to initialize database connections,
caches, or background tasks.

| Value  | Description |
|--------|-------------|
| `auto` | Detect if app supports lifespan, enable if so (default) |
| `on`   | Always run lifespan protocol (fail if unsupported) |
| `off`  | Never run lifespan protocol |

```bash
gunicorn myapp:app --worker-class asgi --asgi-lifespan on
```

Example FastAPI application using lifespan:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize resources
    print("Starting up...")
    yield
    # Shutdown: cleanup resources
    print("Shutting down...")

app = FastAPI(lifespan=lifespan)
```

### Root Path

When running behind a reverse proxy that mounts your application at a subpath,
set `root_path` so your application knows its mount point:

```bash
gunicorn myapp:app --worker-class asgi --root-path /api
```

This is equivalent to the `SCRIPT_NAME` in WSGI applications.

### Worker Connections

Control the maximum number of concurrent connections per worker:

```bash
gunicorn myapp:app --worker-class asgi --worker-connections 1000
```

!!! note
    Unlike sync workers, the `--threads` option has no effect on ASGI workers.
    Use `--worker-connections` to control concurrency.

## WebSocket Support

The ASGI worker supports WebSocket connections out of the box. No additional
configuration is required.

Example with Starlette:

```python
from starlette.applications import Starlette
from starlette.routing import WebSocketRoute

async def websocket_endpoint(websocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        await websocket.send_text(f"Echo: {data}")

app = Starlette(routes=[
    WebSocketRoute("/ws", websocket_endpoint),
])
```

Each message is held in memory until its last frame arrives, so messages are
limited to 16 MiB. A larger message closes the connection with code 1009. To
change the limit:

```bash
gunicorn app:app -k asgi --websocket-max-message-size 67108864
```

While the application does not call `receive()`, gunicorn stops reading from
the socket once a few messages are waiting, so a fast client cannot grow the
worker's memory.

## Production Deployment

### With Nginx (HTTP Proxy)

```nginx
upstream gunicorn {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name example.com;

    location / {
        proxy_pass http://gunicorn;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # WebSocket support
    location /ws {
        proxy_pass http://gunicorn;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

### With Nginx (uWSGI Protocol)

For better performance, you can use nginx's native uWSGI protocol support:

```bash
gunicorn myapp:app --worker-class asgi --protocol uwsgi --bind 127.0.0.1:8000
```

```nginx
upstream gunicorn {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name example.com;

    location / {
        uwsgi_pass gunicorn;
        include uwsgi_params;
    }
}
```

!!! note
    WebSocket connections are not supported when using the uWSGI protocol.
    Use HTTP proxy for WebSocket endpoints.

See [uWSGI Protocol](uwsgi.md) for more details on uWSGI protocol configuration.

### Recommended Settings

For production ASGI deployments:

```python
# gunicorn.conf.py
worker_class = "asgi"
workers = 4  # Number of worker processes
worker_connections = 1000  # Max connections per worker
keepalive = 5  # Keepalive timeout
timeout = 120  # Worker timeout
graceful_timeout = 30  # Graceful shutdown timeout

# Performance tuning
asgi_loop = "auto"  # Use uvloop if available
asgi_lifespan = "auto"  # Auto-detect lifespan support
```

## Performance

### Fast HTTP Parser

For maximum performance, install the optional `gunicorn_h1c` C extension:

```bash
pip install gunicorn[fast]
```

This installs gunicorn_h1c 0.6.14 or later, a C HTTP/1 parser. It accepts and
rejects the same requests as the pure Python parser, so you can switch between
them without changing how requests are framed or which ones get a 400.

The parser is automatically used when available (`--http-parser auto`), or you
can explicitly require it:

```bash
gunicorn myapp:app --worker-class asgi --http-parser fast
```

| Parser | Description |
|--------|-------------|
| `auto` | Use fast parser if available, otherwise Python (default) |
| `fast` | Require fast parser, fail if unavailable |
| `python` | Force pure Python parser |

### Performance Tips

1. **Use uvloop** for improved event loop performance:
   ```bash
   pip install uvloop
   gunicorn myapp:app --worker-class asgi --asgi-loop uvloop
   ```

2. **Install the fast parser** for optimized HTTP parsing:
   ```bash
   pip install gunicorn[fast]
   ```

3. **Tune worker count** based on CPU cores:
   ```bash
   gunicorn myapp:app --worker-class asgi --workers $(nproc)
   ```

4. **Increase connections** for I/O-bound applications:
   ```bash
   gunicorn myapp:app --worker-class asgi --worker-connections 2000
   ```

### Measure performance

Gunicorn ships the benchmark it is tuned with in `benchmarks/asgi/`. It runs
the same app on gunicorn's ASGI worker (with each parser), on Uvicorn and on
gunicorn with Uvicorn's worker, in alternating rounds, and reports requests
per second, latency, CPU and memory for each.

```bash
pip install -e . -r benchmarks/asgi/requirements.txt
python benchmarks/asgi/run.py --workloads small_keepalive stream_response

# compare with another revision, in the same alternating rounds
git worktree add /tmp/gunicorn-old <commit>
python benchmarks/asgi/run.py --baseline-root /tmp/gunicorn-old
```

`benchmarks/asgi/profile_requests.py` shows where one request spends its time,
in process, without the network. See `benchmarks/asgi/README.md` for every
workload and option.

On an Apple M4 Pro with one worker, uvloop and the fast parser, gunicorn's
ASGI worker serves small requests at about 95% of Uvicorn's rate, uploads at
about the same rate, and streamed and 1 MiB responses at about 90%. Requests with
many headers are the slowest case, at about 80%. Measure on your own hardware
before you rely on these numbers.

## HTTP/1.1 request handling

Both parsers handle requests the same way. These are the answers you can see
from a client:

| Request | Answer |
|---------|--------|
| `Expect: 100-continue` on HTTP/1.1 | `100 Continue` when the app first reads the body; none if the app answers first or the body came with the headers |
| Malformed request line, header or chunked body | `400 Bad Request`, connection closed |
| `Transfer-Encoding` that does not end with `chunked`, such as `gzip` or `identity` alone | `400 Bad Request`, connection closed (RFC 9112 §6.3) |
| Unknown transfer coding, such as `foo, chunked` | `501 Not Implemented`, connection closed |
| Request line over `limit_request_line` | `414 URI Too Long` |
| Header section over the header limits | `431 Request Header Fields Too Large` |

Error responses carry the standard reason phrase in the status line and the
error text in the body.

!!! note
    A client that sends `Transfer-Encoding: identity` gets a 400. Drop the
    header: `identity` is no longer a transfer coding.

## Comparison with Other ASGI Servers

| Feature | Gunicorn ASGI | Uvicorn | Hypercorn |
|---------|---------------|---------|-----------|
| Process management | Built-in | External | Built-in |
| HTTP/2 | Yes | No | Yes |
| WebSocket | Yes | Yes | Yes |
| Lifespan | Yes | Yes | Yes |
| uvloop support | Yes | Yes | Yes |

!!! note
    HTTP/2 requires the h2 library, and TLS unless you enable cleartext h2c
    behind a trusted proxy. See [HTTP/2 Support](guides/http2.md) for details.

Gunicorn's ASGI worker provides the same process management, logging, and
configuration capabilities you're familiar with from WSGI deployments.

## Troubleshooting

### Lifespan startup failed

If you see "ASGI lifespan startup failed", the application either sent
`lifespan.startup.failed` (for example because a lifespan handler raised) or,
with `--asgi-lifespan on`, did not complete the lifespan protocol. Gunicorn
stops in both cases. Fix the application, or set `--asgi-lifespan off` (or
`auto` for an app that does not implement lifespan).

### Connection limits

If you're hitting connection limits, increase `--worker-connections` or add
more workers with `--workers`.

### Slow responses under load

Try using uvloop for better performance:

```bash
pip install uvloop
gunicorn myapp:app --worker-class asgi --asgi-loop uvloop
```

## Framework Compatibility

The ASGI worker has been tested for compatibility with major ASGI frameworks.

| Framework | HTTP Scope | HTTP Messages | WebSocket | Lifespan | Streaming | Total |
|-----------|---------|---------|---------|---------|---------|-------|
| Django + Channels | 19/19 | 18/19 | 19/19 | 8/8 | 9/9 | 73/74 |
| FastAPI | 19/19 | 18/19 | 19/19 | 8/8 | 9/9 | 73/74 |
| Starlette | 19/19 | 18/19 | 19/19 | 8/8 | 9/9 | 73/74 |
| Quart | 19/19 | 18/19 | 19/19 | 8/8 | 9/9 | 73/74 |
| Litestar | 19/19 | 18/19 | 19/19 | 8/8 | 9/9 | 73/74 |
| BlackSheep | 19/19 | 18/19 | 19/19 | 8/8 | 9/9 | 73/74 |

**Overall:** 438/444 tests passed (98%)

!!! note
    The compatibility test suite is located in `tests/docker/asgi_framework_compat/`.
    Run `docker compose up -d --build` followed by `pytest tests/ -v` to execute the tests.

## See Also

- [Settings Reference](reference/settings.md#asgi_loop) - All ASGI-related settings
- [Deploy](deploy.md) - General deployment guidance
- [Design](design.md) - Worker architecture overview
