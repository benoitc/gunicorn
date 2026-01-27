#!/usr/bin/env python
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Benchmark suite for dirty worker streaming functionality.

This script benchmarks the streaming performance of dirty workers
to measure throughput, latency, and memory usage.

Usage:
    python benchmarks/dirty_streaming.py [OPTIONS]

Options:
    --quick     Run quick benchmarks only
    --full      Run full benchmark suite including stress tests
"""

import argparse
import asyncio
import gc
import json
import os
import struct
import sys
import time
import tracemalloc
from datetime import datetime
from unittest import mock

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gunicorn.dirty.protocol import (
    DirtyProtocol,
    make_request,
    make_chunk_message,
    make_end_message,
    make_response,
)
from gunicorn.dirty.worker import DirtyWorker
from gunicorn.dirty.arbiter import DirtyArbiter
from gunicorn.dirty.client import (
    DirtyClient,
    DirtyStreamIterator,
    DirtyAsyncStreamIterator,
)
from gunicorn.config import Config


class MockStreamWriter:
    """Mock StreamWriter that captures written messages."""

    def __init__(self):
        self.messages = []
        self._buffer = b""
        self.bytes_written = 0

    def write(self, data):
        self._buffer += data
        self.bytes_written += len(data)

    async def drain(self):
        while len(self._buffer) >= DirtyProtocol.HEADER_SIZE:
            length = struct.unpack(
                DirtyProtocol.HEADER_FORMAT,
                self._buffer[:DirtyProtocol.HEADER_SIZE]
            )[0]
            total_size = DirtyProtocol.HEADER_SIZE + length
            if len(self._buffer) >= total_size:
                msg_data = self._buffer[DirtyProtocol.HEADER_SIZE:total_size]
                self._buffer = self._buffer[total_size:]
                self.messages.append(DirtyProtocol.decode(msg_data))
            else:
                break

    def close(self):
        pass

    async def wait_closed(self):
        pass


class MockStreamReader:
    """Mock StreamReader that yields predefined messages."""

    def __init__(self, messages):
        self._data = b''
        for msg in messages:
            self._data += DirtyProtocol.encode(msg)
        self._pos = 0

    async def readexactly(self, n):
        if self._pos + n > len(self._data):
            raise asyncio.IncompleteReadError(self._data[self._pos:], n)
        result = self._data[self._pos:self._pos + n]
        self._pos += n
        return result


class MockLog:
    """Silent logger for benchmarks."""

    def debug(self, msg, *args):
        pass

    def info(self, msg, *args):
        pass

    def warning(self, msg, *args):
        pass

    def error(self, msg, *args):
        pass

    def close_on_exec(self):
        pass

    def reopen_files(self):
        pass


def create_worker():
    """Create a test worker for benchmarks."""
    cfg = Config()
    cfg.set("dirty_timeout", 300)
    log = MockLog()

    with mock.patch('gunicorn.dirty.worker.WorkerTmp'):
        worker = DirtyWorker(
            age=1,
            ppid=os.getpid(),
            app_paths=["benchmark:App"],
            cfg=cfg,
            log=log,
            socket_path="/tmp/benchmark.sock"
        )

    worker.apps = {}
    worker._executor = None
    worker.tmp = mock.Mock()

    return worker


def create_arbiter():
    """Create a test arbiter for benchmarks."""
    cfg = Config()
    cfg.set("dirty_timeout", 300)
    log = MockLog()

    arbiter = DirtyArbiter(cfg=cfg, log=log)
    arbiter.alive = True
    arbiter.workers = {1234: mock.Mock()}
    arbiter.worker_sockets = {1234: '/tmp/worker.sock'}

    return arbiter


class BenchmarkResults:
    """Store and display benchmark results."""

    def __init__(self):
        self.results = []

    def add(self, name, iterations, duration, chunks=None, bytes_total=None,
            memory_start=None, memory_end=None):
        throughput = iterations / duration if duration > 0 else 0
        result = {
            "name": name,
            "iterations": iterations,
            "duration_s": round(duration, 4),
            "throughput_per_s": round(throughput, 2),
        }
        if chunks:
            result["chunks_per_s"] = round(chunks / duration, 2)
        if bytes_total:
            result["mb_per_s"] = round(bytes_total / (1024 * 1024) / duration, 2)
        if memory_start is not None and memory_end is not None:
            result["memory_start_mb"] = round(memory_start / (1024 * 1024), 2)
            result["memory_end_mb"] = round(memory_end / (1024 * 1024), 2)
            result["memory_delta_mb"] = round((memory_end - memory_start) / (1024 * 1024), 2)
        self.results.append(result)

    def display(self):
        print("\n" + "=" * 70)
        print("BENCHMARK RESULTS")
        print("=" * 70)
        for result in self.results:
            print(f"\n{result['name']}")
            print("-" * 50)
            for key, value in result.items():
                if key != "name":
                    print(f"  {key}: {value}")
        print("\n" + "=" * 70)

    def save_json(self, filepath):
        with open(filepath, 'w') as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "results": self.results
            }, f, indent=2)
        print(f"Results saved to {filepath}")


async def benchmark_worker_streaming_throughput(results, chunk_size=1024, num_chunks=1000):
    """Benchmark worker streaming throughput with various chunk sizes."""
    worker = create_worker()
    writer = MockStreamWriter()

    chunk_data = "x" * chunk_size

    async def sync_gen():
        for _ in range(num_chunks):
            yield chunk_data

    async def mock_execute(app_path, action, args, kwargs):
        return sync_gen()

    gc.collect()
    tracemalloc.start()
    memory_start = tracemalloc.get_traced_memory()[0]

    start = time.perf_counter()

    with mock.patch.object(worker, 'execute', side_effect=mock_execute):
        request = make_request("bench-1", "benchmark:App", "stream")
        await worker.handle_request(request, writer)

    duration = time.perf_counter() - start
    memory_end = tracemalloc.get_traced_memory()[0]
    tracemalloc.stop()

    total_bytes = chunk_size * num_chunks

    results.add(
        f"Worker streaming ({chunk_size}B chunks, {num_chunks} chunks)",
        iterations=1,
        duration=duration,
        chunks=num_chunks,
        bytes_total=total_bytes,
        memory_start=memory_start,
        memory_end=memory_end
    )


async def benchmark_arbiter_forwarding(results, num_chunks=1000):
    """Benchmark arbiter message forwarding throughput."""
    arbiter = create_arbiter()

    messages = []
    for i in range(num_chunks):
        messages.append(make_chunk_message(f"bench-{i}", f"data-{i}"))
    messages.append(make_end_message(f"bench-{num_chunks}"))

    mock_reader = MockStreamReader(messages)

    async def mock_get_connection(pid):
        return mock_reader, MockStreamWriter()

    arbiter._get_worker_connection = mock_get_connection

    client_writer = MockStreamWriter()

    gc.collect()
    start = time.perf_counter()

    request = make_request("bench-forward", "benchmark:App", "stream")
    await arbiter._execute_on_worker(1234, request, client_writer)

    duration = time.perf_counter() - start

    results.add(
        f"Arbiter forwarding ({num_chunks} chunks)",
        iterations=1,
        duration=duration,
        chunks=num_chunks,
        bytes_total=client_writer.bytes_written
    )

    arbiter._cleanup_sync()


async def benchmark_streaming_latency(results, iterations=100):
    """Benchmark time-to-first-chunk and time-to-last-chunk."""
    worker = create_worker()

    first_chunk_times = []
    total_times = []

    for _ in range(iterations):
        writer = MockStreamWriter()

        async def gen_3_chunks():
            yield "first"
            yield "second"
            yield "third"

        async def mock_execute(app_path, action, args, kwargs):
            return gen_3_chunks()

        start = time.perf_counter()

        with mock.patch.object(worker, 'execute', side_effect=mock_execute):
            request = make_request("bench-latency", "benchmark:App", "stream")
            await worker.handle_request(request, writer)

            # Find time when first chunk was received
            if writer.messages:
                first_chunk_times.append(time.perf_counter() - start)

        total_times.append(time.perf_counter() - start)

    avg_first_chunk = sum(first_chunk_times) / len(first_chunk_times) if first_chunk_times else 0
    avg_total = sum(total_times) / len(total_times)

    print(f"\nLatency Results ({iterations} iterations):")
    print(f"  Avg time-to-first-chunk: {avg_first_chunk * 1000:.3f}ms")
    print(f"  Avg time-to-last-chunk: {avg_total * 1000:.3f}ms")

    results.add(
        f"Streaming latency ({iterations} iterations)",
        iterations=iterations,
        duration=sum(total_times),
        chunks=iterations * 3
    )


async def benchmark_concurrent_streams(results, num_streams=10, chunks_per_stream=100):
    """Benchmark multiple concurrent streams."""
    arbiter = create_arbiter()

    async def run_stream(stream_id):
        messages = []
        for i in range(chunks_per_stream):
            messages.append(make_chunk_message(f"stream-{stream_id}", f"chunk-{i}"))
        messages.append(make_end_message(f"stream-{stream_id}"))

        mock_reader = MockStreamReader(messages)
        async def mock_get_connection(pid):
            return mock_reader, MockStreamWriter()

        arbiter._get_worker_connection = mock_get_connection
        client_writer = MockStreamWriter()

        request = make_request(f"bench-concurrent-{stream_id}", "benchmark:App", "stream")
        await arbiter._execute_on_worker(1234, request, client_writer)
        return len(client_writer.messages)

    gc.collect()
    start = time.perf_counter()

    # Run streams concurrently
    tasks = [run_stream(i) for i in range(num_streams)]
    results_list = await asyncio.gather(*tasks)

    duration = time.perf_counter() - start

    total_chunks = sum(results_list)

    results.add(
        f"Concurrent streams ({num_streams} streams, {chunks_per_stream} chunks each)",
        iterations=num_streams,
        duration=duration,
        chunks=total_chunks
    )

    arbiter._cleanup_sync()


async def benchmark_memory_stability(results, iterations=10, chunks=1000):
    """Check memory stability over many iterations."""
    worker = create_worker()

    gc.collect()
    tracemalloc.start()
    memory_samples = [tracemalloc.get_traced_memory()[0]]

    for i in range(iterations):
        writer = MockStreamWriter()

        async def gen_chunks():
            for j in range(chunks):
                yield f"chunk-{j}"

        async def mock_execute(app_path, action, args, kwargs):
            return gen_chunks()

        with mock.patch.object(worker, 'execute', side_effect=mock_execute):
            request = make_request(f"bench-mem-{i}", "benchmark:App", "stream")
            await worker.handle_request(request, writer)

        gc.collect()
        memory_samples.append(tracemalloc.get_traced_memory()[0])

    tracemalloc.stop()

    memory_start = memory_samples[0]
    memory_end = memory_samples[-1]
    memory_max = max(memory_samples)

    print(f"\nMemory stability ({iterations} iterations of {chunks} chunks):")
    print(f"  Start: {memory_start / 1024 / 1024:.2f}MB")
    print(f"  End: {memory_end / 1024 / 1024:.2f}MB")
    print(f"  Max: {memory_max / 1024 / 1024:.2f}MB")
    print(f"  Delta: {(memory_end - memory_start) / 1024 / 1024:.2f}MB")

    results.add(
        f"Memory stability ({iterations} x {chunks} chunks)",
        iterations=iterations * chunks,
        duration=0.001,  # Use small non-zero value to avoid division by zero
        memory_start=memory_start,
        memory_end=memory_end
    )


class MockClientReader:
    """Mock async reader that simulates receiving streaming messages."""

    def __init__(self, num_chunks, chunk_data):
        self.num_chunks = num_chunks
        self.chunk_data = chunk_data
        self._chunk_idx = 0
        self._messages = []
        self._build_messages()
        self._pos = 0
        self._data = b''
        for msg in self._messages:
            self._data += DirtyProtocol.encode(msg)

    def _build_messages(self):
        for i in range(self.num_chunks):
            self._messages.append(make_chunk_message(f"bench-{i}", self.chunk_data))
        self._messages.append(make_end_message(f"bench-end"))

    async def readexactly(self, n):
        if self._pos + n > len(self._data):
            raise asyncio.IncompleteReadError(self._data[self._pos:], n)
        result = self._data[self._pos:self._pos + n]
        self._pos += n
        return result


class MockClientWriter:
    """Mock async writer for client connection."""

    def __init__(self):
        self._buffer = b""
        self._closed = False

    def write(self, data):
        self._buffer += data

    async def drain(self):
        pass

    def close(self):
        self._closed = True

    async def wait_closed(self):
        pass


async def benchmark_async_client_streaming(results, chunk_size=1024, num_chunks=1000):
    """
    Benchmark DirtyAsyncStreamIterator directly.

    Measures async iterator overhead vs raw message reading.
    """
    chunk_data = "x" * chunk_size

    # Create mock client with mock reader/writer
    client = DirtyClient("/tmp/benchmark.sock", timeout=30.0)
    client._reader = MockClientReader(num_chunks, chunk_data)
    client._writer = MockClientWriter()

    gc.collect()
    tracemalloc.start()
    memory_start = tracemalloc.get_traced_memory()[0]

    start = time.perf_counter()

    # Use the async stream iterator directly
    iterator = DirtyAsyncStreamIterator(client, "benchmark:App", "stream", (), {})
    iterator._started = True  # Skip the request sending
    iterator._request_id = "bench-async"
    iterator._deadline = time.perf_counter() + 300  # 5 min deadline
    iterator._last_chunk_time = time.perf_counter()

    chunks_received = 0
    bytes_received = 0
    async for chunk in iterator:
        chunks_received += 1
        bytes_received += len(chunk)

    duration = time.perf_counter() - start
    memory_end = tracemalloc.get_traced_memory()[0]
    tracemalloc.stop()

    results.add(
        f"Async client streaming ({chunk_size}B chunks, {num_chunks} chunks)",
        iterations=1,
        duration=duration,
        chunks=chunks_received,
        bytes_total=bytes_received,
        memory_start=memory_start,
        memory_end=memory_end
    )


async def benchmark_sync_client_streaming(results, chunk_size=1024, num_chunks=1000):
    """
    Benchmark DirtyStreamIterator directly (for comparison with async).

    Note: This runs the sync iterator within an async context for comparison.
    """
    chunk_data = "x" * chunk_size

    # Build raw message data
    messages_data = b''
    for i in range(num_chunks):
        msg = make_chunk_message(f"bench-{i}", chunk_data)
        messages_data += DirtyProtocol.encode(msg)
    messages_data += DirtyProtocol.encode(make_end_message("bench-end"))

    # Create a mock socket-like object
    class MockSocket:
        def __init__(self, data):
            self._data = data
            self._pos = 0
            self._timeout = None

        def recv(self, n, flags=0):
            if self._pos >= len(self._data):
                return b''
            result = self._data[self._pos:self._pos + n]
            self._pos += len(result)
            return result

        def settimeout(self, timeout):
            self._timeout = timeout

    # Create mock client
    client = DirtyClient("/tmp/benchmark.sock", timeout=30.0)
    client._sock = MockSocket(messages_data)

    gc.collect()
    tracemalloc.start()
    memory_start = tracemalloc.get_traced_memory()[0]

    start = time.perf_counter()

    # Use the sync stream iterator
    iterator = DirtyStreamIterator(client, "benchmark:App", "stream", (), {})
    iterator._started = True  # Skip the request sending
    iterator._request_id = "bench-sync"
    iterator._deadline = time.perf_counter() + 300  # 5 min deadline
    iterator._last_chunk_time = time.perf_counter()

    chunks_received = 0
    bytes_received = 0
    for chunk in iterator:
        chunks_received += 1
        bytes_received += len(chunk)

    duration = time.perf_counter() - start
    memory_end = tracemalloc.get_traced_memory()[0]
    tracemalloc.stop()

    results.add(
        f"Sync client streaming ({chunk_size}B chunks, {num_chunks} chunks)",
        iterations=1,
        duration=duration,
        chunks=chunks_received,
        bytes_total=bytes_received,
        memory_start=memory_start,
        memory_end=memory_end
    )


async def benchmark_async_vs_sync_client_streaming(results, chunk_size=1024, num_chunks=1000):
    """
    Compare stream() vs stream_async() performance with the same workload.
    """
    chunk_data = "x" * chunk_size

    # --- Sync test ---
    messages_data = b''
    for i in range(num_chunks):
        msg = make_chunk_message(f"bench-{i}", chunk_data)
        messages_data += DirtyProtocol.encode(msg)
    messages_data += DirtyProtocol.encode(make_end_message("bench-end"))

    class MockSocket:
        def __init__(self, data):
            self._data = data
            self._pos = 0
            self._timeout = None

        def recv(self, n, flags=0):
            if self._pos >= len(self._data):
                return b''
            result = self._data[self._pos:self._pos + n]
            self._pos += len(result)
            return result

        def settimeout(self, timeout):
            self._timeout = timeout

    sync_client = DirtyClient("/tmp/benchmark.sock", timeout=30.0)
    sync_client._sock = MockSocket(messages_data)

    gc.collect()
    sync_start = time.perf_counter()

    sync_iter = DirtyStreamIterator(sync_client, "benchmark:App", "stream", (), {})
    sync_iter._started = True
    sync_iter._request_id = "bench-sync"
    sync_iter._deadline = time.perf_counter() + 300  # 5 min deadline
    sync_iter._last_chunk_time = time.perf_counter()

    sync_chunks = 0
    for _ in sync_iter:
        sync_chunks += 1

    sync_duration = time.perf_counter() - sync_start

    # --- Async test ---
    async_client = DirtyClient("/tmp/benchmark.sock", timeout=30.0)
    async_client._reader = MockClientReader(num_chunks, chunk_data)
    async_client._writer = MockClientWriter()

    gc.collect()
    async_start = time.perf_counter()

    async_iter = DirtyAsyncStreamIterator(async_client, "benchmark:App", "stream", (), {})
    async_iter._started = True
    async_iter._request_id = "bench-async"
    async_iter._deadline = time.perf_counter() + 300  # 5 min deadline
    async_iter._last_chunk_time = time.perf_counter()

    async_chunks = 0
    async for _ in async_iter:
        async_chunks += 1

    async_duration = time.perf_counter() - async_start

    # Report comparison
    print(f"\nSync vs Async Client Streaming Comparison ({num_chunks} x {chunk_size}B chunks):")
    print(f"  Sync:  {sync_duration * 1000:.3f}ms ({sync_chunks} chunks)")
    print(f"  Async: {async_duration * 1000:.3f}ms ({async_chunks} chunks)")
    if sync_duration > 0:
        ratio = async_duration / sync_duration
        print(f"  Ratio (async/sync): {ratio:.3f}x")

    results.add(
        f"Sync client streaming comparison ({chunk_size}B, {num_chunks} chunks)",
        iterations=1,
        duration=sync_duration,
        chunks=sync_chunks,
        bytes_total=sync_chunks * chunk_size
    )

    results.add(
        f"Async client streaming comparison ({chunk_size}B, {num_chunks} chunks)",
        iterations=1,
        duration=async_duration,
        chunks=async_chunks,
        bytes_total=async_chunks * chunk_size
    )


async def run_quick_benchmarks():
    """Run quick benchmarks."""
    results = BenchmarkResults()

    print("Running quick benchmarks...")

    await benchmark_worker_streaming_throughput(results, chunk_size=64, num_chunks=1000)
    await benchmark_worker_streaming_throughput(results, chunk_size=1024, num_chunks=1000)
    await benchmark_arbiter_forwarding(results, num_chunks=1000)
    await benchmark_streaming_latency(results, iterations=50)

    # Async client streaming benchmarks
    await benchmark_async_client_streaming(results, chunk_size=1024, num_chunks=1000)
    await benchmark_async_vs_sync_client_streaming(results, chunk_size=1024, num_chunks=1000)

    return results


async def run_full_benchmarks():
    """Run full benchmark suite including stress tests."""
    results = BenchmarkResults()

    print("Running full benchmark suite...")

    # Throughput tests with different chunk sizes
    for chunk_size in [1, 64, 1024, 65536]:
        await benchmark_worker_streaming_throughput(
            results, chunk_size=chunk_size, num_chunks=1000
        )

    # Arbiter forwarding
    await benchmark_arbiter_forwarding(results, num_chunks=10000)

    # Latency
    await benchmark_streaming_latency(results, iterations=100)

    # Concurrent streams
    await benchmark_concurrent_streams(results, num_streams=10, chunks_per_stream=100)
    await benchmark_concurrent_streams(results, num_streams=50, chunks_per_stream=100)

    # Memory stability
    await benchmark_memory_stability(results, iterations=20, chunks=1000)

    # Async client streaming benchmarks
    for chunk_size in [64, 1024, 65536]:
        await benchmark_async_client_streaming(results, chunk_size=chunk_size, num_chunks=1000)
        await benchmark_sync_client_streaming(results, chunk_size=chunk_size, num_chunks=1000)

    # Comparison benchmark
    await benchmark_async_vs_sync_client_streaming(results, chunk_size=1024, num_chunks=5000)

    return results


def main():
    parser = argparse.ArgumentParser(description="Dirty streaming benchmarks")
    parser.add_argument("--quick", action="store_true", help="Run quick benchmarks only")
    parser.add_argument("--full", action="store_true", help="Run full benchmark suite")
    parser.add_argument("--output", "-o", help="Output JSON file path")
    args = parser.parse_args()

    if args.full:
        results = asyncio.run(run_full_benchmarks())
    else:
        results = asyncio.run(run_quick_benchmarks())

    results.display()

    if args.output:
        results.save_json(args.output)
    else:
        # Save to default location
        output_dir = os.path.dirname(os.path.abspath(__file__))
        results_dir = os.path.join(output_dir, "results")
        os.makedirs(results_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = os.path.join(results_dir, f"streaming_benchmark_{timestamp}.json")
        results.save_json(output_file)


if __name__ == "__main__":
    main()
