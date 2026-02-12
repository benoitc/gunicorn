#!/usr/bin/env python3
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Integration tests for stash (shared state) functionality.

These tests verify that stash works correctly across multiple dirty workers,
demonstrating that state is truly shared.

Run with Docker:
    docker-compose up --build
    docker-compose exec app python test_stash_integration.py
"""

import json
import os
import sys
import urllib.request
import urllib.error

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8000")


def request(path):
    """Make HTTP request and return JSON response."""
    url = f"{BASE_URL}{path}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": str(e), "code": e.code}
    except urllib.error.URLError as e:
        return {"error": str(e)}


def test_stash_shared_state():
    """Test that stash state is shared across workers."""
    print("\n=== Test: Stash Shared State ===")

    # Clear any existing state
    result = request("/session/clear")
    print(f"Clear: {result}")

    # Login a user
    result = request("/session/login?user_id=100&name=Alice")
    print(f"Login Alice: {result}")
    assert result.get("status") == "ok", f"Login failed: {result}"
    worker1 = result.get("session", {}).get("worker_pid")
    print(f"  -> Handled by worker: {worker1}")

    # Make multiple requests to potentially hit different workers
    # and verify they all see the same session
    workers_seen = set()
    for i in range(5):
        result = request("/session/get?user_id=100")
        worker = result.get("served_by_worker")
        workers_seen.add(worker)
        session = result.get("session")
        assert session is not None, f"Session not found on request {i+1}"
        assert session.get("data", {}).get("name") == "Alice", f"Wrong session data"

    print(f"  -> Session visible from workers: {workers_seen}")
    print("PASSED: State is shared across workers")
    return True


def test_stash_counter():
    """Test that global counter increments correctly."""
    print("\n=== Test: Global Counter ===")

    # Clear state
    request("/session/clear")

    # Get initial stats
    result = request("/session/stats")
    initial = result.get("total_requests", 0)
    print(f"Initial count: {initial}")

    # Make several requests
    for i in range(5):
        request(f"/session/login?user_id={i}&name=User{i}")

    # Check counter increased
    result = request("/session/stats")
    final = result.get("total_requests", 0)
    print(f"Final count: {final}")

    # Each login increments counter by 1
    assert final >= initial + 5, f"Counter didn't increment enough: {initial} -> {final}"
    print("PASSED: Global counter works across workers")
    return True


def test_stash_list_sessions():
    """Test listing all sessions."""
    print("\n=== Test: List Sessions ===")

    # Clear and create some sessions
    request("/session/clear")
    request("/session/login?user_id=1&name=Alice")
    request("/session/login?user_id=2&name=Bob")
    request("/session/login?user_id=3&name=Charlie")

    # List all sessions
    result = request("/session/list")
    sessions = result.get("sessions", [])
    count = result.get("count", 0)

    print(f"Sessions: {count}")
    for s in sessions:
        print(f"  - user:{s.get('user_id')} = {s.get('data', {}).get('name')}")

    assert count == 3, f"Expected 3 sessions, got {count}"
    print("PASSED: List sessions works")
    return True


def test_stash_logout():
    """Test session deletion."""
    print("\n=== Test: Logout (Delete) ===")

    # Clear and create a session
    request("/session/clear")
    request("/session/login?user_id=999&name=TestUser")

    # Verify it exists
    result = request("/session/get?user_id=999")
    assert result.get("session") is not None, "Session should exist"

    # Logout
    result = request("/session/logout?user_id=999")
    print(f"Logout: {result}")
    assert result.get("status") == "logged_out", f"Logout failed: {result}"

    # Verify it's gone
    result = request("/session/get?user_id=999")
    assert result.get("session") is None, "Session should be deleted"

    print("PASSED: Logout deletes session")
    return True


def test_multiple_workers_see_updates():
    """Test that updates from one worker are visible to others."""
    print("\n=== Test: Cross-Worker Updates ===")

    request("/session/clear")

    # Create sessions and track which workers handled them
    workers = {}
    for i in range(10):
        result = request(f"/session/login?user_id={i}&name=User{i}")
        worker = result.get("session", {}).get("worker_pid")
        workers[i] = worker

    unique_workers = set(workers.values())
    print(f"Sessions created by workers: {unique_workers}")

    # Now read all sessions and verify all workers can see all data
    result = request("/session/list")
    count = result.get("count", 0)
    served_by = result.get("served_by_worker")

    print(f"List returned {count} sessions, served by worker {served_by}")
    assert count == 10, f"Expected 10 sessions, got {count}"

    print("PASSED: All workers see all updates")
    return True


def main():
    """Run all tests."""
    print("=" * 60)
    print("Stash Integration Tests")
    print("=" * 60)

    # Check server is running
    try:
        result = request("/")
        if "error" in result and "Connection refused" in str(result.get("error", "")):
            print("ERROR: Server not running. Start with: docker-compose up")
            return 1
        if not result.get("dirty_enabled"):
            print("ERROR: Dirty workers not enabled")
            return 1
        print(f"Server running, dirty workers enabled")
    except Exception as e:
        print(f"ERROR: Cannot connect to server: {e}")
        return 1

    # Run tests
    tests = [
        test_stash_shared_state,
        test_stash_counter,
        test_stash_list_sessions,
        test_stash_logout,
        test_multiple_workers_see_updates,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except AssertionError as e:
            print(f"FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
