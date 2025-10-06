<span id="design"></span>
# Design

A brief look at Gunicorn's architecture.

## Server model

Gunicorn uses a pre-fork worker model: a master process manages worker
processes, while the workers handle requests and responses. The master never
touches individual client sockets.

### Master

The master process listens for signals (TTIN, TTOU, CHLD, etc.) and adjusts the
worker pool accordingly. `TTIN`/`TTOU` change the number of workers; `CHLD`
indicates a worker exited and must be restarted.

### Sync workers

The default `sync` worker handles one request at a time. Errors affect only the
current request. Because connections close after each response, persistent
connections are not supported even if you set `Keep-Alive` headers manually.

### Async workers

Async workers are powered by [greenlets](https://github.com/python-greenlet/greenlet)
through [Eventlet](http://eventlet.net/) or [Gevent](http://www.gevent.org/).
Most apps work without modification, though full compatibility may require
patches (for example installing [`psycogreen`](https://github.com/psycopg/psycogreen/)
when using [Psycopg](http://initd.org/psycopg/)). Some apps that depend on the
original blocking behaviour may not be compatible.

### Gthread workers

`gthread` is a threaded worker. The main loop accepts connections and places
them in a thread pool. Keep-alive connections return to the pool to await
further events; idle connections close after the keepalive timeout.

### Tornado workers

A Tornado worker class exists for Tornado-based applications. While it can
serve WSGI apps, this configuration is not recommended.

<span id="asyncio-workers"></span>
### AsyncIO workers

Use third-party workers to pair Gunicorn with asyncio frameworks (see the
[aiohttp deployment guide](https://docs.aiohttp.org/en/stable/deployment.html#nginx-gunicorn)
or the [Flask aiohttp example](https://github.com/benoitc/gunicorn/blob/master/examples/frameworks/flaskapp_aiohttp_wsgi.py)).

## Choosing a worker type

Synchronous workers assume your app is CPU/network bound and avoids indefinite
operations. Any outbound HTTP calls or other blocking behaviour benefit from an
async worker. Because synchronous workers are vulnerable to slow clients,
Gunicorn requires a buffering proxy in front of the default configuration. Tools
like [Hey](https://github.com/rakyll/hey) can simulate slow responses to test
this scenario.

Examples that need async workers:

- Long blocking calls (outbound web services)
- Direct internet traffic (no buffering proxy)
- Streaming request/response bodies
- Long polling
- WebSockets / Comet

## How many workers?

Do **not** scale workers to match client count. Gunicorn usually needs only 4–12
workers to handle heavy traffic. Start with `(2 * num_cores) + 1` and adjust
under load using `TTIN`/`TTOU`.

Too many workers waste resources and can reduce throughput.

## How many threads?

Since Gunicorn 19 you can set `--threads` (with the `gthread` worker) to process
requests concurrently. Threads can extend request time beyond the worker
timeout while still notifying the master. The optimal mix of threads and worker
processes depends on the runtime (for example CPython vs. Jython). Threads share
memory, lowering footprint, and still allow reloads because application code is
loaded in worker processes.
