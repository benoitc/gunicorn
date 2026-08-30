# Docker integration tests

End-to-end suites that run gunicorn in containers, some behind nginx. Use these
when a change touches process management, protocol behavior on the wire, or
anything that only shows up with a real client and a real proxy in front.

## Running them

```sh
PYTEST=".venv/bin/python -m pytest" scripts/run_docker_tests.sh
```

One suite at a time:

```sh
PYTEST=".venv/bin/python -m pytest" scripts/run_docker_tests.sh uwsgi http2
```

Requires a running Docker daemon. The first run builds images and is slow;
later runs reuse them.

## Do not run them with a single pytest invocation

`pytest tests/docker` looks like it should work and does not. Every suite ships
its own `docker-compose.yml` and binds fixed host ports, so running them
together means each suite's requests can reach another suite's containers. The
result is failures that have nothing to do with the code: assertion errors from
valid responses served by the wrong application, not connection errors.

`tests/docker` is listed in `norecursedirs` in `pyproject.toml`, so a plain
`pytest tests/` skips these entirely and reports success without running any of
them. That is deliberate, but worth knowing before you conclude the suite is
green.

Use `scripts/run_docker_tests.sh`, which runs each suite on its own and tears
its stack down before starting the next.

## Ports

The suites bind fixed host ports. Anything else already listening on one of them
will silently answer the tests instead of the container. `mkdocs serve` defaults
to 8000 and collides with `asgi_compliance`.

| Suite | Host ports |
| --- | --- |
| `asgi_compliance` | 8000, 8080, 8443, 8444, 8445 |
| `asgi_framework_compat` | 8001 to 8006 |
| `http2` | 8443, 8444 |
| `h2spec` | 8451, 8452, 8453 |
| `uwsgi` | 8080 |

If a suite fails everywhere at once, check for a port collision before looking
at the code:

```sh
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

## Suites

| Directory | Covers |
| --- | --- |
| `asgi_compliance` | ASGI HTTP, websocket, lifespan and streaming behavior |
| `asgi_framework_compat` | Django, FastAPI, Starlette, Quart, Litestar, BlackSheep |
| `dirty_arbiter` | dirty arbiter lifecycle, parent death, respawn |
| `dirty_ttin_ttou` | scaling dirty workers with TTIN/TTOU |
| `http2` | HTTP/2 over TLS, direct and behind nginx |
| `per_app_allocation` | per-app worker allocation end to end |
| `uwsgi` | uWSGI binary protocol behind nginx |

`asgi/` and `test_asgi_uwsgi/` are shell-driven demos (`test_asgi.sh`,
`test_uwsgi.sh`), not pytest suites, and the runner skips them.

## CI

`.github/workflows/docker-integration.yml` runs `tests/docker/uwsgi/` only. The
other suites are not gated, so run them locally before changing the areas they
cover.

## Certificates

`asgi_compliance` and `http2` generate self-signed certificates into their
`certs/` directories, regenerating them once a day. They will show as modified
in `git status` after a run. Do not commit them.
