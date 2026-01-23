#!/usr/bin/env python3
"""
Benchmark script for gunicorn gthread worker.

This script runs various benchmarks against gunicorn and reports performance metrics.
Requires: gunicorn, requests (for warmup), and wrk or ab for load testing.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


BENCHMARK_DIR = Path(__file__).parent
APP_MODULE = "simple_app:application"


def check_dependencies():
    """Check if required tools are available."""
    # Check for wrk (preferred) or ab
    for tool in ['wrk', 'ab']:
        try:
            subprocess.run([tool, '--version'], capture_output=True, check=False)
            return tool
        except FileNotFoundError:
            continue
    print("Error: Neither 'wrk' nor 'ab' found. Install one of them.")
    print("  macOS: brew install wrk")
    print("  Linux: apt-get install wrk (or apache2-utils for ab)")
    sys.exit(1)


def start_gunicorn(worker_class, workers, threads, connections, bind, extra_args=None):
    """Start gunicorn server and return the process."""
    cmd = [
        sys.executable, '-m', 'gunicorn',
        '--worker-class', worker_class,
        '--workers', str(workers),
        '--threads', str(threads),
        '--worker-connections', str(connections),
        '--bind', bind,
        '--access-logfile', '-',
        '--error-logfile', '-',
        '--log-level', 'warning',
        APP_MODULE,
    ]
    if extra_args:
        cmd.extend(extra_args)

    env = os.environ.copy()
    env['PYTHONPATH'] = str(BENCHMARK_DIR.parent)

    proc = subprocess.Popen(
        cmd,
        cwd=BENCHMARK_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for server to be ready
    time.sleep(2)
    return proc


def stop_gunicorn(proc):
    """Stop the gunicorn server."""
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def run_wrk_benchmark(url, duration, threads, connections):
    """Run wrk benchmark and return results."""
    cmd = [
        'wrk',
        '-t', str(threads),
        '-c', str(connections),
        '-d', f'{duration}s',
        '--latency',
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return parse_wrk_output(result.stdout)


def run_ab_benchmark(url, requests, concurrency):
    """Run Apache Bench benchmark and return results."""
    cmd = [
        'ab',
        '-n', str(requests),
        '-c', str(concurrency),
        '-k',  # keepalive
        url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return parse_ab_output(result.stdout)


def parse_wrk_output(output):
    """Parse wrk output to extract metrics."""
    metrics = {}
    for line in output.split('\n'):
        if 'Requests/sec' in line:
            metrics['requests_per_sec'] = float(line.split(':')[1].strip())
        elif 'Transfer/sec' in line:
            metrics['transfer_per_sec'] = line.split(':')[1].strip()
        elif 'Latency' in line and 'Distribution' not in line:
            parts = line.split()
            if len(parts) >= 2:
                metrics['latency_avg'] = parts[1]
        elif '50%' in line:
            metrics['latency_p50'] = line.split()[1]
        elif '99%' in line:
            metrics['latency_p99'] = line.split()[1]
    return metrics


def parse_ab_output(output):
    """Parse ab output to extract metrics."""
    metrics = {}
    for line in output.split('\n'):
        if 'Requests per second' in line:
            metrics['requests_per_sec'] = float(line.split(':')[1].split()[0])
        elif 'Time per request' in line and 'mean' in line:
            metrics['latency_avg'] = line.split(':')[1].strip()
        elif 'Transfer rate' in line:
            metrics['transfer_per_sec'] = line.split(':')[1].strip()
    return metrics


def run_benchmark_suite(tool, bind_addr):
    """Run a suite of benchmarks."""
    results = {}

    # Test configurations
    configs = [
        {'name': 'simple', 'path': '/', 'connections': 100},
        {'name': 'simple_high_concurrency', 'path': '/', 'connections': 500},
        {'name': 'slow_io', 'path': '/slow', 'connections': 50},
        {'name': 'large_response', 'path': '/large', 'connections': 100},
    ]

    for config in configs:
        url = f'http://{bind_addr}{config["path"]}'
        print(f"  Running {config['name']}...")

        if tool == 'wrk':
            metrics = run_wrk_benchmark(
                url,
                duration=10,
                threads=4,
                connections=config['connections'],
            )
        else:
            metrics = run_ab_benchmark(
                url,
                requests=10000,
                concurrency=config['connections'],
            )

        results[config['name']] = metrics
        print(f"    Requests/sec: {metrics.get('requests_per_sec', 'N/A')}")

    return results


def main():
    parser = argparse.ArgumentParser(description='Benchmark gunicorn gthread worker')
    parser.add_argument('--workers', type=int, default=2, help='Number of workers')
    parser.add_argument('--threads', type=int, default=4, help='Threads per worker')
    parser.add_argument('--connections', type=int, default=1000, help='Worker connections')
    parser.add_argument('--bind', default='127.0.0.1:8000', help='Bind address')
    parser.add_argument('--compare', action='store_true', help='Compare sync vs gthread')
    parser.add_argument('--output', help='Output JSON file for results')
    args = parser.parse_args()

    tool = check_dependencies()
    print(f"Using benchmark tool: {tool}")

    all_results = {}

    if args.compare:
        # Compare sync and gthread workers
        for worker_class in ['sync', 'gthread']:
            print(f"\nBenchmarking {worker_class} worker...")
            proc = start_gunicorn(
                worker_class=worker_class,
                workers=args.workers,
                threads=args.threads,
                connections=args.connections,
                bind=args.bind,
            )
            try:
                all_results[worker_class] = run_benchmark_suite(tool, args.bind)
            finally:
                stop_gunicorn(proc)
    else:
        # Just benchmark gthread
        print("\nBenchmarking gthread worker...")
        proc = start_gunicorn(
            worker_class='gthread',
            workers=args.workers,
            threads=args.threads,
            connections=args.connections,
            bind=args.bind,
        )
        try:
            all_results['gthread'] = run_benchmark_suite(tool, args.bind)
        finally:
            stop_gunicorn(proc)

    # Print summary
    print("\n" + "=" * 60)
    print("BENCHMARK SUMMARY")
    print("=" * 60)
    for worker, results in all_results.items():
        print(f"\n{worker.upper()} Worker:")
        for test, metrics in results.items():
            rps = metrics.get('requests_per_sec', 'N/A')
            print(f"  {test}: {rps} req/s")

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(all_results, f, indent=2)
        print(f"\nResults saved to {args.output}")


if __name__ == '__main__':
    main()
