# ASGI baseline, 2026-11-08

The reference the ASGI performance work is measured against: master at `6a0a716a` (with the #3789, #3791, #3792 and #3805 fixes), compared with `5be13466` (before them), and with Uvicorn.

Machine: Apple M4 Pro, 14 cores, macOS 27.2; Python 3.14.9, uvloop 0.22.1, gunicorn_h1c 0.6.11, uvicorn 0.42.0, httptools 0.7.1, wrk 4.2.0. One worker, wrk 4 threads / 64 connections, 10 s measured after 3 s warm-up, 5 rounds, variant order alternating. Full tables: `master-vs-5be13466.md`; raw runs in the `.json` files.

## Throughput, small GET with keep-alive (req/s, median of 5)

Interleaved run (`master-vs-5be13466.json`), so every variant saw the same machine conditions:

| variant | master | 5be13466 | share of Uvicorn |
|---|---|---|---|
| gunicorn native, gunicorn_h1c | 41,258 | 40,656 | 64% |
| gunicorn native, Python parser | 36,169 | 36,709 | 56% |
| Uvicorn (httptools, uvloop) | 64,055 | | 100% |
| gunicorn + Uvicorn's worker | 59,475 | | 93% |

- The gap is in the native ASGI request path: the same gunicorn master with Uvicorn's worker is close to Uvicorn.
- master and 5be13466 are within noise of each other on every workload (the safety fixes cost nothing measurable); spreads are 2-5% for gunicorn, larger for a few Uvicorn rounds disturbed by the machine.
- Every server runs at 100% CPU and wrk uses under one of its four threads' worth of CPU, so these are CPU-bound per-request comparisons, not client-bound.
- Absolute numbers drift by about 15% between sessions on this machine; compare revisions in one interleaved run (`--baseline-root`), not across separate runs.

Other workloads, gunicorn native with gunicorn_h1c as a share of Uvicorn: percent-encoded target 71%, 30 extra headers 61%, 64 KiB upload 82%, chunked upload 69%, 1 MiB response 107%, streamed response 65%.

## Per-request cost in process (`profile-*.txt`)

`profile_requests.py`, one request at a time over an in-memory transport (includes the same driver overhead for every server, so compare, do not add up):

| request | gunicorn h1c | gunicorn Python | Uvicorn |
|---|---|---|---|
| small: µs / calls | 43.3 / 214 | 49.3 / 264 | 32.4 / 90 |
| percent-encoded target | 44.1 / 210 | 50.1 / 250 | 34.4 / 104 |
| 30 extra headers | 53.3 / 382 | 84.7 / 712 | 36.8 / 174 |

No memory is held from one batch to the next (a few KB over 2,000 requests).

## Where gunicorn spends it (`cprofile-master-6a0a716a.txt`, small GET, h1c)

- `Config.__getattr__`: 17 calls per request (85,000 over 5,000), each going through `Setting.get()`.
- `_peer_is_trusted_proxy`: parses the peer address with `ipaddress` on every request (about 12% of profiled time), from the forwarded-header policy added in #3789; the answer cannot change on a connection.
- `_RequestHeaderPolicy.apply`: about 18% cumulative, a separate pass over the headers.
- `CallbackRequest.from_parser`: several passes over the same headers (bytes copy, upper-case str copy, singleton check, `Expect`).
- `_send_response_start` and `_get_reason_phrase` (a dict rebuilt per call), `_validate_response_headers`, `_will_close` called twice.
- `Logger.access_log_enabled`: 5-6 settings read per request with the access log off.

These are the targets of the next PR, in that order, each checked against this baseline in an interleaved run.
