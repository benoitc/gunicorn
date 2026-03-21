#!/usr/bin/env python
"""
Benchmark comparing HTTP parser implementations.

Compares:
- WSGI Python parser vs Fast parser (gunicorn_h1c)
- ASGI Python parser vs Fast parser (gunicorn_h1c)

Usage:
    python benchmarks/http_parser_benchmark.py
"""

import io
import time
import statistics
from typing import NamedTuple

from gunicorn.config import Config
from gunicorn.http.message import Request, _check_fast_parser
from gunicorn.http.unreader import IterUnreader


# Check if fast parser is available
try:
    import gunicorn_h1c
    FAST_AVAILABLE = True
except ImportError:
    FAST_AVAILABLE = False
    print("WARNING: gunicorn_h1c not installed. Fast parser benchmarks will be skipped.")
    print("Install with: pip install gunicorn_h1c\n")


class BenchmarkResult(NamedTuple):
    name: str
    iterations: int
    total_time: float
    avg_time_us: float
    min_time_us: float
    max_time_us: float
    requests_per_sec: float


# Test requests of varying complexity
SIMPLE_REQUEST = b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n"

MEDIUM_REQUEST = b"""POST /api/users HTTP/1.1\r
Host: api.example.com\r
Content-Type: application/json\r
Content-Length: 42\r
Accept: application/json\r
Authorization: Bearer token123\r
X-Request-ID: abc-123-def-456\r
\r
"""

COMPLEX_REQUEST = b"""POST /api/v2/resources/items HTTP/1.1\r
Host: api.example.com\r
Content-Type: application/json; charset=utf-8\r
Content-Length: 1024\r
Accept: application/json, text/plain, */*\r
Accept-Language: en-US,en;q=0.9,fr;q=0.8\r
Accept-Encoding: gzip, deflate, br\r
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ\r
X-Request-ID: 550e8400-e29b-41d4-a716-446655440000\r
X-Correlation-ID: 7f3d8c2a-1b4e-4a6f-9c8d-2e5f6a7b8c9d\r
X-Forwarded-For: 203.0.113.195, 70.41.3.18, 150.172.238.178\r
X-Forwarded-Proto: https\r
X-Real-IP: 203.0.113.195\r
User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36\r
Cache-Control: no-cache, no-store, must-revalidate\r
Pragma: no-cache\r
Cookie: session=abc123; preferences=dark_mode\r
If-None-Match: "etag-value-here"\r
If-Modified-Since: Wed, 21 Oct 2024 07:28:00 GMT\r
\r
"""


def create_wsgi_config(use_fast: bool) -> Config:
    """Create a config for WSGI parsing."""
    cfg = Config()
    cfg.set('http_parser', 'fast' if use_fast else 'python')
    return cfg


def benchmark_wsgi_parser(request_data: bytes, cfg: Config, iterations: int) -> BenchmarkResult:
    """Benchmark WSGI parser."""
    times = []
    parser_type = cfg.http_parser

    for _ in range(iterations):
        # Create fresh unreader for each iteration
        unreader = IterUnreader(iter([request_data]))

        start = time.perf_counter()
        req = Request(cfg, unreader, ('127.0.0.1', 8000), req_number=1)
        end = time.perf_counter()

        times.append(end - start)

        # Verify parsing worked
        assert req.method is not None

    total_time = sum(times)
    avg_time = statistics.mean(times)
    min_time = min(times)
    max_time = max(times)

    return BenchmarkResult(
        name=f"WSGI {parser_type}",
        iterations=iterations,
        total_time=total_time,
        avg_time_us=avg_time * 1_000_000,
        min_time_us=min_time * 1_000_000,
        max_time_us=max_time * 1_000_000,
        requests_per_sec=iterations / total_time,
    )


def benchmark_asgi_parser(request_data: bytes, cfg: Config, iterations: int) -> BenchmarkResult:
    """Benchmark ASGI parser."""
    from gunicorn.asgi.parser import HttpParser

    times = []
    parser_type = cfg.http_parser

    for _ in range(iterations):
        # Create fresh parser for each iteration
        parser = HttpParser(cfg, ('127.0.0.1', 8000), is_ssl=False)

        start = time.perf_counter()
        result = parser.feed(bytearray(request_data))
        end = time.perf_counter()

        times.append(end - start)

        # Verify parsing worked
        assert result is not None
        assert result.method is not None

    total_time = sum(times)
    avg_time = statistics.mean(times)
    min_time = min(times)
    max_time = max(times)

    return BenchmarkResult(
        name=f"ASGI {parser_type}",
        iterations=iterations,
        total_time=total_time,
        avg_time_us=avg_time * 1_000_000,
        min_time_us=min_time * 1_000_000,
        max_time_us=max_time * 1_000_000,
        requests_per_sec=iterations / total_time,
    )


