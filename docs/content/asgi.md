# ASGI Worker

!!! warning "Beta Feature"
    The ASGI worker is a beta feature introduced in Gunicorn 24.0.0. While it has been tested,
    the API and behavior may change in future releases. Please report any issues on
    [GitHub](https://github.com/benoitc/gunicorn/issues).

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
- **WebSocket** support for real-time applications
- **Lifespan protocol** for startup/shutdown hooks
- **Optional uvloop** for improved performance
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

## Comparison with Other ASGI Servers

| Feature | Gunicorn ASGI | Uvicorn | Hypercorn |
|---------|---------------|---------|-----------|
| Process management | Built-in | External | Built-in |
| HTTP/2 | Yes | No | Yes |
| WebSocket | Yes | Yes | Yes |
| Lifespan | Yes | Yes | Yes |
| uvloop support | Yes | Yes | Yes |

!!! note
    HTTP/2 requires SSL/TLS and the h2 library. See [HTTP/2 Support](guides/http2.md) for details.

Gunicorn's ASGI worker provides the same process management, logging, and
configuration capabilities you're familiar with from WSGI deployments.

## Troubleshooting

### Lifespan startup failed

If you see "ASGI lifespan startup failed", your application may not properly
implement the lifespan protocol. Either fix the application or set
`--asgi-lifespan off`.

### Connection limits

If you're hitting connection limits, increase `--worker-connections` or add
more workers with `--workers`.

### Slow responses under load

Try using uvloop for better performance:

```bash
pip install uvloop
gunicorn myapp:app --worker-class asgi --asgi-loop uvloop
```

## See Also

- [Settings Reference](reference/settings.md#asgi_loop) - All ASGI-related settings
- [Deploy](deploy.md) - General deployment guidance
- [Design](design.md) - Worker architecture overview
