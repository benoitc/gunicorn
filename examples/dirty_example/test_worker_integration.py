#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

#!/usr/bin/env python
"""
Integration test demonstrating DirtyWorker execution.

This test demonstrates how the DirtyWorker loads apps and handles requests
without actually forking processes (suitable for a quick test).

Run with:
    python examples/dirty_example/test_worker_integration.py
"""

import sys
import os
import asyncio
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from gunicorn.config import Config
from gunicorn.dirty.worker import DirtyWorker
from gunicorn.dirty.protocol import DirtyProtocol, make_request


class MockLog:
    """Mock logger for testing."""
    def debug(self, msg, *args): print(f"[DEBUG] {msg % args if args else msg}")
    def info(self, msg, *args): print(f"[INFO] {msg % args if args else msg}")
    def warning(self, msg, *args): print(f"[WARN] {msg % args if args else msg}")
    def error(self, msg, *args): print(f"[ERROR] {msg % args if args else msg}")
    def close_on_exec(self): pass
    def reopen_files(self): pass


async def test_worker_request_handling():
    """Test that a worker can load apps and handle requests."""
    print("=" * 60)
    print("Testing DirtyWorker Request Handling")
    print("=" * 60)

    # Create config and worker
    cfg = Config()
    log = MockLog()

    with tempfile.TemporaryDirectory() as tmpdir:
        socket_path = os.path.join(tmpdir, "worker.sock")

        worker = DirtyWorker(
            age=1,
            ppid=os.getpid(),
            app_paths=["examples.dirty_example.dirty_app:MLApp"],
            cfg=cfg,
            log=log,
            socket_path=socket_path
        )

        # Load apps (normally done in init_process after fork)
        print("\n1. Loading apps...")
        worker.load_apps()
        print(f"   Loaded apps: {list(worker.apps.keys())}")

        # Test execute directly
        print("\n2. Testing execute() - list_models...")
        result = await worker.execute(
            "examples.dirty_example.dirty_app:MLApp",
            "list_models",
            [],
            {}
        )
        print(f"   Result: {result}")

        # Test handle_request with a proper request message
        print("\n3. Testing handle_request() - load_model...")
        request = make_request(
            request_id="test-001",
            app_path="examples.dirty_example.dirty_app:MLApp",
            action="load_model",
            args=("gpt-4",),
            kwargs={}
        )
        response = await worker.handle_request(request)
        print(f"   Response type: {response['type']}")
        print(f"   Result: {response.get('result', response.get('error'))}")

        # Test inference
        print("\n4. Testing handle_request() - inference...")
        request = make_request(
            request_id="test-002",
            app_path="examples.dirty_example.dirty_app:MLApp",
            action="inference",
            args=("default", "Hello AI!"),
            kwargs={}
        )
        response = await worker.handle_request(request)
        print(f"   Response type: {response['type']}")
        print(f"   Result: {response.get('result', response.get('error'))}")

        # Test error handling
        print("\n5. Testing error handling - unknown action...")
        request = make_request(
            request_id="test-003",
            app_path="examples.dirty_example.dirty_app:MLApp",
            action="nonexistent_action",
            args=(),
            kwargs={}
        )
        response = await worker.handle_request(request)
        print(f"   Response type: {response['type']}")
        print(f"   Error: {response.get('error', {}).get('message')}")

        # Test app not found
        print("\n6. Testing error handling - app not found...")
        request = make_request(
            request_id="test-004",
            app_path="nonexistent:App",
            action="test",
            args=(),
            kwargs={}
        )
        response = await worker.handle_request(request)
        print(f"   Response type: {response['type']}")
        print(f"   Error type: {response.get('error', {}).get('error_type')}")

        # Cleanup
        print("\n7. Cleanup...")
        worker._cleanup()
        print("   Done!")


async def test_worker_with_compute_app():
    """Test worker with ComputeApp."""
    print("\n" + "=" * 60)
    print("Testing DirtyWorker with ComputeApp")
    print("=" * 60)

    cfg = Config()
    log = MockLog()

    with tempfile.TemporaryDirectory() as tmpdir:
        socket_path = os.path.join(tmpdir, "worker.sock")

        worker = DirtyWorker(
            age=1,
            ppid=os.getpid(),
            app_paths=["examples.dirty_example.dirty_app:ComputeApp"],
            cfg=cfg,
            log=log,
            socket_path=socket_path
        )

        worker.load_apps()

        # Fibonacci
        print("\n1. Computing Fibonacci(30)...")
        result = await worker.execute(
            "examples.dirty_example.dirty_app:ComputeApp",
            "fibonacci",
            [30],
            {}
        )
        print(f"   Result: {result}")

        # Prime check
        print("\n2. Checking if 997 is prime...")
        result = await worker.execute(
            "examples.dirty_example.dirty_app:ComputeApp",
            "prime_check",
            [997],
            {}
        )
        print(f"   Result: {result}")

        worker._cleanup()


async def test_multiple_apps():
    """Test worker with multiple apps loaded."""
    print("\n" + "=" * 60)
    print("Testing DirtyWorker with Multiple Apps")
    print("=" * 60)

    cfg = Config()
    log = MockLog()

    with tempfile.TemporaryDirectory() as tmpdir:
        socket_path = os.path.join(tmpdir, "worker.sock")

        worker = DirtyWorker(
            age=1,
            ppid=os.getpid(),
            app_paths=[
                "examples.dirty_example.dirty_app:MLApp",
                "examples.dirty_example.dirty_app:ComputeApp",
            ],
            cfg=cfg,
            log=log,
            socket_path=socket_path
        )

        worker.load_apps()
        print(f"\n1. Loaded {len(worker.apps)} apps: {list(worker.apps.keys())}")

        # Use both apps
        print("\n2. Using MLApp for inference...")
        result = await worker.execute(
            "examples.dirty_example.dirty_app:MLApp",
            "inference",
            ["default", "test input"],
            {}
        )
        print(f"   MLApp result: {result['prediction']}")

        print("\n3. Using ComputeApp for fibonacci...")
        result = await worker.execute(
            "examples.dirty_example.dirty_app:ComputeApp",
            "fibonacci",
            [15],
            {}
        )
        print(f"   ComputeApp result: fib(15) = {result['result']}")

        worker._cleanup()


if __name__ == "__main__":
    print("\n" + "#" * 60)
    print("# DirtyWorker Integration Demonstration")
    print("#" * 60)

    asyncio.run(test_worker_request_handling())
    asyncio.run(test_worker_with_compute_app())
    asyncio.run(test_multiple_apps())

    print("\n" + "#" * 60)
    print("# All integration tests passed!")
    print("#" * 60 + "\n")
