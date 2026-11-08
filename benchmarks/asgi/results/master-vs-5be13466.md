# ASGI benchmark: master-vs-5be13466

- commit: `6a0a716a84a3522c88646370f5759af24faa8214`
- date: 2026-11-08T17:12:08+00:00
- machine: Apple M4 Pro, 14 CPUs, macOS-27.2-arm64-arm-64bit-Mach-O
- Python 3.14.9; gunicorn 26.2.2, gunicorn_h1c 0.6.11, uvicorn 0.42.0, httptools 0.7.1, uvloop 0.22.1, wrk wrk 4.2.0 [kqueue] Copyright (C) 2012 Will Glozer
- 1 worker(s); wrk -t4 -c64; 10s measured after 3s warm-up; 5 rounds, variant order alternating
- commands:
  - gunicorn-fast: `<repo>/.venv/bin/python <repo>/benchmarks/asgi/_launch.py <repo> gunicorn -k asgi --http-parser fast --asgi-loop uvloop -w 1 --keep-alive 5 -b 127.0.0.1:PORT apps:app`
  - gunicorn-fast@baseline: `<repo>/.venv/bin/python <repo>/benchmarks/asgi/_launch.py <5be13466 worktree> gunicorn -k asgi --http-parser fast --asgi-loop uvloop -w 1 --keep-alive 5 -b 127.0.0.1:PORT apps:app`
  - gunicorn-python: `<repo>/.venv/bin/python <repo>/benchmarks/asgi/_launch.py <repo> gunicorn -k asgi --http-parser python --asgi-loop uvloop -w 1 --keep-alive 5 -b 127.0.0.1:PORT apps:app`
  - gunicorn-python@baseline: `<repo>/.venv/bin/python <repo>/benchmarks/asgi/_launch.py <5be13466 worktree> gunicorn -k asgi --http-parser python --asgi-loop uvloop -w 1 --keep-alive 5 -b 127.0.0.1:PORT apps:app`
  - gunicorn-uvicorn-worker: `<repo>/.venv/bin/python <repo>/benchmarks/asgi/_launch.py <repo> gunicorn -k uvicorn.workers.UvicornWorker -w 1 --keep-alive 5 -b 127.0.0.1:PORT apps:app`
  - uvicorn: `<repo>/.venv/bin/python <repo>/benchmarks/asgi/_launch.py <repo> uvicorn apps:app --http httptools --loop uvloop --workers 1 --timeout-keep-alive 5 --no-access-log --host 127.0.0.1 --port PORT`

## small_keepalive

| variant | req/s median | min-max | spread | vs uvicorn | vs baseline | p50 ms | p95 ms | p99 ms | errors | server CPU % | client CPU % | peak RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gunicorn-fast | 41258 | 40173-41794 | 3.9% | 64% | +1.5% | 1.56 | 1.90 | 2.06 | 0 | 100 | 64 | 62 |
| gunicorn-python | 36169 | 35949-37173 | 3.4% | 56% | -1.5% | 1.74 | 1.96 | 2.14 | 0 | 100 | 58 | 61 |
| uvicorn | 64055 | 27652-65709 | 59.4% | 100% | - | 1.10 | 1.35 | 1.47 | 0 | 100 | 89 | 39 |
| gunicorn-uvicorn-worker | 59475 | 46356-62017 | 26.3% | 93% | - | 1.19 | 1.45 | 1.60 | 0 | 99 | 83 | 68 |
| gunicorn-fast@baseline | 40656 | 40210-42119 | 4.7% | 63% | - | 1.61 | 2.02 | 2.26 | 0 | 99 | 63 | 62 |
| gunicorn-python@baseline | 36709 | 36281-37354 | 2.9% | 57% | - | 1.72 | 1.95 | 2.14 | 0 | 100 | 55 | 61 |

## pct_target

| variant | req/s median | min-max | spread | vs uvicorn | vs baseline | p50 ms | p95 ms | p99 ms | errors | server CPU % | client CPU % | peak RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gunicorn-fast | 40300 | 39856-40691 | 2.1% | 71% | +1.6% | 1.59 | 1.94 | 2.10 | 0 | 100 | 63 | 64 |
| gunicorn-python | 35855 | 35124-36298 | 3.3% | 63% | -0.1% | 1.77 | 1.98 | 2.12 | 0 | 100 | 56 | 62 |
| uvicorn | 56958 | 26538-58542 | 56.2% | 100% | - | 1.24 | 1.54 | 1.82 | 0 | 100 | 72 | 40 |
| gunicorn-uvicorn-worker | 54754 | 52936-57580 | 8.5% | 96% | - | 1.30 | 1.59 | 1.75 | 0 | 99 | 73 | 68 |
| gunicorn-fast@baseline | 39671 | 38789-40426 | 4.1% | 70% | - | 1.65 | 2.08 | 2.35 | 0 | 99 | 63 | 63 |
| gunicorn-python@baseline | 35876 | 34983-36756 | 4.9% | 63% | - | 1.74 | 2.20 | 2.50 | 0 | 100 | 54 | 62 |

## many_headers

| variant | req/s median | min-max | spread | vs uvicorn | vs baseline | p50 ms | p95 ms | p99 ms | errors | server CPU % | client CPU % | peak RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gunicorn-fast | 26044 | 25614-26485 | 3.3% | 61% | +3.9% | 2.42 | 2.74 | 2.96 | 0 | 100 | 44 | 67 |
| gunicorn-python | 15041 | 14912-15287 | 2.5% | 35% | -1.8% | 4.23 | 4.62 | 4.83 | 0 | 100 | 25 | 64 |
| uvicorn | 42764 | 19083-46479 | 64.1% | 100% | - | 1.58 | 2.09 | 3.93 | 0 | 98 | 61 | 40 |
| gunicorn-uvicorn-worker | 45568 | 44757-48584 | 8.4% | 107% | - | 1.57 | 1.87 | 2.07 | 0 | 100 | 61 | 69 |
| gunicorn-fast@baseline | 25064 | 22990-26359 | 13.4% | 59% | - | 2.47 | 2.99 | 3.39 | 0 | 99 | 42 | 66 |
| gunicorn-python@baseline | 15316 | 14888-15370 | 3.1% | 36% | - | 4.38 | 5.33 | 5.85 | 0 | 100 | 22 | 65 |

