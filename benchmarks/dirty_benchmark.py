#!/usr/bin/env python3
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Dirty Pool Benchmark Runner

Stress tests and benchmarks the dirty arbiter pool to find bottlenecks
and optimization opportunities.

Test Modes:
- Isolated: Direct client -> arbiter -> worker (no HTTP overhead)
- Integrated: HTTP workers calling dirty pool (realistic end-to-end)

Usage:
    # Quick smoke test
    python benchmarks/dirty_benchmark.py --quick

    # Full isolated suite
    python benchmarks/dirty_benchmark.py --isolated --output results.json

    # Specific scenario
    python benchmarks/dirty_benchmark.py \
        --duration 100 \
        --concurrency 50 \
        --workers 4 \
        --threads 2

    # Payload size tests
    python benchmarks/dirty_benchmark.py --payload-tests

    # Integration tests (requires gunicorn running)
    python benchmarks/dirty_benchmark.py --integrated --url http://127.0.0.1:8000
"""

import argparse
import asyncio
import json
import multiprocessing
import os
import signal
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

# Add parent to path for imports
BENCHMARK_DIR = Path(__file__).parent
sys.path.insert(0, str(BENCHMARK_DIR.parent))

from gunicorn.dirty.client import DirtyClient
from gunicorn.dirty.arbiter import DirtyArbiter


# Default benchmark app path
BENCHMARK_APP = "benchmarks.dirty_bench_app:BenchmarkApp"


@dataclass
class LatencyStats:
    """Latency statistics in milliseconds."""
    min: float = 0.0
    max: float = 0.0
    mean: float = 0.0
    stddev: float = 0.0
    p50: float = 0.0
    p95: float = 0.0
    p99: float = 0.0

    @classmethod
    def from_samples(cls, samples: list[float]) -> "LatencyStats":
        """Calculate statistics from list of latency samples."""
        if not samples:
            return cls()

        sorted_samples = sorted(samples)
        n = len(sorted_samples)

        return cls(
            min=sorted_samples[0],
            max=sorted_samples[-1],
            mean=statistics.mean(sorted_samples),
            stddev=statistics.stdev(sorted_samples) if n > 1 else 0.0,
            p50=sorted_samples[int(n * 0.50)],
            p95=sorted_samples[int(n * 0.95)] if n >= 20 else sorted_samples[-1],
            p99=sorted_samples[int(n * 0.99)] if n >= 100 else sorted_samples[-1],
        )


@dataclass
class BenchmarkResult:
    """Results from a single benchmark run."""
    scenario: str
    config: dict
    total_requests: int = 0
    successful: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    duration_sec: float = 0.0
    requests_per_sec: float = 0.0
    latency_ms: LatencyStats = field(default_factory=LatencyStats)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        d = asdict(self)
        d['latency_ms'] = asdict(self.latency_ms)
        return d


class MockConfig:
    """Mock gunicorn config for standalone arbiter testing."""

    def __init__(
        self,
        dirty_apps: list[str],
        dirty_workers: int = 2,
        dirty_threads: int = 1,
        dirty_timeout: int = 300,
        dirty_graceful_timeout: int = 30,
    ):
        self.dirty_apps = dirty_apps
        self.dirty_workers = dirty_workers
        self.dirty_threads = dirty_threads
        self.dirty_timeout = dirty_timeout
        self.dirty_graceful_timeout = dirty_graceful_timeout

        # Other required config
        self.env = {}
        self.uid = os.getuid()
        self.gid = os.getgid()
        self.initgroups = False
        self.proc_name = "dirty-benchmark"

        # WorkerTmp requirements
        self.umask = 0
        self.worker_tmp_dir = None

    # Hook stubs
    def on_dirty_starting(self, arbiter):
        pass

    def dirty_post_fork(self, arbiter, worker):
        pass

    def dirty_worker_init(self, worker):
        pass

    def dirty_worker_exit(self, arbiter, worker):
        pass


class MockLogger:
    """Mock logger for standalone testing."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def debug(self, msg, *args):
        if self.verbose:
            print(f"[DEBUG] {msg % args if args else msg}")

    def info(self, msg, *args):
        if self.verbose:
            print(f"[INFO] {msg % args if args else msg}")

    def warning(self, msg, *args):
        print(f"[WARN] {msg % args if args else msg}")

    def error(self, msg, *args):
        print(f"[ERROR] {msg % args if args else msg}")

    def critical(self, msg, *args):
        print(f"[CRIT] {msg % args if args else msg}")

    def exception(self, msg, *args):
        print(f"[EXC] {msg % args if args else msg}")

    def reopen_files(self):
        pass

    def close_on_exec(self):
        pass


