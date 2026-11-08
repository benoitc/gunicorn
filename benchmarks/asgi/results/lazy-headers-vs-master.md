# ASGI benchmark: head-vs-master

- commit: `c33bbcab289b1b7797e0e29afe2c801f52e9a28a`
- date: 2026-11-08T22:12:33+00:00
- machine: Apple M4 Pro, 14 CPUs, macOS-27.2-arm64-arm-64bit-Mach-O
- Python 3.14.9; gunicorn 26.2.2, gunicorn_h1c 0.6.11, uvicorn 0.42.0, httptools 0.7.1, uvloop 0.22.1, wrk wrk 4.2.0 [kqueue] Copyright (C) 2012 Will Glozer
- 1 worker(s); wrk -t4 -c64; 10s measured after 3s warm-up; 5 rounds, variant order alternating
- commands:
  - gunicorn-fast: `/Users/benoitc/Projects/gunicorn/.venv/bin/python /Users/benoitc/Projects/gunicorn/benchmarks/asgi/_launch.py /Users/benoitc/Projects/gunicorn gunicorn -k asgi --http-parser fast --asgi-loop uvloop -w 1 --keep-alive 5 -b 127.0.0.1:PORT apps:app`
  - gunicorn-fast@baseline: `/Users/benoitc/Projects/gunicorn/.venv/bin/python /Users/benoitc/Projects/gunicorn/benchmarks/asgi/_launch.py /private/tmp/claude-501/-Users-benoitc-Projects-gunicorn/4c638f51-b20a-4a54-b4c3-ad935d5e81a2/scratchpad/base gunicorn -k asgi --http-parser fast --asgi-loop uvloop -w 1 --keep-alive 5 -b 127.0.0.1:PORT apps:app`
  - gunicorn-python: `/Users/benoitc/Projects/gunicorn/.venv/bin/python /Users/benoitc/Projects/gunicorn/benchmarks/asgi/_launch.py /Users/benoitc/Projects/gunicorn gunicorn -k asgi --http-parser python --asgi-loop uvloop -w 1 --keep-alive 5 -b 127.0.0.1:PORT apps:app`
  - gunicorn-python@baseline: `/Users/benoitc/Projects/gunicorn/.venv/bin/python /Users/benoitc/Projects/gunicorn/benchmarks/asgi/_launch.py /private/tmp/claude-501/-Users-benoitc-Projects-gunicorn/4c638f51-b20a-4a54-b4c3-ad935d5e81a2/scratchpad/base gunicorn -k asgi --http-parser python --asgi-loop uvloop -w 1 --keep-alive 5 -b 127.0.0.1:PORT apps:app`
  - uvicorn: `/Users/benoitc/Projects/gunicorn/.venv/bin/python /Users/benoitc/Projects/gunicorn/benchmarks/asgi/_launch.py /Users/benoitc/Projects/gunicorn uvicorn apps:app --http httptools --loop uvloop --workers 1 --timeout-keep-alive 5 --no-access-log --host 127.0.0.1 --port PORT`

## small_keepalive

| variant | req/s median | min-max | spread | vs uvicorn | vs baseline | p50 ms | p95 ms | p99 ms | errors | server CPU % | client CPU % | peak RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gunicorn-fast | 57844 | 53878-59132 | 9.1% | 95% | +7.5% | 1.20 | 1.48 | 1.62 | 0 | 100 | 85 | 62 |
| gunicorn-python | 49803 | 47782-52184 | 8.8% | 82% | +6.6% | 1.41 | 1.70 | 1.83 | 0 | 100 | 71 | 61 |
| uvicorn | 60684 | 29470-65832 | 59.9% | 100% | - | 1.12 | 1.39 | 1.48 | 0 | 100 | 87 | 40 |
| gunicorn-fast@baseline | 53785 | 52895-55190 | 4.3% | 89% | - | 1.30 | 1.60 | 1.74 | 0 | 100 | 77 | 62 |
| gunicorn-python@baseline | 46725 | 44924-48031 | 6.6% | 77% | - | 1.49 | 1.80 | 1.94 | 0 | 100 | 67 | 61 |

## pct_target

| variant | req/s median | min-max | spread | vs uvicorn | vs baseline | p50 ms | p95 ms | p99 ms | errors | server CPU % | client CPU % | peak RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gunicorn-fast | 54829 | 51622-57871 | 11.4% | 99% | +5.5% | 1.27 | 1.55 | 1.73 | 0 | 100 | 79 | 63 |
| gunicorn-python | 47992 | 43420-49708 | 13.1% | 87% | +7.4% | 1.47 | 1.75 | 1.91 | 0 | 100 | 68 | 62 |
| uvicorn | 55421 | 24620-58221 | 60.6% | 100% | - | 1.26 | 1.55 | 1.76 | 0 | 99 | 80 | 40 |
| gunicorn-fast@baseline | 51966 | 48861-54977 | 11.8% | 94% | - | 1.36 | 1.63 | 1.77 | 0 | 100 | 74 | 63 |
| gunicorn-python@baseline | 44678 | 42246-46278 | 9.0% | 81% | - | 1.54 | 1.91 | 2.10 | 0 | 100 | 65 | 62 |

## many_headers