## post_upload

| variant | req/s median | min-max | spread | vs uvicorn | vs baseline | p50 ms | p95 ms | p99 ms | errors | server CPU % | client CPU % | peak RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gunicorn-fast | 28219 | 26360-28325 | 7.0% | 82% | +3.6% | 2.29 | 2.59 | 2.77 | 0 | 99 | 101 | 90 |
| gunicorn-python | 25084 | 24114-25388 | 5.1% | 73% | +2.3% | 2.55 | 2.87 | 3.10 | 0 | 99 | 92 | 74 |
| uvicorn | 34320 | 15460-35354 | 58.0% | 100% | - | 1.88 | 2.21 | 2.44 | 0 | 99 | 118 | 56 |
| gunicorn-uvicorn-worker | 34658 | 33621-36980 | 9.7% | 101% | - | 1.86 | 2.17 | 2.39 | 0 | 99 | 123 | 76 |
| gunicorn-fast@baseline | 27229 | 26550-28997 | 9.0% | 79% | - | 2.33 | 2.75 | 3.49 | 0 | 99 | 103 | 90 |
| gunicorn-python@baseline | 24526 | 24144-26033 | 7.7% | 71% | - | 2.58 | 3.05 | 3.48 | 0 | 99 | 90 | 78 |

## chunked_upload

| variant | req/s median | min-max | spread | vs uvicorn | vs baseline | p50 ms | p95 ms | p99 ms | errors | server CPU % | client CPU % | peak RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gunicorn-fast | 30989 | 30727-31575 | 2.7% | 69% | -3.6% | 2.02 | 2.30 | 2.47 | 0 | 100 | 56 | 92 |
| gunicorn-python | 24009 | 23240-24295 | 4.4% | 53% | -0.9% | 2.64 | 2.91 | 3.12 | 0 | 100 | 41 | 74 |
| uvicorn | 45235 | 42780-46572 | 8.4% | 100% | - | 1.58 | 1.90 | 2.11 | 0 | 99 | 67 | 56 |
| gunicorn-uvicorn-worker | 44716 | 44258-46759 | 5.6% | 99% | - | 1.58 | 1.92 | 2.18 | 0 | 100 | 69 | 77 |
| gunicorn-fast@baseline | 32150 | 28426-32387 | 12.3% | 71% | - | 1.95 | 2.27 | 2.53 | 0 | 100 | 55 | 92 |
| gunicorn-python@baseline | 24228 | 23962-24705 | 3.1% | 54% | - | 2.58 | 2.92 | 3.33 | 0 | 100 | 40 | 79 |

## large_response

| variant | req/s median | min-max | spread | vs uvicorn | vs baseline | p50 ms | p95 ms | p99 ms | errors | server CPU % | client CPU % | peak RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gunicorn-fast | 6303 | 5628-6492 | 13.7% | 107% | +13.6% | 9.61 | 13.01 | 22.92 | 0 | 99 | 78 | 130 |
| gunicorn-python | 5908 | 4779-6506 | 29.2% | 100% | +5.5% | 10.57 | 13.53 | 24.58 | 0 | 99 | 75 | 122 |
| uvicorn | 5904 | 5744-7686 | 32.9% | 100% | - | 10.44 | 14.27 | 21.47 | 0 | 99 | 86 | 53 |
| gunicorn-uvicorn-worker | 6323 | 5565-7071 | 23.8% | 107% | - | 9.97 | 12.41 | 19.76 | 0 | 99 | 90 | 77 |
| gunicorn-fast@baseline | 5548 | 5027-6553 | 27.5% | 94% | - | 11.30 | 14.09 | 26.30 | 0 | 99 | 77 | 141 |
| gunicorn-python@baseline | 5600 | 5364-6352 | 17.7% | 95% | - | 11.19 | 14.04 | 25.60 | 0 | 99 | 75 | 122 |

## stream_response

| variant | req/s median | min-max | spread | vs uvicorn | vs baseline | p50 ms | p95 ms | p99 ms | errors | server CPU % | client CPU % | peak RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gunicorn-fast | 20280 | 20028-20679 | 3.2% | 65% | +5.4% | 3.58 | 4.12 | 4.36 | 0 | 100 | 51 | 131 |
| gunicorn-python | 18525 | 9394-19424 | 54.1% | 59% | -0.8% | 3.90 | 4.51 | 4.83 | 0 | 99 | 48 | 118 |
| uvicorn | 31428 | 23222-32059 | 28.1% | 100% | - | 2.00 | 2.39 | 4.08 | 0 | 99 | 52 | 53 |
| gunicorn-uvicorn-worker | 31450 | 27245-32460 | 16.6% | 100% | - | 1.99 | 2.42 | 4.05 | 0 | 99 | 50 | 77 |
| gunicorn-fast@baseline | 19250 | 18592-20495 | 9.9% | 61% | - | 3.74 | 4.34 | 4.78 | 0 | 99 | 51 | 142 |
| gunicorn-python@baseline | 18671 | 18442-18930 | 2.6% | 59% | - | 3.85 | 4.55 | 5.27 | 0 | 99 | 48 | 104 |