class IsolatedBenchmark:
    """
    Run benchmarks directly against the dirty pool without HTTP.

    Spawns a standalone dirty arbiter and workers, then runs concurrent
    clients to measure performance.
    """

    def __init__(
        self,
        dirty_workers: int = 2,
        dirty_threads: int = 1,
        dirty_timeout: int = 300,
        verbose: bool = False,
    ):
        self.dirty_workers = dirty_workers
        self.dirty_threads = dirty_threads
        self.dirty_timeout = dirty_timeout
        self.verbose = verbose

        self.arbiter = None
        self.arbiter_pid = None
        self.socket_path = None
        self._tmpdir = None

    def start(self):
        """Start the dirty arbiter and workers."""
        # Create temp directory for socket
        self._tmpdir = tempfile.mkdtemp(prefix="dirty-bench-")
        self.socket_path = os.path.join(self._tmpdir, "arbiter.sock")

        # Create config and logger
        cfg = MockConfig(
            dirty_apps=[BENCHMARK_APP],
            dirty_workers=self.dirty_workers,
            dirty_threads=self.dirty_threads,
            dirty_timeout=self.dirty_timeout,
        )
        log = MockLogger(verbose=self.verbose)

        # Fork arbiter process
        pid = os.fork()
        if pid == 0:
            # Child process - run arbiter
            try:
                arbiter = DirtyArbiter(cfg, log, socket_path=self.socket_path)
                arbiter.run()
            except Exception as e:
                print(f"Arbiter error: {e}")
            finally:
                os._exit(0)

        # Parent process
        self.arbiter_pid = pid

        # Wait for arbiter socket to be ready
        for _ in range(50):  # 5 seconds max
            if os.path.exists(self.socket_path):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Arbiter socket not ready")

        # Give workers time to start
        time.sleep(0.5)

    def stop(self):
        """Stop the dirty arbiter."""
        if self.arbiter_pid:
            try:
                os.kill(self.arbiter_pid, signal.SIGTERM)
                os.waitpid(self.arbiter_pid, 0)
            except (OSError, ChildProcessError):
                pass
            self.arbiter_pid = None

        # Cleanup temp directory
        if self._tmpdir:
            try:
                for f in os.listdir(self._tmpdir):
                    os.unlink(os.path.join(self._tmpdir, f))
                os.rmdir(self._tmpdir)
            except OSError:
                pass
            self._tmpdir = None

    def warmup(self, requests: int = 10):
        """Warm up the pool with a few requests."""
        with DirtyClient(self.socket_path, timeout=30.0) as client:
            for _ in range(requests):
                client.execute(BENCHMARK_APP, "health")

    def run_benchmark(
        self,
        action: str,
        args: tuple = (),
        kwargs: dict = None,
        total_requests: int = 1000,
        concurrency: int = 10,
        timeout: float = 30.0,
    ) -> tuple[list[float], list[str]]:
        """
        Run a benchmark with specified parameters.

        Each concurrent worker maintains a persistent connection to the arbiter
        and makes sequential requests. This simulates how real HTTP workers
        use the dirty client (one connection per worker thread).

        Args:
            action: Action to call on the benchmark app
            args: Positional arguments for the action
            kwargs: Keyword arguments for the action
            total_requests: Total number of requests to make
            concurrency: Number of concurrent clients
            timeout: Timeout per request in seconds

        Returns:
            Tuple of (latencies in ms, error messages)
        """
        kwargs = kwargs or {}
        latencies = []
        errors = []
        lock = threading.Lock()

        # Calculate requests per worker
        requests_per_worker = total_requests // concurrency
        remainder = total_requests % concurrency

        def worker_task(num_requests: int) -> None:
            """Worker that makes sequential requests on a persistent connection."""
            worker_latencies = []
            worker_errors = []

            try:
                client = DirtyClient(self.socket_path, timeout=timeout)
                client.connect()

                for _ in range(num_requests):
                    try:
                        start = time.perf_counter()
                        client.execute(BENCHMARK_APP, action, *args, **kwargs)
                        elapsed = (time.perf_counter() - start) * 1000
                        worker_latencies.append(elapsed)
                    except Exception as e:
                        worker_errors.append(str(e))
                        # Reconnect on error
                        try:
                            client.close()
                            client = DirtyClient(self.socket_path, timeout=timeout)
                            client.connect()
                        except Exception:
                            pass

                client.close()
            except Exception as e:
                worker_errors.append(f"Connection error: {e}")

            # Add results to shared lists
            with lock:
                latencies.extend(worker_latencies)
                errors.extend(worker_errors)

        # Run concurrent workers
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = []
            for i in range(concurrency):
                # Distribute remainder requests among first few workers
                num = requests_per_worker + (1 if i < remainder else 0)
                if num > 0:
                    futures.append(executor.submit(worker_task, num))

            # Wait for all workers to complete
            for future in as_completed(futures):
                future.result()  # Raises any exceptions

        return latencies, errors


