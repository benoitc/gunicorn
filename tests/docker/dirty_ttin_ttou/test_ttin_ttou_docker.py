#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Docker integration tests for dirty arbiter TTIN/TTOU signals."""

import os
import subprocess
import time
from pathlib import Path

import pytest
import requests


pytestmark = [
    pytest.mark.docker,
    pytest.mark.integration,
]

# Directory containing this test file
TEST_DIR = Path(__file__).parent
COMPOSE_FILE = TEST_DIR / "docker-compose.yml"
BASE_URL = "http://localhost:18000"


@pytest.fixture(scope="module")
def docker_services():
    """Start Docker services for the test module."""
    # Start services
    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d", "--build"],
        check=True,
        cwd=TEST_DIR
    )

    # Wait for health
    for _ in range(30):
        try:
            resp = requests.get(f"{BASE_URL}/health", timeout=2)
            if resp.status_code == 200:
                break
        except requests.RequestException:
            pass
        time.sleep(1)
    else:
        # Print logs for debugging
        subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "logs"],
            cwd=TEST_DIR
        )
        pytest.fail("Services did not become healthy")

    yield

    # Cleanup
    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "down", "-v"],
        cwd=TEST_DIR
    )


def get_dirty_arbiter_pid():
    """Get the dirty arbiter PID from the container."""
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE),
         "exec", "-T", "gunicorn", "pgrep", "-f", "dirty-arbiter"],
        capture_output=True,
        text=True,
        cwd=TEST_DIR
    )
    pids = result.stdout.strip().split('\n')
    # Return the first PID (there should only be one dirty-arbiter)
    return int(pids[0]) if pids and pids[0] else None


def get_dirty_worker_count():
    """Get the current number of dirty workers."""
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE),
         "exec", "-T", "gunicorn", "pgrep", "-c", "-f", "dirty-worker"],
        capture_output=True,
        text=True,
        cwd=TEST_DIR
    )
    count = result.stdout.strip()
    return int(count) if count else 0


def send_signal_to_dirty_arbiter(sig):
    """Send a signal to the dirty arbiter."""
    pid = get_dirty_arbiter_pid()
    if pid is None:
        raise RuntimeError("Could not find dirty arbiter PID")
    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE),
         "exec", "-T", "gunicorn", "kill", f"-{sig}", str(pid)],
        check=True,
        cwd=TEST_DIR
    )


class TestTTINSignal:
    """Test SIGTTIN increases dirty workers."""

    def test_ttin_increases_workers(self, docker_services):
        """TTIN should spawn additional dirty worker."""
        initial_count = get_dirty_worker_count()
        assert initial_count == 3, f"Expected 3 initial workers, got {initial_count}"

        send_signal_to_dirty_arbiter("TTIN")
        time.sleep(2)  # Wait for worker to spawn

        new_count = get_dirty_worker_count()
        assert new_count == 4, f"Expected 4 workers after TTIN, got {new_count}"

    def test_multiple_ttin_increases(self, docker_services):
        """Multiple TTIN signals should keep increasing workers."""
        # Get current count (may be 4 from previous test)
        current_count = get_dirty_worker_count()

        send_signal_to_dirty_arbiter("TTIN")
        time.sleep(2)

        new_count = get_dirty_worker_count()
        assert new_count == current_count + 1


class TestTTOUSignal:
    """Test SIGTTOU decreases dirty workers."""

    def test_ttou_decreases_workers(self, docker_services):
        """TTOU should kill a dirty worker."""
        # First make sure we have more than minimum
        send_signal_to_dirty_arbiter("TTIN")
        time.sleep(2)

        count_before = get_dirty_worker_count()
        send_signal_to_dirty_arbiter("TTOU")
        time.sleep(2)

        count_after = get_dirty_worker_count()
        assert count_after == count_before - 1

    def test_ttou_respects_minimum(self, docker_services):
        """TTOU should not go below app minimum (2 for LimitedTask)."""
        # Try to decrease multiple times
        for _ in range(10):
            send_signal_to_dirty_arbiter("TTOU")
            time.sleep(0.5)

        time.sleep(2)  # Wait for all signals to be processed

        # Should not go below 2 (LimitedTask.workers = 2)
        final_count = get_dirty_worker_count()
        assert final_count >= 2, f"Worker count {final_count} is below minimum of 2"


class TestUnlimitedApps:
    """Test apps with worker_count=None work correctly."""

    def test_unlimited_app_works(self, docker_services):
        """UnlimitedTask should work."""
        resp = requests.get(f"{BASE_URL}/unlimited", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert data["task"] == "unlimited"

    def test_limited_app_works(self, docker_services):
        """LimitedTask should work."""
        resp = requests.get(f"{BASE_URL}/limited", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert data["task"] == "limited"

    def test_apps_work_after_scaling(self, docker_services):
        """Both apps should work after scaling up and down."""
        # Scale up
        send_signal_to_dirty_arbiter("TTIN")
        time.sleep(2)

        # Test both apps
        resp = requests.get(f"{BASE_URL}/unlimited", timeout=10)
        assert resp.status_code == 200

        resp = requests.get(f"{BASE_URL}/limited", timeout=10)
        assert resp.status_code == 200

        # Scale down
        send_signal_to_dirty_arbiter("TTOU")
        time.sleep(2)

        # Test both apps again
        resp = requests.get(f"{BASE_URL}/unlimited", timeout=10)
        assert resp.status_code == 200

        resp = requests.get(f"{BASE_URL}/limited", timeout=10)
        assert resp.status_code == 200