| variant | req/s median | min-max | spread | vs uvicorn | vs baseline | p50 ms | p95 ms | p99 ms | errors | server CPU % | client CPU % | peak RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gunicorn-fast | 36700 | 33467-38334 | 13.3% | 82% | +15.2% | 1.79 | 2.20 | 2.48 | 0 | 100 | 58 | 66 |
| gunicorn-python | 18753 | 8265-18831 | 56.3% | 42% | +11.4% | 3.85 | 4.43 | 4.80 | 0 | 100 | 27 | 64 |
| uvicorn | 44746 | 20773-46741 | 58.0% | 100% | - | 1.56 | 1.87 | 2.03 | 0 | 100 | 67 | 40 |
| gunicorn-fast@baseline | 31860 | 31278-32857 | 5.0% | 71% | - | 1.94 | 2.37 | 2.79 | 0 | 100 | 51 | 67 |
| gunicorn-python@baseline | 16827 | 16657-17094 | 2.6% | 38% | - | 3.83 | 4.68 | 5.09 | 0 | 100 | 25 | 65 |

## post_upload

| variant | req/s median | min-max | spread | vs uvicorn | vs baseline | p50 ms | p95 ms | p99 ms | errors | server CPU % | client CPU % | peak RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gunicorn-fast | 34252 | 31856-36057 | 12.3% | 94% | +7.3% | 1.83 | 2.21 | 2.48 | 0 | 99 | 126 | 91 |
| gunicorn-python | 29120 | 10500-31140 | 70.9% | 80% | +0.3% | 2.22 | 2.49 | 2.64 | 0 | 100 | 109 | 73 |
| uvicorn | 36374 | 23968-37337 | 36.8% | 100% | - | 1.79 | 2.04 | 2.26 | 0 | 99 | 126 | 53 |
| gunicorn-fast@baseline | 31908 | 30928-33630 | 8.5% | 88% | - | 2.02 | 2.34 | 2.98 | 0 | 99 | 118 | 96 |
| gunicorn-python@baseline | 29023 | 27112-29803 | 9.3% | 80% | - | 2.21 | 2.58 | 3.06 | 0 | 99 | 104 | 75 |

## chunked_upload

| variant | req/s median | min-max | spread | vs uvicorn | vs baseline | p50 ms | p95 ms | p99 ms | errors | server CPU % | client CPU % | peak RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gunicorn-fast | 40685 | 39154-41938 | 6.8% | 85% | +4.0% | 1.65 | 1.97 | 2.13 | 0 | 100 | 66 | 94 |
| gunicorn-python | 28291 | 11382-28983 | 62.2% | 59% | +2.6% | 2.23 | 2.64 | 2.85 | 0 | 100 | 45 | 74 |
| uvicorn | 47601 | 46661-49091 | 5.1% | 100% | - | 1.48 | 1.77 | 1.90 | 0 | 100 | 72 | 54 |
| gunicorn-fast@baseline | 39119 | 35201-40201 | 12.8% | 82% | - | 1.63 | 2.00 | 2.20 | 0 | 100 | 65 | 98 |
| gunicorn-python@baseline | 27585 | 26624-27985 | 4.9% | 58% | - | 2.29 | 2.59 | 2.74 | 0 | 100 | 47 | 76 |

## large_response

| variant | req/s median | min-max | spread | vs uvicorn | vs baseline | p50 ms | p95 ms | p99 ms | errors | server CPU % | client CPU % | peak RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gunicorn-fast | 6772 | 4125-7949 | 56.5% | 92% | +10.9% | 8.71 | 12.41 | 18.28 | 0 | 100 | 89 | 95 |
| gunicorn-python | 6342 | 3352-7177 | 60.3% | 86% | +6.7% | 9.68 | 13.29 | 21.94 | 0 | 100 | 88 | 75 |
| uvicorn | 7363 | 6753-8191 | 19.5% | 100% | - | 8.25 | 11.81 | 16.21 | 0 | 100 | 93 | 55 |
| gunicorn-fast@baseline | 6106 | 5106-7287 | 35.7% | 83% | - | 9.40 | 15.01 | 24.59 | 0 | 100 | 79 | 146 |
| gunicorn-python@baseline | 5941 | 2608-6319 | 62.5% | 81% | - | 10.12 | 14.67 | 23.42 | 0 | 99 | 76 | 128 |

## stream_response

| variant | req/s median | min-max | spread | vs uvicorn | vs baseline | p50 ms | p95 ms | p99 ms | errors | server CPU % | client CPU % | peak RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gunicorn-fast | 29221 | 22598-30310 | 26.4% | 89% | +42.4% | 2.14 | 2.56 | 4.31 | 0 | 100 | 46 | 95 |
| gunicorn-python | 23177 | 13949-27668 | 59.2% | 71% | +12.5% | 2.52 | 3.32 | 6.10 | 0 | 99 | 42 | 75 |
| uvicorn | 32764 | 31419-34428 | 9.2% | 100% | - | 1.92 | 2.30 | 3.91 | 0 | 100 | 50 | 55 |
| gunicorn-fast@baseline | 20527 | 10885-22579 | 57.0% | 63% | - | 3.43 | 4.07 | 4.25 | 0 | 100 | 57 | 146 |
| gunicorn-python@baseline | 20595 | 19851-21360 | 7.3% | 63% | - | 3.43 | 4.10 | 4.39 | 0 | 100 | 54 | 129 |