class IntegratedBenchmark:
    """
    Run benchmarks against gunicorn with dirty pool via HTTP.

    Uses wrk or ab for load testing, or falls back to Python requests.
    """

    def __init__(
        self,
        url: str = "http://127.0.0.1:8000",
        verbose: bool = False,
    ):
        self.url = url.rstrip('/')
        self.verbose = verbose
        self._tool = None

    def check_dependencies(self) -> str | None:
        """Check for available load testing tools."""
        for tool in ['wrk', 'ab']:
            try:
                subprocess.run([tool, '--version'], capture_output=True,
                               check=False)
                return tool
            except FileNotFoundError:
                continue
        return None

    def warmup(self, requests: int = 10):
        """Warm up the server."""
        import urllib.request
        for _ in range(requests):
            try:
                urllib.request.urlopen(f"{self.url}/health", timeout=5)
            except Exception:
                pass

    def run_wrk(
        self,
        path: str,
        duration: int = 10,
        threads: int = 4,
        connections: int = 100,
    ) -> dict:
        """Run wrk benchmark and parse results."""
        url = f"{self.url}{path}"
        cmd = [
            'wrk',
            '-t', str(threads),
            '-c', str(connections),
            '-d', f'{duration}s',
            '--latency',
            url,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True,
                                check=False)
        return self._parse_wrk_output(result.stdout)

    def _parse_wrk_output(self, output: str) -> dict:
        """Parse wrk output to extract metrics."""
        metrics = {
            'requests_per_sec': 0.0,
            'latency_ms': {},
            'errors': 0,
        }

        for line in output.split('\n'):
            if 'Requests/sec' in line:
                try:
                    metrics['requests_per_sec'] = float(
                        line.split(':')[1].strip())
                except (ValueError, IndexError):
                    pass
            elif 'Latency' in line and 'Distribution' not in line:
                parts = line.split()
                if len(parts) >= 2:
                    metrics['latency_ms']['avg'] = self._parse_duration(
                        parts[1])
            elif '50%' in line:
                parts = line.split()
                if len(parts) >= 2:
                    metrics['latency_ms']['p50'] = self._parse_duration(
                        parts[1])
            elif '99%' in line:
                parts = line.split()
                if len(parts) >= 2:
                    metrics['latency_ms']['p99'] = self._parse_duration(
                        parts[1])
            elif 'Socket errors' in line:
                # Parse error counts
                parts = line.split(',')
                for part in parts:
                    if any(x in part for x in ['connect', 'read', 'write',
                                                 'timeout']):
                        try:
                            metrics['errors'] += int(part.split()[-1])
                        except (ValueError, IndexError):
                            pass

        return metrics

    def _parse_duration(self, s: str) -> float:
        """Parse wrk duration string (e.g., '12.34ms', '1.23s') to ms."""
        s = s.strip()
        if s.endswith('us'):
            return float(s[:-2]) / 1000
        elif s.endswith('ms'):
            return float(s[:-2])
        elif s.endswith('s'):
            return float(s[:-1]) * 1000
        else:
            return float(s)

    def run_python_benchmark(
        self,
        path: str,
        total_requests: int = 1000,
        concurrency: int = 10,
        timeout: float = 30.0,
    ) -> tuple[list[float], list[str]]:
        """
        Run benchmark using Python urllib.

        Fallback when wrk/ab not available.
        """
        import urllib.request
        import urllib.error

        url = f"{self.url}{path}"
        latencies = []
        errors = []

        def make_request() -> tuple[float | None, str | None]:
            try:
                start = time.perf_counter()
                urllib.request.urlopen(url, timeout=timeout)
                elapsed = (time.perf_counter() - start) * 1000
                return elapsed, None
            except Exception as e:
                return None, str(e)

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(make_request)
                       for _ in range(total_requests)]

            for future in as_completed(futures):
                latency, error = future.result()
                if latency is not None:
                    latencies.append(latency)
                if error:
                    errors.append(error)

        return latencies, errors


