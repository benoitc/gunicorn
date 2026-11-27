# ASGI benchmark: head-vs-master

- commit: `7f5a3e697300b844c18d68f41de59524700df200`
- date: 2026-11-08T18:56:17+00:00
- machine: Apple M4 Pro, 14 CPUs, macOS-27.2-arm64-arm-64bit-Mach-O
- Python 3.14.9; gunicorn 26.2.2, gunicorn_h1c 0.6.11, uvicorn 0.42.0, httptools 0.7.1, uvloop 0.22.1, wrk wrk 4.2.0 [kqueue] Copyright (C) 2012 Will Glozer
- 1 worker(s); wrk -t4 -c64; 10s measured after 3s warm-up; 5 rounds, variant order alternating
- commands:
  - gunicorn-fast: `python <repo>/benchmarks/asgi/_launch.py <repo> gunicorn -k asgi --http-parser fast --asgi-loop uvloop -w 1 --keep-alive 5 -b 127.0.0.1:PORT apps:app`
  - gunicorn-fast@baseline: `python <repo>/benchmarks/asgi/_launch.py <worktree baseperf> gunicorn -k asgi --http-parser fast --asgi-loop uvloop -w 1 --keep-alive 5 -b 127.0.0.1:PORT apps:app`
  - gunicorn-python: `python <repo>/benchmarks/asgi/_launch.py <repo> gunicorn -k asgi --http-parser python --asgi-loop uvloop -w 1 --keep-alive 5 -b 127.0.0.1:PORT apps:app`
  - gunicorn-python@baseline: `python <repo>/benchmarks/asgi/_launch.py <worktree baseperf> gunicorn -k asgi --http-parser python --asgi-loop uvloop -w 1 --keep-alive 5 -b 127.0.0.1:PORT apps:app`
  - uvicorn: `python <repo>/benchmarks/asgi/_launch.py <repo> uvicorn apps:app --http httptools --loop uvloop --workers 1 --timeout-keep-alive 5 --no-access-log --host 127.0.0.1 --port PORT`

## small_keepalive

| variant | req/s median | min-max | spread | vs uvicorn | vs baseline | p50 ms | p95 ms | p99 ms | errors | server CPU % | client CPU % | peak RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gunicorn-fast | 51955 | 50423-58539 | 15.6% | 86% | +23.5% | 1.36 | 1.62 | 1.75 | 0 | 100 | 77 | 62 |
| gunicorn-python | 46743 | 46016-49742 | 8.0% | 77% | +27.7% | 1.50 | 1.81 | 1.96 | 0 | 100 | 63 | 61 |
| uvicorn | 60671 | 53367-67873 | 23.9% | 100% | - | 1.17 | 1.39 | 1.58 | 0 | 99 | 89 | 39 |
| gunicorn-fast@baseline | 42054 | 36915-42809 | 14.0% | 69% | - | 1.56 | 1.98 | 2.21 | 0 | 99 | 62 | 62 |
| gunicorn-python@baseline | 36599 | 29555-37107 | 20.6% | 60% | - | 1.72 | 2.15 | 2.43 | 0 | 99 | 54 | 61 |

## pct_target

| variant | req/s median | min-max | spread | vs uvicorn | vs baseline | p50 ms | p95 ms | p99 ms | errors | server CPU % | client CPU % | peak RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gunicorn-fast | 52692 | 49106-56499 | 14.0% | 96% | +36.0% | 1.34 | 1.62 | 1.76 | 0 | 100 | 72 | 63 |
| gunicorn-python | 45713 | 44646-46618 | 4.3% | 84% | +29.4% | 1.52 | 1.84 | 1.97 | 0 | 100 | 62 | 62 |
| uvicorn | 54653 | 48667-62213 | 24.8% | 100% | - | 1.30 | 1.57 | 1.72 | 0 | 100 | 80 | 40 |
| gunicorn-fast@baseline | 38747 | 37597-41633 | 10.4% | 71% | - | 1.71 | 2.12 | 2.65 | 0 | 99 | 59 | 63 |
| gunicorn-python@baseline | 35330 | 33114-36755 | 10.3% | 65% | - | 1.80 | 2.22 | 2.46 | 0 | 100 | 54 | 62 |

## many_headers

| variant | req/s median | min-max | spread | vs uvicorn | vs baseline | p50 ms | p95 ms | p99 ms | errors | server CPU % | client CPU % | peak RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gunicorn-fast | 31925 | 30871-33507 | 8.3% | 71% | +24.1% | 2.02 | 2.56 | 2.77 | 0 | 100 | 49 | 67 |
| gunicorn-python | 17021 | 16712-17256 | 3.2% | 38% | +11.8% | 3.75 | 4.10 | 4.31 | 0 | 100 | 26 | 64 |
| uvicorn | 45079 | 41678-47751 | 13.5% | 100% | - | 1.60 | 1.88 | 2.06 | 0 | 100 | 68 | 40 |
| gunicorn-fast@baseline | 25723 | 19792-27201 | 28.8% | 57% | - | 2.42 | 2.89 | 3.47 | 0 | 100 | 41 | 67 |
| gunicorn-python@baseline | 15223 | 14273-15286 | 6.7% | 34% | - | 4.49 | 5.37 | 5.79 | 0 | 100 | 23 | 65 |