def print_result(result: BenchmarkResult, baseline: BenchmarkResult = None):
    """Print benchmark result."""
    speedup = ""
    if baseline and baseline.avg_time_us > 0:
        ratio = baseline.avg_time_us / result.avg_time_us
        if ratio > 1:
            speedup = f"  ({ratio:.2f}x faster)"
        elif ratio < 1:
            speedup = f"  ({1/ratio:.2f}x slower)"

    print(f"  {result.name:20} {result.avg_time_us:8.2f} us/req  "
          f"({result.requests_per_sec:,.0f} req/s){speedup}")


def run_benchmark_suite(name: str, request_data: bytes, iterations: int):
    """Run a complete benchmark suite for a request type."""
    print(f"\n{'='*60}")
    print(f"Benchmark: {name}")
    print(f"Request size: {len(request_data)} bytes, Iterations: {iterations:,}")
    print('='*60)

    results = []

    # WSGI Python
    cfg_python = create_wsgi_config(use_fast=False)
    result_wsgi_python = benchmark_wsgi_parser(request_data, cfg_python, iterations)
    results.append(result_wsgi_python)

    # WSGI Fast (if available)
    if FAST_AVAILABLE:
        cfg_fast = create_wsgi_config(use_fast=True)
        result_wsgi_fast = benchmark_wsgi_parser(request_data, cfg_fast, iterations)
        results.append(result_wsgi_fast)

    # ASGI Python
    cfg_python = create_wsgi_config(use_fast=False)
    result_asgi_python = benchmark_asgi_parser(request_data, cfg_python, iterations)
    results.append(result_asgi_python)

    # ASGI Fast (if available)
    if FAST_AVAILABLE:
        cfg_fast = create_wsgi_config(use_fast=True)
        result_asgi_fast = benchmark_asgi_parser(request_data, cfg_fast, iterations)
        results.append(result_asgi_fast)

    # Print results
    print("\nResults (avg time per request):")
    print("-" * 60)

    # Print WSGI results
    print_result(result_wsgi_python)
    if FAST_AVAILABLE:
        print_result(result_wsgi_fast, result_wsgi_python)

    print()

    # Print ASGI results
    print_result(result_asgi_python)
    if FAST_AVAILABLE:
        print_result(result_asgi_fast, result_asgi_python)

    return results


def main():
    print("HTTP Parser Benchmark")
    print("=" * 60)
    print(f"Fast parser (gunicorn_h1c): {'Available' if FAST_AVAILABLE else 'Not installed'}")

    # Warmup
    print("\nWarming up...")
    cfg = create_wsgi_config(use_fast=False)
    for _ in range(100):
        unreader = IterUnreader(iter([SIMPLE_REQUEST]))
        Request(cfg, unreader, ('127.0.0.1', 8000), req_number=1)

    if FAST_AVAILABLE:
        cfg = create_wsgi_config(use_fast=True)
        for _ in range(100):
            unreader = IterUnreader(iter([SIMPLE_REQUEST]))
            Request(cfg, unreader, ('127.0.0.1', 8000), req_number=1)

    # Run benchmarks
    iterations = 10000

    all_results = []
    all_results.extend(run_benchmark_suite("Simple GET Request", SIMPLE_REQUEST, iterations))
    all_results.extend(run_benchmark_suite("Medium POST Request", MEDIUM_REQUEST, iterations))
    all_results.extend(run_benchmark_suite("Complex POST Request", COMPLEX_REQUEST, iterations))

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    if FAST_AVAILABLE:
        # Calculate overall speedups
        wsgi_python_avg = statistics.mean([r.avg_time_us for r in all_results if r.name == "WSGI python"])
        wsgi_fast_avg = statistics.mean([r.avg_time_us for r in all_results if r.name == "WSGI fast"])
        asgi_python_avg = statistics.mean([r.avg_time_us for r in all_results if r.name == "ASGI python"])
        asgi_fast_avg = statistics.mean([r.avg_time_us for r in all_results if r.name == "ASGI fast"])

        print(f"\nWSGI: Fast parser is {wsgi_python_avg/wsgi_fast_avg:.2f}x faster than Python parser")
        print(f"ASGI: Fast parser is {asgi_python_avg/asgi_fast_avg:.2f}x faster than Python parser")
    else:
        print("\nInstall gunicorn_h1c to see fast parser comparison:")
        print("  pip install gunicorn_h1c")

    print()


if __name__ == "__main__":
    main()
