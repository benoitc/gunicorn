<span id="design"></span>
# Design

A brief look at Gunicorn's architecture.

## Server Model

Gunicorn uses a **pre-fork worker model**: an arbiter process manages worker
processes, while the workers handle requests and responses. The arbiter never
touches individual client sockets.

<div class="pillars" markdown>

<div class="pillar" markdown>
<div class="pillar__icon">⚖️</div>

### Arbiter

Orchestrates the worker pool. Listens for signals (`TTIN`, `TTOU`, `CHLD`,
`HUP`) to adjust workers, restart them on failure, or reload configuration.
</div>

<div class="pillar" markdown>
<div class="pillar__icon">⚙️</div>

### Worker Pool

Each worker handles requests independently. Worker types determine
concurrency model: sync, threaded, or async via greenlets/asyncio.
</div>

<div class="pillar" markdown>
<div class="pillar__icon">📡</div>

### Signal Communication

`TTIN`/`TTOU` adjust worker count. `CHLD` triggers restart of crashed
workers. `HUP` reloads configuration. See [Signals](signals.md).
</div>

</div>

## Worker Types

Choose a worker type based on your application's needs.

=== "Sync"

    The **default** worker. Handles one request at a time per worker.

    - Simple and predictable
    - Errors affect only the current request
    - No keep-alive support (connections close after response)
    - Requires a buffering proxy (nginx, HAProxy) for production

    ```bash
    gunicorn myapp:app
    ```

=== "Gthread"

    Threaded worker with a **thread pool** per worker process.

    - Supports keep-alive connections
    - Good balance of concurrency and simplicity
    - Threads share memory (lower footprint than workers)
    - Idle connections close after keepalive timeout

    ```bash
    gunicorn myapp:app -k gthread --threads 4
    ```

=== "ASGI"

    Native **asyncio** support for modern async frameworks.

    - For FastAPI, Starlette, Quart, and other ASGI apps
    - Full async/await support
    - See the [ASGI Guide](asgi.md) for details

    ```bash
    gunicorn myapp:app -k uvicorn.workers.UvicornWorker
    ```

=== "Gevent"

    **Greenlet-based** async worker using [Gevent](http://www.gevent.org/).

    - Handles thousands of concurrent connections
    - Supports keep-alive, WebSockets, long-polling
    - May require patches for some libraries (e.g., `psycogreen` for Psycopg)
    - Not compatible with code that relies on blocking behavior

    ```bash
    gunicorn myapp:app -k gevent --worker-connections 1000
    ```

=== "Eventlet (Deprecated)"

    !!! warning "Deprecated"
        The eventlet worker is **deprecated** and will be removed in Gunicorn 26.0.
        Eventlet itself is [no longer actively maintained](https://eventlet.readthedocs.io/en/latest/asyncio/migration.html).
        Please migrate to `gevent`, `gthread`, or another supported worker type.

    **Greenlet-based** async worker using [Eventlet](http://eventlet.net/).

    - Similar capabilities to Gevent
    - Handles high concurrency for I/O-bound apps
    - Some libraries may need compatibility patches

    ```bash
    gunicorn myapp:app -k eventlet --worker-connections 1000
    ```

=== "Tornado"

    Worker for [Tornado](https://www.tornadoweb.org/) applications.

    - Designed for Tornado's async framework
    - Can serve WSGI apps, but not recommended for that use case
    - Use when running native Tornado applications

    ```bash
    gunicorn myapp:app -k tornado
    ```

## Comparison

| Worker | Concurrency Model | Keep-Alive | Best For |
|--------|-------------------|------------|----------|
| `sync` | 1 request/worker | ❌ | CPU-bound apps behind a proxy |
| `gthread` | Thread pool | ✅ | Mixed workloads, moderate concurrency |
| ASGI workers | AsyncIO | ✅ | Modern async frameworks (FastAPI, etc.) |
| `gevent` | Greenlets | ✅ | I/O-bound, WebSockets, streaming |
| `eventlet` | Greenlets | ✅ | **Deprecated** - use `gevent` instead |
| `tornado` | Tornado IOLoop | ✅ | Native Tornado applications |

!!! tip "Quick Decision Guide"

    - **Simple app behind nginx?** → `sync` (default)
    - **Need keep-alive or moderate concurrency?** → `gthread`
    - **WebSockets, streaming, long-polling?** → `gevent` or ASGI worker
    - **FastAPI, Starlette, or async framework?** → ASGI worker

## When to Use Async Workers

Synchronous workers assume your app is CPU or network bound and avoids
indefinite blocking operations. Use async workers when you have:

- Long blocking calls (external APIs, slow databases)
- Direct internet traffic without a buffering proxy
- Streaming request/response bodies
- Long polling or Comet patterns
- WebSockets

!!! info "Testing Slow Clients"

    Tools like [Hey](https://github.com/rakyll/hey) can simulate slow responses
    to test how your configuration handles them.

## Scaling

### How Many Workers?

!!! warning "Don't Over-Scale"

    Workers ≠ clients. Gunicorn typically needs only **4–12 workers** to handle
    heavy traffic. Too many workers waste resources and can reduce throughput.

Start with this formula and adjust under load:

```
workers = (2 × CPU cores) + 1
```

Use `TTIN`/`TTOU` signals to adjust the worker count at runtime.

### How Many Threads?

With the `gthread` worker, you can combine workers and threads:

```bash
gunicorn myapp:app -k gthread --workers 4 --threads 2
```

!!! info "Threads vs Workers"

    - **Threads** share memory → lower footprint
    - **Workers** isolate failures → better fault tolerance
    - Combine both for the best of both worlds

Threads can extend request time beyond the worker timeout while still
notifying the arbiter. The optimal mix depends on your runtime (CPython vs
PyPy) and workload.

## Configuration Examples

```bash
# Sync (default) - simple apps behind nginx
gunicorn myapp:app

# Gthread - keep-alive and thread concurrency
gunicorn myapp:app -k gthread --workers 4 --threads 4

# Gevent - high concurrency for I/O-bound apps
gunicorn myapp:app -k gevent --workers 4 --worker-connections 1000

# ASGI - FastAPI/Starlette with Uvicorn worker
gunicorn myapp:app -k uvicorn.workers.UvicornWorker --workers 4
```

<span id="asyncio-workers"></span>

!!! note "Third-Party AsyncIO Workers"

    For asyncio frameworks, you can also use third-party workers. See the
    [aiohttp deployment guide](https://docs.aiohttp.org/en/stable/deployment.html#nginx-gunicorn)
    for examples.