def run_isolated_suite(
    workers: int = 2,
    threads: int = 1,
    verbose: bool = False,
) -> list[BenchmarkResult]:
    """Run the full isolated benchmark suite."""
    results = []

    bench = IsolatedBenchmark(
        dirty_workers=workers,
        dirty_threads=threads,
        verbose=verbose,
    )

    print(f"\nStarting isolated benchmarks (workers={workers}, "
          f"threads={threads})...")

    try:
        bench.start()
        bench.warmup()

        # Define scenarios
        scenarios = [
            # Baseline
            {
                "name": "baseline_10ms",
                "action": "sleep_task",
                "args": (10,),
                "requests": 1000,
                "concurrency": 1,
                "description": "Single request latency (10ms sleep)",
            },
            # Throughput
            {
                "name": "throughput_10ms",
                "action": "sleep_task",
                "args": (10,),
                "requests": 5000,
                "concurrency": 100,
                "description": "Max requests/sec (10ms sleep, 100 clients)",
            },
            # CPU Bound
            {
                "name": "cpu_bound_100ms",
                "action": "cpu_task",
                "args": (100,),
                "requests": 500,
                "concurrency": 20,
                "description": "CPU-bound work (100ms, 20 clients)",
            },
            # I/O Bound
            {
                "name": "io_bound_500ms",
                "action": "sleep_task",
                "args": (500,),
                "requests": 200,
                "concurrency": 50,
                "description": "I/O-bound work (500ms sleep, 50 clients)",
            },
            # Mixed
            {
                "name": "mixed_50_50",
                "action": "mixed_task",
                "args": (50, 50),
                "requests": 500,
                "concurrency": 30,
                "description": "Mixed workload (50ms sleep + 50ms CPU)",
            },
            # Overload
            {
                "name": "overload_10ms",
                "action": "sleep_task",
                "args": (10,),
                "requests": 2000,
                "concurrency": 200,
                "description": "Overload test (10ms, 200 clients)",
            },
        ]

        for scenario in scenarios:
            print(f"  Running {scenario['name']}: {scenario['description']}...")

            start_time = time.perf_counter()
            latencies, errors = bench.run_benchmark(
                action=scenario["action"],
                args=scenario.get("args", ()),
                kwargs=scenario.get("kwargs"),
                total_requests=scenario["requests"],
                concurrency=scenario["concurrency"],
            )
            duration = time.perf_counter() - start_time

            result = BenchmarkResult(
                scenario=scenario["name"],
                config={
                    "dirty_workers": workers,
                    "dirty_threads": threads,
                    "task_action": scenario["action"],
                    "task_args": scenario.get("args", ()),
                    "concurrency": scenario["concurrency"],
                },
                total_requests=scenario["requests"],
                successful=len(latencies),
                failed=len(errors),
                errors=errors[:10] if errors else [],  # First 10 errors
                duration_sec=round(duration, 2),
                requests_per_sec=round(len(latencies) / duration, 1),
                latency_ms=LatencyStats.from_samples(latencies),
            )
            results.append(result)

            print(f"    Requests/sec: {result.requests_per_sec:.1f}, "
                  f"p50: {result.latency_ms.p50:.1f}ms, "
                  f"p99: {result.latency_ms.p99:.1f}ms, "
                  f"failed: {result.failed}")

    finally:
        bench.stop()

    return results


