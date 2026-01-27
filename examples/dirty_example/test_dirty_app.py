#!/usr/bin/env python
"""
Test script to demonstrate Dirty App functionality directly.

This tests the dirty app without running the full gunicorn server.

Run with:
    python examples/dirty_example/test_dirty_app.py
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from examples.dirty_example.dirty_app import MLApp, ComputeApp


def test_ml_app():
    """Test the MLApp dirty application."""
    print("=" * 60)
    print("Testing MLApp")
    print("=" * 60)

    # Create and initialize the app
    app = MLApp()
    print("\n1. Initializing app (loads default model)...")
    app.init()

    # List models
    print("\n2. Listing models...")
    result = app("list_models")
    print(f"   Models: {result}")

    # Load another model
    print("\n3. Loading 'gpt-4' model...")
    result = app("load_model", "gpt-4")
    print(f"   Result: {result}")

    # List models again
    print("\n4. Listing models again...")
    result = app("list_models")
    print(f"   Models: {result}")

    # Run inference
    print("\n5. Running inference on 'default' model...")
    result = app("inference", "default", "Hello, world!")
    print(f"   Result: {result}")

    # Run more inferences
    print("\n6. Running more inferences...")
    for i in range(3):
        result = app("inference", "gpt-4", f"Input data {i}")
        print(f"   Inference {i+1}: {result['prediction']}")

    # Unload a model
    print("\n7. Unloading 'gpt-4' model...")
    result = app("unload_model", "gpt-4")
    print(f"   Result: {result}")

    # Final stats
    print("\n8. Final stats...")
    result = app("list_models")
    print(f"   {result}")

    # Close
    print("\n9. Closing app...")
    app.close()

    print("\n" + "=" * 60)
    print("MLApp test complete!")
    print("=" * 60)


def test_compute_app():
    """Test the ComputeApp dirty application."""
    print("\n" + "=" * 60)
    print("Testing ComputeApp")
    print("=" * 60)

    # Create and initialize
    app = ComputeApp()
    app.init()

    # Fibonacci
    print("\n1. Computing Fibonacci numbers...")
    for n in [10, 20, 30, 40]:
        result = app("fibonacci", n)
        print(f"   fib({n}) = {result['result']}")

    # Prime checks
    print("\n2. Checking prime numbers...")
    for n in [17, 100, 997, 1000]:
        result = app("prime_check", n)
        status = "is prime" if result['is_prime'] else "is NOT prime"
        print(f"   {n} {status}")

    # Stats
    print("\n3. Stats...")
    result = app("stats")
    print(f"   {result}")

    # Close
    app.close()

    print("\n" + "=" * 60)
    print("ComputeApp test complete!")
    print("=" * 60)


def test_error_handling():
    """Test error handling in dirty apps."""
    print("\n" + "=" * 60)
    print("Testing Error Handling")
    print("=" * 60)

    app = MLApp()
    app.init()

    # Try to run inference on non-existent model
    print("\n1. Trying inference on non-existent model...")
    try:
        app("inference", "nonexistent", "data")
    except ValueError as e:
        print(f"   Caught expected error: {e}")

    # Try unknown action
    print("\n2. Trying unknown action...")
    try:
        app("unknown_action")
    except ValueError as e:
        print(f"   Caught expected error: {e}")

    # Try private method
    print("\n3. Trying private method...")
    try:
        app("_load_model", "test")
    except ValueError as e:
        print(f"   Caught expected error: {e}")

    app.close()

    print("\n" + "=" * 60)
    print("Error handling test complete!")
    print("=" * 60)


if __name__ == "__main__":
    print("\n" + "#" * 60)
    print("# Dirty App Demonstration")
    print("#" * 60)

    test_ml_app()
    test_compute_app()
    test_error_handling()

    print("\n" + "#" * 60)
    print("# All tests passed!")
    print("#" * 60 + "\n")
