<span id="news"></span>
# Changelog

## 25.1.0 - 2026-02-12

### New Features

- **Dirty Stash**: Add global shared state between workers via `dirty.stash`
  ([PR #3503](https://github.com/benoitc/gunicorn/pull/3503))
  - In-memory key-value store accessible by all workers
  - Supports get, set, delete, clear, keys, and has operations
  - Useful for sharing state like feature flags, rate limits, or cached data

- **Dirty Binary Protocol**: Implement efficient binary protocol for dirty arbiter IPC
  using TLV (Type-Length-Value) encoding
  ([PR #3500](https://github.com/benoitc/gunicorn/pull/3500))
  - More efficient than JSON for binary data
  - Supports all Python types: str, bytes, int, float, bool, None, list, dict
  - Better performance for large payloads

### Changes

- **ASGI Worker**: Promoted from beta to stable
- **Dirty Arbiters**: Now marked as beta feature

### Documentation

- Fix Markdown formatting in /configure documentation

---

## 25.0.3 - 2026-02-07

### Bug Fixes

- Fix RuntimeError when StopIteration is raised inside ASGI response body
  coroutine (PEP 479 compliance)

- Fix deprecation warning for passing maxsplit as positional argument in
  `re.split()` (Python 3.13+)

---

## 25.0.2 - 2026-02-06

### Bug Fixes

- Fix ASGI concurrent request failures through nginx proxy by normalizing
  sockaddr tuples to handle both 2-tuple (IPv4) and 4-tuple (IPv6) formats
  ([PR #3485](https://github.com/benoitc/gunicorn/pull/3485))

- Fix graceful disconnect handling for ASGI worker to properly handle
  client disconnects without raising exceptions
  ([PR #3485](https://github.com/benoitc/gunicorn/pull/3485))

- Fix lazy import of dirty module for gevent compatibility - prevents
  import errors when concurrent.futures is imported before gevent monkey-patching
  ([PR #3483](https://github.com/benoitc/gunicorn/pull/3483))

### Changes

- Refactor: Extract `_normalize_sockaddr` utility function for consistent
  socket address handling across workers

- Add license headers to all Python source files

- Update copyright year to 2026 in LICENSE and NOTICE files

---

## 25.0.1 - 2026-02-02

### Bug Fixes

- Fix ASGI streaming responses (SSE) hanging: add chunked transfer encoding for
  HTTP/1.1 responses without Content-Length header. Without chunked encoding,
  clients wait for connection close to determine end-of-response.

### Changes

- Update celery_alternative example to use FastAPI with native ASGI worker and
  uvloop for async task execution

### Testing

- Add ASGI compliance test suite with Docker-based integration tests covering HTTP,
  WebSocket, streaming, lifespan, framework integration (Starlette, FastAPI),
  HTTP/2, and concurrency scenarios

---

## 25.0.0 - 2026-02-01

### New Features

- **Dirty Arbiters**: Separate process pool for executing long-running, blocking
  operations (AI model loading, heavy computation) without blocking HTTP workers
  ([PR #3460](https://github.com/benoitc/gunicorn/pull/3460))
  - Inspired by Erlang's dirty schedulers
  - Asyncio-based with Unix socket IPC
  - Stateful workers that persist loaded resources
  - New settings: `--dirty-app`, `--dirty-workers`, `--dirty-timeout`,
    `--dirty-threads`, `--dirty-graceful-timeout`
  - Lifecycle hooks: `on_dirty_starting`, `dirty_post_fork`,
    `dirty_worker_init`, `dirty_worker_exit`

- **Per-App Worker Allocation for Dirty Arbiters**: Control how many dirty workers
  load each app for memory optimization with heavy models
  ([PR #3473](https://github.com/benoitc/gunicorn/pull/3473))
  - Set `workers` class attribute on DirtyApp (e.g., `workers = 2`)
  - Or use config format `module:class:N` (e.g., `myapp:HeavyModel:2`)
  - Requests automatically routed to workers with the target app
  - New exception `DirtyNoWorkersAvailableError` for graceful error handling
  - Example: 8 workers × 10GB model = 80GB → with `workers=2`: 20GB (75% savings)

- **HTTP/2 Support (Beta)**: Native HTTP/2 (RFC 7540) support for improved performance
  with modern clients ([PR #3468](https://github.com/benoitc/gunicorn/pull/3468))
  - Multiplexed streams over a single connection
  - Header compression (HPACK)
  - Flow control and stream prioritization
  - Works with gthread, gevent, and ASGI workers
  - New settings: `--http-protocols`, `--http2-max-concurrent-streams`,
    `--http2-initial-window-size`, `--http2-max-frame-size`, `--http2-max-header-list-size`
  - Requires SSL/TLS and h2 library: `pip install gunicorn[http2]`
  - See [HTTP/2 Guide](guides/http2.md) for details
  - New example: `examples/http2_gevent/` with Docker and tests

- **HTTP 103 Early Hints**: Support for RFC 8297 Early Hints to enable browsers to
  preload resources before the final response
  ([PR #3468](https://github.com/benoitc/gunicorn/pull/3468))
  - WSGI: `environ['wsgi.early_hints'](headers)` callback
  - ASGI: `http.response.informational` message type
  - Works with both HTTP/1.1 and HTTP/2

- **uWSGI Protocol for ASGI Worker**: The ASGI worker now supports receiving requests
  via the uWSGI binary protocol from nginx
  ([PR #3467](https://github.com/benoitc/gunicorn/pull/3467))

### Bug Fixes

- Fix HTTP/2 ALPN negotiation for gevent and eventlet workers when
  `do_handshake_on_connect` is False (the default). The TLS handshake is now
  explicitly performed before checking `selected_alpn_protocol()`.

- Fix setproctitle initialization with systemd socket activation
  ([#3465](https://github.com/benoitc/gunicorn/issues/3465))

- Fix `Expect: 100-continue` handling: ignore the header for HTTP/1.0 requests
  since 100-continue is only valid for HTTP/1.1+
  ([PR #3463](https://github.com/benoitc/gunicorn/pull/3463))

- Fix missing `_expected_100_continue` attribute in UWSGIRequest

- Disable setproctitle on macOS to prevent segfaults during process title updates

- Publish full exception traceback when the application fails to load
  ([#3462](https://github.com/benoitc/gunicorn/issues/3462))

- Fix ASGI: quick shutdown on SIGINT/SIGQUIT, graceful on SIGTERM

### Deprecations

- **Eventlet Worker**: The `eventlet` worker is deprecated and will be removed in
  Gunicorn 26.0. Eventlet itself is [no longer actively maintained](https://eventlet.readthedocs.io/en/latest/asyncio/migration.html).
  Please migrate to `gevent`, `gthread`, or another supported worker type.

### Changes

- Remove obsolete Makefile targets
  ([PR #3471](https://github.com/benoitc/gunicorn/pull/3471))

---

## 24.1.1 - 2026-01-24

### Bug Fixes

- Fix `forwarded_allow_ips` and `proxy_allow_ips` to remain as strings for backward
  compatibility with external tools like uvicorn. Network validation now uses strict
  mode to detect invalid CIDR notation (e.g., `192.168.1.1/24` where host bits are set)
  ([#3458](https://github.com/benoitc/gunicorn/issues/3458),
  [PR #3459](https://github.com/benoitc/gunicorn/pull/3459))

---

## 24.1.0 - 2026-01-23

### New Features

- **Official Docker Image**: Gunicorn now publishes official Docker images to GitHub
  Container Registry at `ghcr.io/benoitc/gunicorn`
  - Based on Python 3.12 slim image
  - Uses recommended worker formula (2 × CPU + 1)
  - Configurable via environment variables

- **PROXY Protocol v2 Support**: Extended PROXY protocol implementation to support
  the binary v2 format in addition to the existing text-based v1 format
  - New `--proxy-protocol` modes: `off`, `v1`, `v2`, `auto`
  - Works with HAProxy, AWS NLB/ALB, and other PROXY protocol v2 sources

- **CIDR Network Support**: `--forwarded-allow-ips` and `--proxy-allow-from` now
  accept CIDR notation (e.g., `192.168.0.0/16`) for specifying trusted networks

- **Socket Backlog Metric**: New `gunicorn.socket.backlog` gauge metric reports
  the current socket backlog size on Linux systems

- **InotifyReloader Enhancement**: The inotify-based reloader now watches newly
  imported modules, not just those loaded at startup

### Bug Fixes

- Fix signal handling regression where SIGCLD alias caused errors on Linux
- Fix socket blocking mode on keepalive connections with async workers
- Handle `SSLWantReadError` in `finish_body()` to prevent worker hangs
- Log SIGTERM as info level instead of warning
- Print exception details to stderr when worker fails to boot
- Fix `unreader.unread()` to prepend data to buffer instead of appending
- Prevent `RecursionError` when pickling Config objects

---

## 24.0.0 - 2026-01-23

### New Features

- **ASGI Worker (Beta)**: Native asyncio-based ASGI support for running async Python
  frameworks like FastAPI, Starlette, and Quart without external dependencies
  - HTTP/1.1 with keepalive connections
  - WebSocket support
  - Lifespan protocol for startup/shutdown hooks
  - Optional uvloop for improved performance

- **uWSGI Binary Protocol**: Support for receiving requests from nginx via
  `uwsgi_pass` directive

- **Documentation Migration**: Migrated to MkDocs with Material theme

### Security

- **eventlet**: Require eventlet >= 0.40.3 (CVE-2021-21419, CVE-2025-58068)
- **gevent**: Require gevent >= 24.10.1 (CVE-2023-41419, CVE-2024-3219)
- **tornado**: Require tornado >= 6.5.0 (CVE-2025-47287)

---

## 23.0.0 - 2024-08-10

- minor docs fixes ([PR #3217](https://github.com/benoitc/gunicorn/pull/3217), [PR #3089](https://github.com/benoitc/gunicorn/pull/3089), [PR #3167](https://github.com/benoitc/gunicorn/pull/3167))
- worker_class parameter accepts a class ([PR #3079](https://github.com/benoitc/gunicorn/pull/3079))
- fix deadlock if request terminated during chunked parsing ([PR #2688](https://github.com/benoitc/gunicorn/pull/2688))
- permit receiving Transfer-Encodings: compress, deflate, gzip ([PR #3261](https://github.com/benoitc/gunicorn/pull/3261))
- permit Transfer-Encoding headers specifying multiple encodings. note: no parameters, still ([PR #3261](https://github.com/benoitc/gunicorn/pull/3261))
- sdist generation now explicitly excludes sphinx build folder ([PR #3257](https://github.com/benoitc/gunicorn/pull/3257))
- decode bytes-typed status (as can be passed by gevent) as utf-8 instead of raising `TypeError` ([PR #2336](https://github.com/benoitc/gunicorn/pull/2336))
- raise correct Exception when encounting invalid chunked requests ([PR #3258](https://github.com/benoitc/gunicorn/pull/3258))
- the SCRIPT_NAME and PATH_INFO headers, when received from allowed forwarders, are no longer restricted for containing an underscore ([PR #3192](https://github.com/benoitc/gunicorn/pull/3192))
- include IPv6 loopback address ``[::1]`` in default for [forwarded-allow-ips](reference/settings.md#forwarded_allow_ips) and [proxy-allow-ips](reference/settings.md#proxy_allow_ips) ([PR #3192](https://github.com/benoitc/gunicorn/pull/3192))

!!! note
    - The SCRIPT_NAME change mitigates a regression that appeared first in the 22.0.0 release
    - Review your [forwarded-allow-ips](reference/settings.md#forwarded_allow_ips) setting if you are still not seeing the SCRIPT_NAME transmitted
    - Review your [forwarder-headers](reference/settings.md#forwarder_headers) setting if you are missing headers after upgrading from a version prior to 22.0.0


### Breaking changes

- refuse requests where the uri field is empty ([PR #3255](https://github.com/benoitc/gunicorn/pull/3255))
- refuse requests with invalid CR/LR/NUL in heade field values ([PR #3253](https://github.com/benoitc/gunicorn/pull/3253))
- remove temporary ``--tolerate-dangerous-framing`` switch from 22.0 ([PR #3260](https://github.com/benoitc/gunicorn/pull/3260))
- If any of the breaking changes affect you, be aware that now refused requests can post a security problem, especially so in setups involving request pipe-lining and/or proxies.

## 22.0.0 - 2024-04-17

- use `utime` to notify workers liveness
- migrate setup to pyproject.toml
- fix numerous security vulnerabilities in HTTP parser (closing some request smuggling vectors)
- parsing additional requests is no longer attempted past unsupported request framing
- on HTTP versions < 1.1 support for chunked transfer is refused (only used in exploits)
- requests conflicting configured or passed SCRIPT_NAME now produce a verbose error
- Trailer fields are no longer inspected for headers indicating secure scheme
- support Python 3.12

### Breaking changes

- minimum version is Python 3.7
- the limitations on valid characters in the HTTP method have been bounded to Internet Standards
- requests specifying unsupported transfer coding (order.md) are refused by default (rare.md)
- HTTP methods are no longer casefolded by default (IANA method registry contains none affected)
- HTTP methods containing the number sign (#) are no longer accepted by default (rare.md)
- HTTP versions < 1.0 or >= 2.0 are no longer accepted by default (rare, only HTTP/1.1 is supported)
- HTTP versions consisting of multiple digits or containing a prefix/suffix are no longer accepted
- HTTP header field names Gunicorn cannot safely map to variables are silently dropped, as in other software
- HTTP headers with empty field name are refused by default (no legitimate use cases, used in exploits)
- requests with both Transfer-Encoding and Content-Length are refused by default (such a message might indicate an attempt to perform request smuggling)
- empty transfer codings are no longer permitted (reportedly seen with really old & broken proxies)


### Security

- fix CVE-2024-1135

## History

- [2026](2026-news.md)
- [2024](2024-news.md)
- [2023](2023-news.md)
- [2021](2021-news.md)
- [2020](2020-news.md)
- [2019](2019-news.md)
- [2018](2018-news.md)
- [2017](2017-news.md)
- [2016](2016-news.md)
- [2015](2015-news.md)
- [2014](2014-news.md)
- [2013](2013-news.md)
- [2012](2012-news.md)
- [2011](2011-news.md)
- [2010](2010-news.md)