def run_payload_suite(
    workers: int = 2,
    threads: int = 1,
    verbose: bool = False,
) -> list[BenchmarkResult]:
    """Run payload size benchmark suite."""
    results = []

    bench = IsolatedBenchmark(
        dirty_workers=workers,
        dirty_threads=threads,
        verbose=verbose,
    )

    print(f"\nStarting payload benchmarks (workers={workers})...")

    try:
        bench.start()
        bench.warmup()

        # Payload sizes to test
        payload_sizes = [
            (100, "100B", "Tiny payload"),
            (1024, "1KB", "Small payload"),
            (10240, "10KB", "Medium payload"),
            (102400, "100KB", "Large payload"),
            (1048576, "1MB", "Very large payload"),
        ]

        for size, size_label, description in payload_sizes:
            # Adjust concurrency for larger payloads
            concurrency = max(5, 100 // (size // 1024 + 1))
            requests = max(100, 1000 // (size // 1024 + 1))

            print(f"  Running payload_{size_label}: {description}...")

            start_time = time.perf_counter()
            latencies, errors = bench.run_benchmark(
                action="payload_task",
                args=(size,),
                total_requests=requests,
                concurrency=concurrency,
            )
            duration = time.perf_counter() - start_time

            result = BenchmarkResult(
                scenario=f"payload_{size_label}",
                config={
                    "dirty_workers": workers,
                    "dirty_threads": threads,
                    "payload_bytes": size,
                    "concurrency": concurrency,
                },
                total_requests=requests,
                successful=len(latencies),
                failed=len(errors),
                errors=errors[:5] if errors else [],
                duration_sec=round(duration, 2),
                requests_per_sec=round(len(latencies) / duration, 1),
                latency_ms=LatencyStats.from_samples(latencies),
            )
            results.append(result)

            # Calculate throughput in MB/s
            throughput_mb = (len(latencies) * size) / duration / 1024 / 1024

            print(f"    Requests/sec: {result.requests_per_sec:.1f}, "
                  f"p50: {result.latency_ms.p50:.1f}ms, "
                  f"throughput: {throughput_mb:.1f} MB/s")

    finally:
        bench.stop()

    return results


def run_quick_test(verbose: bool = False) -> list[BenchmarkResult]:
    """Run a quick smoke test."""
    results = []

    bench = IsolatedBenchmark(dirty_workers=1, dirty_threads=1, verbose=verbose)

    print("\nRunning quick smoke test...")

    try:
        bench.start()
        bench.warmup(5)

        # Simple test
        start_time = time.perf_counter()
        latencies, errors = bench.run_benchmark(
            action="sleep_task",
            args=(10,),
            total_requests=100,
            concurrency=10,
        )
        duration = time.perf_counter() - start_time

        result = BenchmarkResult(
            scenario="quick_test",
            config={"dirty_workers": 1, "dirty_threads": 1},
            total_requests=100,
            successful=len(latencies),
            failed=len(errors),
            errors=errors[:5] if errors else [],
            duration_sec=round(duration, 2),
            requests_per_sec=round(len(latencies) / duration, 1),
            latency_ms=LatencyStats.from_samples(latencies),
        )
        results.append(result)

        print(f"  Requests/sec: {result.requests_per_sec:.1f}, "
              f"p50: {result.latency_ms.p50:.1f}ms, "
              f"failed: {result.failed}")

        if result.failed == 0:
            print("  PASS: Quick test successful")
        else:
            print(f"  WARN: {result.failed} requests failed")

    finally:
        bench.stop()

    return results


def run_config_sweep(verbose: bool = False) -> list[BenchmarkResult]:
    """
    Sweep through different configurations to find optimal settings.

    Tests combinations of workers and threads.
    """
    results = []

    configs = [
        (1, 1),   # Baseline
        (2, 1),   # 2 workers, 1 thread each
        (4, 1),   # 4 workers, 1 thread each
        (2, 2),   # 2 workers, 2 threads each
        (2, 4),   # 2 workers, 4 threads each
        (4, 2),   # 4 workers, 2 threads each
    ]

    print("\nRunning configuration sweep...")

    for workers, threads in configs:
        print(f"\n  Testing workers={workers}, threads={threads}...")

        bench = IsolatedBenchmark(
            dirty_workers=workers,
            dirty_threads=threads,
            verbose=verbose,
        )

        try:
            bench.start()
            bench.warmup()

            # Run a standard workload
            start_time = time.perf_counter()
            latencies, errors = bench.run_benchmark(
                action="mixed_task",
                args=(20, 20),  # 20ms sleep + 20ms CPU
                total_requests=1000,
                concurrency=50,
            )
            duration = time.perf_counter() - start_time

            result = BenchmarkResult(
                scenario=f"config_w{workers}_t{threads}",
                config={
                    "dirty_workers": workers,
                    "dirty_threads": threads,
                    "task": "mixed_task(20, 20)",
                    "concurrency": 50,
                },
                total_requests=1000,
                successful=len(latencies),
                failed=len(errors),
                errors=errors[:5] if errors else [],
                duration_sec=round(duration, 2),
                requests_per_sec=round(len(latencies) / duration, 1),
                latency_ms=LatencyStats.from_samples(latencies),
            )
            results.append(result)

            print(f"    Requests/sec: {result.requests_per_sec:.1f}, "
                  f"p50: {result.latency_ms.p50:.1f}ms, "
                  f"p99: {result.latency_ms.p99:.1f}ms")

        finally:
            bench.stop()

    # Print summary
    print("\n  Configuration Summary:")
    print("  " + "-" * 60)
    sorted_results = sorted(results, key=lambda r: -r.requests_per_sec)
    for r in sorted_results:
        cfg = r.config
        print(f"    w={cfg['dirty_workers']}, t={cfg['dirty_threads']}: "
              f"{r.requests_per_sec:.1f} req/s, "
              f"p99={r.latency_ms.p99:.1f}ms")

    return results


def generate_report(results: list[BenchmarkResult], output_path: str = None):
    """Generate a summary report from benchmark results."""
    print("\n" + "=" * 70)
    print("BENCHMARK REPORT")
    print("=" * 70)

    for result in results:
        print(f"\n{result.scenario}")
        print("-" * 40)
        print(f"  Config: {json.dumps(result.config, indent=None)}")
        print(f"  Requests: {result.successful}/{result.total_requests} "
              f"({result.failed} failed)")
        print(f"  Duration: {result.duration_sec}s")
        print(f"  Throughput: {result.requests_per_sec:.1f} req/s")
        print(f"  Latency (ms):")
        print(f"    min: {result.latency_ms.min:.2f}")
        print(f"    p50: {result.latency_ms.p50:.2f}")
        print(f"    p95: {result.latency_ms.p95:.2f}")
        print(f"    p99: {result.latency_ms.p99:.2f}")
        print(f"    max: {result.latency_ms.max:.2f}")
        print(f"    mean: {result.latency_ms.mean:.2f} "
              f"(stddev: {result.latency_ms.stddev:.2f})")

        if result.errors:
            print(f"  Errors (first {len(result.errors)}):")
            for err in result.errors[:3]:
                print(f"    - {err[:80]}")

    if output_path:
        output_data = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "results": [r.to_dict() for r in results],
        }
        with open(output_path, 'w') as f:
            json.dump(output_data, f, indent=2)
        print(f"\nResults saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Benchmark the gunicorn dirty pool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Mode selection
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument('--quick', action='store_true',
                            help='Run quick smoke test')
    mode_group.add_argument('--isolated', action='store_true',
                            help='Run isolated benchmark suite')
    mode_group.add_argument('--payload-tests', action='store_true',
                            help='Run payload size tests')
    mode_group.add_argument('--config-sweep', action='store_true',
                            help='Sweep through configurations')
    mode_group.add_argument('--integrated', action='store_true',
                            help='Run integrated HTTP benchmarks')

    # Configuration
    parser.add_argument('--workers', type=int, default=2,
                        help='Number of dirty workers (default: 2)')
    parser.add_argument('--threads', type=int, default=1,
                        help='Threads per dirty worker (default: 1)')
    parser.add_argument('--duration', type=int, default=10,
                        help='Task duration in ms for custom run')
    parser.add_argument('--concurrency', type=int, default=10,
                        help='Number of concurrent clients')
    parser.add_argument('--requests', type=int, default=1000,
                        help='Total requests to make')

    # Integration mode options
    parser.add_argument('--url', default='http://127.0.0.1:8000',
                        help='Server URL for integrated tests')

    # Output
    parser.add_argument('--output', '-o',
                        help='Output JSON file for results')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose output')

    args = parser.parse_args()

    results = []

    try:
        if args.quick:
            results = run_quick_test(verbose=args.verbose)
        elif args.isolated:
            results = run_isolated_suite(
                workers=args.workers,
                threads=args.threads,
                verbose=args.verbose,
            )
        elif args.payload_tests:
            results = run_payload_suite(
                workers=args.workers,
                threads=args.threads,
                verbose=args.verbose,
            )
        elif args.config_sweep:
            results = run_config_sweep(verbose=args.verbose)
        elif args.integrated:
            bench = IntegratedBenchmark(url=args.url, verbose=args.verbose)
            tool = bench.check_dependencies()

            if tool == 'wrk':
                print(f"\nRunning integrated benchmarks with wrk...")
                bench.warmup()

                # Run basic scenarios
                scenarios = [
                    ("/sleep?duration=10", "sleep_10ms"),
                    ("/cpu?duration=100", "cpu_100ms"),
                    ("/mixed?sleep=50&cpu=50", "mixed_50_50"),
                ]

                for path, name in scenarios:
                    print(f"  Running {name}...")
                    metrics = bench.run_wrk(path, duration=10, connections=100)
                    print(f"    Requests/sec: {metrics.get('requests_per_sec', 'N/A')}")

                print("\nNote: For detailed results, use wrk directly:")
                print(f"  wrk -t4 -c100 -d30s --latency '{args.url}/sleep?duration=10'")
            else:
                print("\nUsing Python fallback (install wrk for better results)...")
                bench.warmup()

                latencies, errors = bench.run_python_benchmark(
                    "/sleep?duration=10",
                    total_requests=args.requests,
                    concurrency=args.concurrency,
                )

                result = BenchmarkResult(
                    scenario="integrated_sleep",
                    config={"url": args.url, "concurrency": args.concurrency},
                    total_requests=args.requests,
                    successful=len(latencies),
                    failed=len(errors),
                    errors=errors[:5],
                    duration_sec=sum(latencies) / 1000 / args.concurrency,
                    requests_per_sec=len(latencies) / (sum(latencies) / 1000 /
                                                        args.concurrency),
                    latency_ms=LatencyStats.from_samples(latencies),
                )
                results.append(result)

        else:
            # Default: run custom single benchmark
            print(f"\nRunning custom benchmark: "
                  f"duration={args.duration}ms, concurrency={args.concurrency}")

            bench = IsolatedBenchmark(
                dirty_workers=args.workers,
                dirty_threads=args.threads,
                verbose=args.verbose,
            )

            try:
                bench.start()
                bench.warmup()

                start_time = time.perf_counter()
                latencies, errors = bench.run_benchmark(
                    action="sleep_task",
                    args=(args.duration,),
                    total_requests=args.requests,
                    concurrency=args.concurrency,
                )
                duration = time.perf_counter() - start_time

                result = BenchmarkResult(
                    scenario="custom",
                    config={
                        "dirty_workers": args.workers,
                        "dirty_threads": args.threads,
                        "task_duration_ms": args.duration,
                        "concurrency": args.concurrency,
                    },
                    total_requests=args.requests,
                    successful=len(latencies),
                    failed=len(errors),
                    errors=errors[:10],
                    duration_sec=round(duration, 2),
                    requests_per_sec=round(len(latencies) / duration, 1),
                    latency_ms=LatencyStats.from_samples(latencies),
                )
                results.append(result)

            finally:
                bench.stop()

        # Generate report
        if results:
            generate_report(results, args.output)

    except KeyboardInterrupt:
        print("\nBenchmark interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
