# ASGI request overhead, 2026-11-08

What the three commits of the overhead work changed, measured with this harness against the baseline in `BASELINE.md`. Same machine and settings: one worker, wrk 4 threads / 64 connections, interleaved rounds (`--baseline-root`). The machine was partly busy during these runs, so a few rounds collapsed; medians are used and the spread is shown in the full tables.

## Whole branch against master (`head-vs-master.md`, 5 rounds)

| workload | gunicorn_h1c | Python parser | gunicorn_h1c share of Uvicorn |
|---|---|---|---|
| small GET | 42,054 -> 51,955 (+23.5%) | 36,599 -> 46,743 (+27.7%) | 69% -> 86% |
| percent-encoded target | +36.0% | +29.4% | 71% -> 96% |
| 30 extra headers | +24.1% | +11.8% | 57% -> 71% |
| 64 KiB upload | +18.7% | +17.4% | 81% -> 96% |
| chunked upload | +22.8% | +17.1% | 66% -> 81% |
| streamed response | +9.9% | +13.2% | 61% -> 67% |

The 1 MiB response run was too noisy to read (spreads over 30%).

## Per commit, interleaved against the commit before (7 rounds)

| commit | workload | gunicorn_h1c | Python parser | file |
|---|---|---|---|---|
| settings once per connection | small GET | +26.5% | +19.9% | `step1-vs-master.json` |
| one pass over request headers | 30 extra headers | +5.9% | +1.2% | `step2-vs-step1-many-headers.json` |
| fewer response passes | small GET | +5.7% | +6.7% | `step3-vs-step2.json` |

Most of the gain is the first commit: the peer address was parsed with `ipaddress` on every request and 17 settings were resolved through `Config.__getattr__`. The other two are close to the run-to-run spread; they are kept because they remove work the profile shows and change no output (byte-identical responses and identical request fields, both tested).

## In process (`profile_requests.py`, small GET, gunicorn_h1c)

Calls per request: 214 (master) -> 147 -> 141 -> 137. Config reads per request: 17 -> 0.
