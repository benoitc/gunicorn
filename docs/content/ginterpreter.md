# Interpreter Worker

!!! warning "Experimental"
    The `ginterpreter` worker is experimental and requires Python 3.14+. The API
    and behavior may change in future releases.

The interpreter worker uses Python's `InterpreterPoolExecutor` to handle each
request in a separate sub-interpreter. Each sub-interpreter runs in its own
thread with an independent GIL, enabling true CPU parallelism without multiple
processes.

## Quick Start

```bash
gunicorn myapp:app --worker-class ginterpreter --threads 4
```

Or in a configuration file:

```python
# gunicorn.conf.py
worker_class = "ginterpreter"
threads = 4
```

## Configuration

The interpreter worker uses the standard gunicorn settings. The most relevant ones:

| Setting | Default | Description |
|---------|---------|-------------|
| `threads` | `1` | Number of sub-interpreters (i.e. concurrent requests per worker) |
| `workers` | `1` | Number of worker processes |
| `timeout` | `30` | Request timeout in seconds |
| `graceful_timeout` | `30` | Time to wait for in-flight requests on shutdown |

## Known Limitations

The following features are **not supported**:

- **`ssl_context` hook** — SSL contexts cannot be shared across sub-interpreters. Built-in SSL via `certfile`/`keyfile` works normally.
- **`pre_request` / `post_request` hooks** — Callables cannot be passed to sub-interpreters.
- **Keepalive connections** — Each connection is closed after the response.
- **HTTP/2**
- **Sendfile**
- **`max_requests` / `max_requests_jitter`**

## See Also

- [Settings Reference](reference/settings.md) - All available settings
- [Design](design.md) - Worker architecture overview