## post_upload

| variant | req/s median | min-max | spread | vs uvicorn | vs baseline | p50 ms | p95 ms | p99 ms | errors | server CPU % | client CPU % | peak RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gunicorn-fast | 33074 | 31389-35855 | 13.5% | 96% | +18.7% | 1.95 | 2.30 | 2.56 | 0 | 99 | 116 | 99 |
| gunicorn-python | 29521 | 27982-30761 | 9.4% | 86% | +17.4% | 2.19 | 2.47 | 2.63 | 0 | 100 | 102 | 76 |
| uvicorn | 34349 | 32699-38282 | 16.3% | 100% | - | 1.88 | 2.21 | 2.34 | 0 | 99 | 126 | 56 |
| gunicorn-fast@baseline | 27852 | 11348-29746 | 66.1% | 81% | - | 2.28 | 2.70 | 2.92 | 0 | 99 | 100 | 92 |
| gunicorn-python@baseline | 25148 | 22066-26173 | 16.3% | 73% | - | 2.58 | 2.91 | 3.12 | 0 | 100 | 88 | 73 |

## chunked_upload

| variant | req/s median | min-max | spread | vs uvicorn | vs baseline | p50 ms | p95 ms | p99 ms | errors | server CPU % | client CPU % | peak RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gunicorn-fast | 38290 | 37191-40090 | 7.6% | 81% | +22.8% | 1.69 | 2.11 | 2.28 | 0 | 100 | 61 | 94 |
| gunicorn-python | 27856 | 26318-28488 | 7.8% | 59% | +17.1% | 2.27 | 2.58 | 2.82 | 0 | 100 | 44 | 77 |
| uvicorn | 47006 | 46055-50421 | 9.3% | 100% | - | 1.53 | 1.80 | 1.95 | 0 | 100 | 71 | 56 |
| gunicorn-fast@baseline | 31178 | 14123-32363 | 58.5% | 66% | - | 2.02 | 2.36 | 2.58 | 0 | 99 | 54 | 94 |
| gunicorn-python@baseline | 23784 | 22010-24344 | 9.8% | 51% | - | 2.65 | 2.96 | 3.14 | 0 | 100 | 39 | 74 |

## large_response

| variant | req/s median | min-max | spread | vs uvicorn | vs baseline | p50 ms | p95 ms | p99 ms | errors | server CPU % | client CPU % | peak RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gunicorn-fast | 5901 | 5550-7695 | 36.4% | 83% | +18.9% | 10.15 | 14.60 | 23.92 | 0 | 99 | 79 | 142 |
| gunicorn-python | 6500 | 5635-7664 | 31.2% | 91% | +4.3% | 9.07 | 13.79 | 24.96 | 0 | 99 | 79 | 123 |
| uvicorn | 7104 | 6320-8740 | 34.1% | 100% | - | 8.57 | 12.01 | 17.37 | 0 | 99 | 91 | 56 |
| gunicorn-fast@baseline | 4964 | 3460-6416 | 59.5% | 70% | - | 12.90 | 16.45 | 26.27 | 0 | 99 | 74 | 156 |
| gunicorn-python@baseline | 6231 | 4487-7172 | 43.1% | 88% | - | 9.95 | 13.01 | 23.08 | 0 | 100 | 77 | 120 |

## stream_response

| variant | req/s median | min-max | spread | vs uvicorn | vs baseline | p50 ms | p95 ms | p99 ms | errors | server CPU % | client CPU % | peak RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gunicorn-fast | 21200 | 20163-24591 | 20.9% | 67% | +9.9% | 3.29 | 3.95 | 4.24 | 0 | 99 | 58 | 143 |
| gunicorn-python | 21371 | 19697-22987 | 15.4% | 68% | +13.2% | 3.39 | 3.98 | 4.30 | 0 | 100 | 54 | 121 |
| uvicorn | 31517 | 30407-37076 | 21.2% | 100% | - | 1.99 | 2.39 | 3.99 | 0 | 100 | 50 | 56 |
| gunicorn-fast@baseline | 19293 | 9547-20518 | 56.9% | 61% | - | 3.62 | 4.25 | 5.99 | 0 | 99 | 51 | 156 |
| gunicorn-python@baseline | 18888 | 15720-20188 | 23.7% | 60% | - | 3.85 | 4.42 | 4.69 | 0 | 100 | 48 | 120 |

