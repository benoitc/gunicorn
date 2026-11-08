# ASGI benchmarks

This harness measures gunicorn's native ASGI worker against Uvicorn on the same application, and profiles the Python cost of one request. Use it before and after any change to the ASGI request path, to tell a real gain from noise.

## Set up

```bash
.venv/bin/pip install -e . -r benchmarks/asgi/requirements.txt
brew install wrk        # or: apt install wrk
```

## Compare servers

```bash
.venv/bin/python benchmarks/asgi/run.py --label master
.venv/bin/python benchmarks/asgi/report.py benchmarks/asgi/results/master.json
```

`run.py` starts four variants serving `apps.py` with the same Python, uvloop, worker count (1 by default), keep-alive and no access log:

| variant | what it is |
|---|---|
| `gunicorn-fast` | native ASGI worker, gunicorn_h1c parser |
| `gunicorn-python` | native ASGI worker, pure-Python parser |
| `uvicorn` | Uvicorn, httptools, uvloop |
| `gunicorn-uvicorn-worker` | gunicorn running Uvicorn's worker (control: same master process, Uvicorn's request path) |

Each round runs every variant, in alternating order between rounds. Each run is warmed up, then measured with wrk for `--duration` seconds. The result file holds every run: req/s, p50/p95/p99, errors by kind, server CPU, client CPU and peak RSS, plus the commit, dependency versions, machine and exact commands.

Pick workloads and rounds:

```bash
.venv/bin/python benchmarks/asgi/run.py --workloads small_keepalive many_headers --rounds 9
```

## Compare revisions

```bash
git worktree add /tmp/gunicorn-old <commit>
.venv/bin/python benchmarks/asgi/run.py --gunicorn-root /tmp/gunicorn-old --label old
.venv/bin/python benchmarks/asgi/run.py --label new
.venv/bin/python benchmarks/asgi/report.py benchmarks/asgi/results/old.json benchmarks/asgi/results/new.json
```

`--gunicorn-root` makes the servers import that tree even with an editable install of another one; the result file records where gunicorn was imported from.

## Profile one request

```bash
.venv/bin/python benchmarks/asgi/profile_requests.py
.venv/bin/python benchmarks/asgi/profile_requests.py --request many_headers --top 25
```

This drives gunicorn's real ASGI protocol and Uvicorn's httptools protocol in process, one request at a time, over an in-memory transport. It prints, from separate passes: microseconds per request, Python and C calls per request, memory still held after a batch (a leak check) and peak traced memory, and with `--top` the cProfile functions with the most own time. Use it to see where a change saves work; use `run.py` to see whether it shows up under load.

## Workloads

| workload | checks |
|---|---|
| `small_keepalive` | fixed per-request cost (the main comparison) |
| `small_close` | connection setup and teardown |
| `pct_target` | percent-encoded request target |
| `many_headers` | 30 extra request headers |
| `post_upload` | 64 KiB request body |
| `chunked_upload` | chunked request body |
| `large_response` | 1 MiB response |
| `stream_response` | 16 chunks without Content-Length |

TLS, h2c, HTTP/2, WebSocket, uWSGI, slow clients and disconnects are covered for correctness by the Docker suites in `tests/docker`, not here.

## Notes

- Start with one worker: it shows the per-request cost. Use more only while the client is not the limit; the report shows wrk's CPU next to the server's.
- `small_close` is left out by default on macOS: opening a connection per request at full speed runs out of local ports there (TIME_WAIT lasts 30 s), which measures the client. Run it on Linux, or ask for it with `--workloads` after lowering `net.inet.tcp.msl`.
- A run with connect errors measured fewer connections than asked; rerun it after a minute.
- Never derive a per-request cost from `1 / req/s` under concurrency; use `profile_requests.py`.
