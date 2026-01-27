#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Benchmark DirtyApp for stress testing the dirty arbiter pool.

Provides configurable workloads for testing:
- Pure sleep (scheduling overhead)
- CPU-bound work (thread pool utilization)
- Mixed I/O + CPU (realistic workloads)
- Payload generation (serialization overhead)
"""

import time

from gunicorn.dirty import DirtyApp


class BenchmarkApp(DirtyApp):
    """
    Configurable benchmark app for stress testing.

    Provides various task types to test different aspects of the
    dirty pool performance.
    """

    def init(self):
        """Fast initialization - no heavy resources to load."""
        self.call_count = 0
        self.total_sleep_ms = 0
        self.total_cpu_ms = 0

    def sleep_task(self, duration_ms):
        """
        Pure sleep task - tests scheduling overhead.

        This simulates I/O-bound work like waiting for external APIs.
        The thread is blocked but not consuming CPU.

        Args:
            duration_ms: Sleep duration in milliseconds

        Returns:
            dict with sleep duration
        """
        self.call_count += 1
        self.total_sleep_ms += duration_ms
        time.sleep(duration_ms / 1000.0)
        return {"slept_ms": duration_ms}

    def cpu_task(self, duration_ms, intensity=1.0):
        """
        CPU-bound work - tests thread pool utilization.

        Performs actual computation to simulate CPU-intensive work
        like model inference or data processing.

        Args:
            duration_ms: Target duration in milliseconds
            intensity: Work intensity multiplier (1.0 = normal)

        Returns:
            dict with computed iterations and actual duration
        """
        self.call_count += 1
        start = time.perf_counter()
        target_end = start + (duration_ms / 1000.0)

        # Perform CPU work until target duration
        iterations = 0
        work_per_iteration = int(1000 * intensity)

        while time.perf_counter() < target_end:
            # Do some actual computation
            x = 0.0
            for i in range(work_per_iteration):
                x += i * 0.001
                x = x * 1.001 if x < 1000000 else x * 0.999
            iterations += 1

        actual_ms = (time.perf_counter() - start) * 1000
        self.total_cpu_ms += actual_ms

        return {
            "iterations": iterations,
            "target_ms": duration_ms,
            "actual_ms": round(actual_ms, 2),
            "intensity": intensity
        }

    def mixed_task(self, sleep_ms, cpu_ms, intensity=1.0):
        """
        Mixed I/O + CPU task - simulates realistic workloads.

        First performs I/O (sleep), then does CPU work. This is
        common in real apps: fetch data, then process it.

        Args:
            sleep_ms: I/O simulation duration in milliseconds
            cpu_ms: CPU work duration in milliseconds
            intensity: CPU work intensity multiplier

        Returns:
            dict with both sleep and CPU metrics
        """
        self.call_count += 1

        # I/O phase (sleep)
        time.sleep(sleep_ms / 1000.0)
        self.total_sleep_ms += sleep_ms

        # CPU phase
        start = time.perf_counter()
        target_end = start + (cpu_ms / 1000.0)

        iterations = 0
        work_per_iteration = int(1000 * intensity)

        while time.perf_counter() < target_end:
            x = 0.0
            for i in range(work_per_iteration):
                x += i * 0.001
                x = x * 1.001 if x < 1000000 else x * 0.999
            iterations += 1

        actual_cpu_ms = (time.perf_counter() - start) * 1000
        self.total_cpu_ms += actual_cpu_ms

        return {
            "sleep_ms": sleep_ms,
            "cpu_iterations": iterations,
            "target_cpu_ms": cpu_ms,
            "actual_cpu_ms": round(actual_cpu_ms, 2),
            "total_ms": round(sleep_ms + actual_cpu_ms, 2)
        }

    def payload_task(self, size_bytes, duration_ms=0):
        """
        Generate payload of specified size - tests serialization.

        Creates a deterministic payload to test JSON serialization
        overhead for different response sizes.

        Args:
            size_bytes: Target payload size in bytes
            duration_ms: Optional sleep before generating payload

        Returns:
            dict with 'data' field of specified size
        """
        self.call_count += 1

        if duration_ms > 0:
            time.sleep(duration_ms / 1000.0)
            self.total_sleep_ms += duration_ms

        # Generate payload - use a pattern that compresses differently
        # than pure repeated characters for more realistic testing
        pattern = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        repeats = (size_bytes // len(pattern)) + 1
        data = (pattern * repeats)[:size_bytes]

        return {
            "data": data,
            "size": len(data)
        }

    def echo_task(self, payload):
        """
        Echo back payload - tests round-trip serialization.

        Useful for testing request/response serialization together.

        Args:
            payload: Data to echo back

        Returns:
            dict with echoed payload and its size
        """
        self.call_count += 1

        # Calculate size based on type
        if isinstance(payload, str):
            size = len(payload)
        elif isinstance(payload, (dict, list)):
            import json
            size = len(json.dumps(payload))
        else:
            size = len(str(payload))

        return {
            "echoed_size": size,
            "payload": payload
        }

    def stats(self):
        """
        Return accumulated statistics.

        Returns:
            dict with call counts and totals
        """
        return {
            "call_count": self.call_count,
            "total_sleep_ms": self.total_sleep_ms,
            "total_cpu_ms": round(self.total_cpu_ms, 2)
        }

    def reset_stats(self):
        """Reset accumulated statistics."""
        self.call_count = 0
        self.total_sleep_ms = 0
        self.total_cpu_ms = 0
        return {"reset": True}

    def health(self):
        """Health check endpoint for warmup."""
        return {"status": "ok"}

    def close(self):
        """Cleanup on shutdown."""
        pass
