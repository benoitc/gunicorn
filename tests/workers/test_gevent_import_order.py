#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Test for gevent worker compatibility with concurrent.futures import order.

Issue: https://github.com/benoitc/gunicorn/issues/3482
Discussion: https://github.com/benoitc/gunicorn/discussions/3481
Gist: https://gist.github.com/markjm/9f724364619c519892e8111fe6520ca6

When using gevent workers, `concurrent.futures` must not be imported before
`gevent.monkey.patch_all()` is called. If it is, certain thread locks in
concurrent.futures will not be properly patched, leading to issues with
libraries like boto3 that use concurrent.futures internally.

In gunicorn v25, the import of gunicorn.arbiter triggered the import of
gunicorn.dirty, which imports concurrent.futures via asyncio. This happened
before user code (like a config file with monkey.patch_all()) could run.

The fix was to make the dirty module imports lazy - only importing when
dirty workers are actually being started (in spawn_dirty_arbiter()).
"""

import subprocess
import sys
import textwrap

import pytest

try:
    import gevent
    HAS_GEVENT = True
except ImportError:
    HAS_GEVENT = False

pytestmark = pytest.mark.skipif(not HAS_GEVENT, reason="gevent not installed")


class TestConcurrentFuturesImportOrder:
    """Test that concurrent.futures import timing doesn't break gevent patching."""

    def test_concurrent_futures_not_imported_by_arbiter(self):
        """Test that importing gunicorn.arbiter does NOT import concurrent.futures.

        The dirty module (which uses asyncio and concurrent.futures) is now
        imported lazily to avoid breaking gevent patching.
        See: https://github.com/benoitc/gunicorn/discussions/3481
        """
        # Run in a subprocess to ensure clean import state
        code = textwrap.dedent("""
            import sys

            # Verify concurrent.futures is not imported yet
            assert 'concurrent.futures' not in sys.modules, \
                "concurrent.futures should not be imported yet"

            # Import gunicorn.arbiter
            import gunicorn.arbiter

            # Check if concurrent.futures is now imported
            cf_imported = 'concurrent.futures' in sys.modules
            print(f"RESULT:concurrent_futures_imported={cf_imported}")
        """)

        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True
        )

        # Parse the result
        stdout = result.stdout.strip()
        assert "RESULT:concurrent_futures_imported=" in stdout, \
            f"Test script failed: stderr={result.stderr}"

        imported = stdout.split("RESULT:concurrent_futures_imported=")[1] == "True"

        # concurrent.futures should NOT be imported by gunicorn.arbiter
        # The dirty module is now imported lazily
        assert not imported, (
            "concurrent.futures should NOT be imported when gunicorn.arbiter is imported. "
            "The dirty module should be imported lazily."
        )

    def test_gevent_patch_after_concurrent_futures_import_leaves_unpatched_lock(self):
        """Test that patching after concurrent.futures import leaves locks unpatched.

        This reproduces the issue from the gist where the _global_shutdown_lock
        in concurrent.futures.thread is not properly patched if concurrent.futures
        is imported before monkey.patch_all().
        """
        # Run in a subprocess to ensure clean import state
        code = textwrap.dedent("""
            import sys

            # Simulate what happens with gunicorn v25:
            # concurrent.futures is imported BEFORE gevent patching
            import concurrent.futures
            from concurrent.futures import thread as futures_thread

            # Get a reference to the lock BEFORE patching
            lock_before_patch = futures_thread._global_shutdown_lock

            # Now apply gevent patching (simulating user's config file)
            from gevent import monkey
            monkey.patch_all()

            # Get the lock type AFTER patching
            from gevent.thread import LockType as GeventLockType

            # Check if the lock is a gevent lock
            is_gevent_lock = isinstance(lock_before_patch, GeventLockType)
            lock_type = type(lock_before_patch).__module__

            print(f"RESULT:is_gevent_lock={is_gevent_lock}")
            print(f"RESULT:lock_module={lock_type}")
        """)

        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True
        )

        stdout = result.stdout.strip()
        assert "RESULT:is_gevent_lock=" in stdout, \
            f"Test script failed: stderr={result.stderr}"

        # Parse results
        lines = stdout.split("\n")
        is_gevent_lock = None
        lock_module = None
        for line in lines:
            if line.startswith("RESULT:is_gevent_lock="):
                is_gevent_lock = line.split("=")[1] == "True"
            elif line.startswith("RESULT:lock_module="):
                lock_module = line.split("=")[1]

        # Document: when concurrent.futures is imported before patching,
        # the _global_shutdown_lock is NOT a gevent lock - this is the bug
        assert is_gevent_lock is False, (
            "Lock should NOT be a gevent lock when concurrent.futures "
            "was imported before patching. If this fails, gevent may have "
            "improved their patching."
        )
        assert lock_module == "_thread", (
            f"Lock module should be _thread (unpatched), got {lock_module}"
        )

    def test_gevent_patch_before_concurrent_futures_import_patches_lock(self):
        """Test that patching BEFORE concurrent.futures import works correctly.

        This shows the correct behavior: when monkey.patch_all() is called
        BEFORE importing concurrent.futures, the locks are properly patched.
        """
        # Run in a subprocess to ensure clean import state
        code = textwrap.dedent("""
            import sys

            # Apply gevent patching FIRST (correct order)
            from gevent import monkey
            monkey.patch_all()

            # Now import concurrent.futures
            import concurrent.futures
            from concurrent.futures import thread as futures_thread

            # Get a reference to the lock
            lock = futures_thread._global_shutdown_lock

            # Check if the lock is a gevent lock
            from gevent.thread import LockType as GeventLockType
            is_gevent_lock = isinstance(lock, GeventLockType)
            lock_type = type(lock).__module__

            print(f"RESULT:is_gevent_lock={is_gevent_lock}")
            print(f"RESULT:lock_module={lock_type}")
        """)

        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True
        )

        stdout = result.stdout.strip()
        assert "RESULT:is_gevent_lock=" in stdout, \
            f"Test script failed: stderr={result.stderr}"

        # Parse results
        lines = stdout.split("\n")
        is_gevent_lock = None
        lock_module = None
        for line in lines:
            if line.startswith("RESULT:is_gevent_lock="):
                is_gevent_lock = line.split("=")[1] == "True"
            elif line.startswith("RESULT:lock_module="):
                lock_module = line.split("=")[1]

        # When patching happens BEFORE import, locks are properly patched
        assert is_gevent_lock is True, (
            "Lock should be a gevent lock when patching happens before import"
        )
        assert lock_module == "gevent.thread", (
            f"Lock module should be gevent.thread, got {lock_module}"
        )

    def test_gunicorn_gevent_worker_patching_works(self):
        """Integration test verifying gevent patching works with gunicorn.

        This simulates what happens when:
        1. User starts gunicorn with gevent worker
        2. gunicorn.arbiter is imported (does NOT import concurrent.futures)
        3. User's config file runs with monkey.patch_all()
        4. concurrent.futures is imported later (after patching)

        The result: concurrent.futures locks ARE properly patched.
        """
        code = textwrap.dedent("""
            import sys

            # Step 1: User starts gunicorn - gunicorn.arbiter gets imported
            # With the lazy import fix, this does NOT import concurrent.futures
            import gunicorn.arbiter

            # Step 2: Verify concurrent.futures was NOT imported yet
            assert 'concurrent.futures' not in sys.modules, \
                "concurrent.futures should NOT have been imported by arbiter"

            # Step 3: Now user's config file runs with monkey.patch_all()
            # This happens BEFORE concurrent.futures is imported - correct order!
            from gevent import monkey
            monkey.patch_all()

            # Step 4: Now import concurrent.futures (after patching)
            from concurrent.futures import thread as futures_thread
            lock = futures_thread._global_shutdown_lock

            from gevent.thread import LockType as GeventLockType
            is_gevent_lock = isinstance(lock, GeventLockType)

            print(f"RESULT:is_gevent_lock={is_gevent_lock}")
            print(f"RESULT:lock_type={type(lock)}")
        """)

        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True
        )

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        # Allow for the test to run even if gevent isn't available in subprocess
        if "ModuleNotFoundError" in stderr or "ImportError" in stderr:
            pytest.skip("gevent not available in subprocess")

        assert "RESULT:is_gevent_lock=" in stdout, \
            f"Test script failed: stdout={stdout}, stderr={stderr}"

        is_gevent_lock = "RESULT:is_gevent_lock=True" in stdout

        # The lock IS properly patched because:
        # 1. gunicorn.arbiter no longer imports concurrent.futures at module load
        # 2. monkey.patch_all() runs before concurrent.futures is imported
        # 3. concurrent.futures gets the patched threading primitives
        assert is_gevent_lock is True, (
            "Lock should be a gevent lock when gunicorn.arbiter is imported "
            "before monkey.patch_all() - the dirty module should be lazily imported."
        )

    def test_gevent_config_file_patching_scenario(self):
        """Test the exact scenario from the bug report gist.

        This reproduces the test case from:
        https://gist.github.com/markjm/9f724364619c519892e8111fe6520ca6

        The gist simulates a gunicorn config file that:
        1. Calls monkey.patch_all()
        2. Checks if locks in concurrent.futures are properly patched

        With the fix, both locks (before and after importing concurrent.futures)
        should be gevent locks because monkey.patch_all() runs before any
        concurrent.futures import.
        """
        code = textwrap.dedent("""
            import sys

            # Simulate gunicorn startup - import arbiter first
            # (this should NOT import concurrent.futures anymore)
            import gunicorn.arbiter

            # === This simulates a gunicorn config file (like echo.py from the gist) ===

            # Config file starts by patching
            from gevent import monkey
            monkey.patch_all()
            # print("[INFO] gevent.monkey.patch_all() called")

            # Now access concurrent.futures (after patching)
            from concurrent.futures import thread as futures_thread
            lock_after_patch = futures_thread._global_shutdown_lock

            # Also create a new lock to compare
            import threading
            new_lock = threading.Lock()

            from gevent.thread import LockType as GeventLockType
            import _thread

            # Check both locks
            after_is_gevent = isinstance(lock_after_patch, GeventLockType)
            after_module = type(lock_after_patch).__module__
            new_is_gevent = isinstance(new_lock, GeventLockType)
            new_module = type(new_lock).__module__

            # Print comparison table like the gist
            print("=== LOCK COMPARISON TABLE ===")
            print(f"CF Lock Type: {type(lock_after_patch)}")
            print(f"CF Lock Module: {after_module}")
            print(f"CF Is GeventLockType: {after_is_gevent}")
            print(f"New Lock Type: {type(new_lock)}")
            print(f"New Lock Module: {new_module}")
            print(f"New Is GeventLockType: {new_is_gevent}")

            # Results for parsing
            print(f"RESULT:cf_is_gevent={after_is_gevent}")
            print(f"RESULT:cf_module={after_module}")
            print(f"RESULT:new_is_gevent={new_is_gevent}")
        """)

        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True
        )

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if "ModuleNotFoundError" in stderr or "ImportError" in stderr:
            pytest.skip("gevent not available in subprocess")

        assert "RESULT:cf_is_gevent=" in stdout, \
            f"Test script failed: stdout={stdout}, stderr={stderr}"

        # Parse results
        cf_is_gevent = "RESULT:cf_is_gevent=True" in stdout
        new_is_gevent = "RESULT:new_is_gevent=True" in stdout

        # With the fix, BOTH locks should be gevent locks
        # This matches the expected v24 behavior from the gist
        assert cf_is_gevent is True, (
            "concurrent.futures lock should be a gevent lock. "
            "This indicates monkey.patch_all() ran before concurrent.futures was imported."
        )
        assert new_is_gevent is True, (
            "New threading.Lock should be a gevent lock after monkey.patch_all()"
        )
