# Stress and resilience suite

Drives real load at gunicorn with [k6](https://k6.io) and asserts the server
stays correct under it: no failed requests, intact bodies and checksums, the
negotiated protocol, and no worker tracebacks. Use it when a change touches the
workers, the ASGI/HTTP-2 paths, or process management and you need to know it
holds up under concurrency, not just on a single request.

Load runs as a pinned k6 container inside the compose network; network faults
run through a pinned [Toxiproxy](https://github.com/Shopify/toxiproxy). Nothing
is installed on the host and Grafana Cloud is not used. HTTP/2 and HPACK
conformance stay with the `h2spec` suite; k6 is a load driver, not a fuzzer.

## Run it

```sh
PYTEST=".venv/bin/python -m pytest" scripts/run_docker_tests.sh stress
```

This runs the smoke matrix only. The heavier resilience and Toxiproxy scenarios
are opt-in:

```sh
GUNICORN_STRESS_HEAVY=1 .venv/bin/python -m pytest tests/docker/stress -v
```

Requires a running Docker daemon. The first run builds the gunicorn and nginx
images and pulls `grafana/k6` and `ghcr.io/shopify/toxiproxy`; later runs reuse
them.

## What it covers

Smoke matrix (wired and verified):

| Config | Worker | Path | Protocol |
| --- | --- | --- | --- |
| `sync-direct-h1` | sync | direct | HTTP/1.1 |
| `gthread-nginx-h1` | gthread | behind nginx | HTTP/1.1 |
| `asgi-direct-h1` | asgi | direct | HTTP/1.1 |
| `asgi-nginx-h1` | asgi | behind nginx | HTTP/1.1 |
| `asgi-ws-nginx` | asgi | behind nginx | WebSocket |
| `h2-direct-tls` | asgi | direct | HTTP/2 (TLS) |

nginx terminates HTTP/2 and the uWSGI protocol downstream only; the gunicorn
upstream always sees HTTP/1.1 (proxy) or the uWSGI protocol (`uwsgi_pass`). The
`uwsgi_pass` topology targets the sync worker, gunicorn's supported uWSGI path;
the asgi worker's uWSGI parser is not exercised here.

Heavy scenarios (`GUNICORN_STRESS_HEAVY=1`): kill a worker, HUP reload, TTIN/TTOU
scaling, and Toxiproxy latency, bandwidth, and connection-reset faults, each
applied while load runs.

## Selecting worker, topology, protocol, and profile

Every combination is reachable by environment. The k6 scenario is chosen with
`SCENARIO` (`smoke`, `constant`, `ramping`, `spike`, `churn`, `soak`) and tuned
with `RATE`, `DURATION`, `VUS`, `MAXVUS`, `FAIL_BUDGET`, `MAX_P95`, `MAX_P99`.
Gunicorn services are shaped by the compose environment: `MAX_REQUESTS`,
`ASGI_LOOP` (`auto`/`asyncio`/`uvloop`), and `H2_WORKER` (which worker backs the
HTTP/2 service). For example, to run the asgi worker on uvloop with request
recycling:

```sh
ASGI_LOOP=uvloop MAX_REQUESTS=1000 docker compose -p gunicorn_stress \
  -f tests/docker/stress/docker-compose.yml up -d --build
```

## Ports

Fixed host ports (run one docker suite at a time; a collision answers from the
wrong stack):

| Port | Target |
| --- | --- |
| 8460 | sync, direct |
| 8461 | gthread, behind nginx |
| 8462 | asgi, direct |
| 8463 | asgi, behind nginx (HTTP + WebSocket) |
| 8464 | HTTP/2 (TLS) behind nginx |
| 8465 | asgi HTTP/2 (TLS), direct |
| 8466 | sync behind nginx `uwsgi_pass` |
| 8474 | Toxiproxy admin API |
| 8475 | Toxiproxy proxy |

## Resource expectations

The smoke matrix runs in a few minutes on a laptop. The nightly profiles
(`ramping`, `spike`, `soak`) and the heavy resilience/fault tests run longer and
push more concurrency; give them a host with a few spare cores and ~2 GB free.
The `soak` scenario defaults to 30 minutes (`DURATION` overrides it).

## Evidence

k6 writes a machine-readable summary per run to `_results/<config>-<scenario>.json`
(git-ignored) and prints error rate, check rate, p95/p99/max latency, and dropped
iterations. Container logs are available with
`docker compose -p gunicorn_stress logs <service>`.
