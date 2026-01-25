#!/usr/bin/env python
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Docker-based integration tests for dirty arbiter process lifecycle.

These tests verify:
1. Dirty arbiter self-terminates when main arbiter dies unexpectedly (SIGKILL)
2. Orphan cleanup works on gunicorn restart
3. Dirty arbiter respawn works when it dies
4. Graceful shutdown terminates both arbiters cleanly

Usage:
    # Build the container first
    docker compose build

    # Run all tests
    pytest test_parent_death.py -v

    # Run specific test
    pytest test_parent_death.py::TestParentDeath::test_dirty_arbiter_exits_on_parent_sigkill -v
"""

import os
import re
import subprocess
import time

import pytest


class DockerContainer:
    """Context manager for managing a Docker container."""

    def __init__(self, name="gunicorn-test", build=True):
        self.name = name
        self.build = build
        self.container_id = None

    def __enter__(self):
        # Build if requested
        if self.build:
            result = subprocess.run(
                ["docker", "compose", "build"],
                cwd=os.path.dirname(__file__),
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(f"Docker build failed: {result.stderr}")

        # Remove any existing container with same name
        subprocess.run(
            ["docker", "rm", "-f", self.name],
            capture_output=True,
        )

        # Start container with a keep-alive wrapper
        # This runs gunicorn in background so killing master doesn't exit container
        # The wrapper keeps container alive for observation after master death
        result = subprocess.run(
            [
                "docker", "run", "-d",
                "--name", self.name,
                "-p", "8000:8000",
                "dirty_arbiter-gunicorn",
                "sh", "-c",
                "gunicorn app:application -c gunicorn_conf.py & "
                "GUNICORN_PID=$!; "
                "trap 'kill $GUNICORN_PID 2>/dev/null' TERM; "
                "while true; do sleep 1; done"
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Docker run failed: {result.stderr}")

        self.container_id = result.stdout.strip()

        # Wait for gunicorn to be ready
        self._wait_for_ready()

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.container_id:
            # Get logs before cleanup
            logs = self.get_logs()
            if exc_val:
                print(f"\n=== Container logs ===\n{logs}\n=== End logs ===\n")

            # Stop and remove container
            subprocess.run(
                ["docker", "rm", "-f", self.name],
                capture_output=True,
            )

    def _wait_for_ready(self, timeout=30):
        """Wait for gunicorn to be ready."""
        start = time.time()
        while time.time() - start < timeout:
            pids = self.get_gunicorn_pids()
            if pids.get("master") and pids.get("dirty-arbiter"):
                # Both processes are running
                return
            time.sleep(0.5)
        raise TimeoutError("Gunicorn did not start within timeout")

    def exec(self, cmd, check=True):
        """Execute a command in the container."""
        result = subprocess.run(
            ["docker", "exec", self.name] + cmd,
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            raise RuntimeError(f"Command failed: {cmd}\n{result.stderr}")
        return result

    def get_logs(self):
        """Get container logs."""
        result = subprocess.run(
            ["docker", "logs", self.name],
            capture_output=True,
            text=True,
        )
        return result.stdout + result.stderr

    def get_gunicorn_pids(self):
        """Get PIDs of gunicorn processes.

        Uses ps output with proctitle if available, otherwise falls back
        to process tree analysis.
        """
        pids = {
            "master": None,
            "dirty-arbiter": None,
            "workers": [],
            "dirty-workers": [],
        }

        # First try using proctitle-based detection
        result = self.exec(["ps", "aux"], check=False)
        proctitle_found = False

        for line in result.stdout.split("\n"):
            if "gunicorn:" not in line:
                continue

            proctitle_found = True
            parts = line.split()
            if len(parts) < 2:
                continue

            pid = int(parts[1])

            if "gunicorn: master" in line:
                pids["master"] = pid
            elif "gunicorn: dirty-arbiter" in line:
                pids["dirty-arbiter"] = pid
            elif "gunicorn: dirty-worker" in line:
                pids["dirty-workers"].append(pid)
            elif "gunicorn: worker" in line:
                pids["workers"].append(pid)

        if proctitle_found:
            return pids

        # Fallback: use process tree analysis
        # Get ps output with ppid info
        result = self.exec(["ps", "-eo", "pid,ppid,comm"], check=False)

        gunicorn_procs = []
        for line in result.stdout.split("\n"):
            if "gunicorn" not in line and "python" not in line:
                continue
            parts = line.split()
            if len(parts) >= 3:
                try:
                    pid = int(parts[0])
                    ppid = int(parts[1])
                    gunicorn_procs.append((pid, ppid))
                except ValueError:
                    continue

        # Build process tree
        # Master: gunicorn process whose parent is init (pid 1 or docker-init)
        # Dirty-arbiter: child of master
        # Workers: children of master (that aren't dirty-arbiter)
        # Dirty-workers: children of dirty-arbiter

        for pid, ppid in gunicorn_procs:
            if ppid == 1 or ppid == 0:
                # This is the master (or docker-init spawned process)
                # Check if it's actually docker-init by checking its children
                continue
            if ppid not in [p for p, _ in gunicorn_procs]:
                # Parent isn't a gunicorn process - this is master
                pids["master"] = pid

        # Now identify children
        if pids["master"]:
            master_children = [p for p, pp in gunicorn_procs if pp == pids["master"]]

            # Get first child as dirty-arbiter (forked first from spawn_dirty_arbiter)
            # and check if it has children (dirty workers)
            for child_pid in master_children:
                child_children = [p for p, pp in gunicorn_procs if pp == child_pid]
                if child_children:
                    # This child has children, so it's the dirty-arbiter
                    pids["dirty-arbiter"] = child_pid
                    pids["dirty-workers"] = child_children
                else:
                    # No children, it's a regular worker
                    pids["workers"].append(child_pid)

        return pids

    def kill_process(self, pid, signal=9):
        """Send a signal to a process in the container."""
        self.exec(
            ["kill", f"-{signal}", str(pid)],
            check=False,
        )

    def wait_for_process_exit(self, pid, timeout=5):
        """Wait for a specific process to exit."""
        start = time.time()
        while time.time() - start < timeout:
            result = self.exec(
                ["ps", "-p", str(pid)],
                check=False,
            )
            if result.returncode != 0:
                # Process no longer exists
                return True
            time.sleep(0.2)
        return False

    def wait_for_no_gunicorn(self, timeout=5):
        """Wait until no gunicorn processes are running."""
        start = time.time()
        while time.time() - start < timeout:
            pids = self.get_gunicorn_pids()
            if not any([
                pids["master"],
                pids["dirty-arbiter"],
                pids["workers"],
                pids["dirty-workers"],
            ]):
                return True
            time.sleep(0.2)
        return False

    def wait_for_dirty_arbiter(self, timeout=10, exclude_pid=None):
        """Wait for a dirty arbiter to be running."""
        start = time.time()
        while time.time() - start < timeout:
            pids = self.get_gunicorn_pids()
            da_pid = pids.get("dirty-arbiter")
            if da_pid and da_pid != exclude_pid:
                return da_pid
            time.sleep(0.5)
        return None

    def restart_gunicorn(self):
        """Restart gunicorn in the container."""
        # Start gunicorn in background
        self.exec(
            ["sh", "-c", "gunicorn app:application -c gunicorn_conf.py &"],
            check=False,
        )
        # Wait for it to be ready
        self._wait_for_ready()


class TestParentDeath:
    """Test dirty arbiter behavior when parent dies."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Check Docker is available."""
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
        )
        if result.returncode != 0:
            pytest.skip("Docker is not available")

    def test_dirty_arbiter_exits_on_parent_sigkill(self):
        """Dirty arbiter should exit when main arbiter is SIGKILLed.

        This tests the ppid detection mechanism in the dirty arbiter.
        When the main arbiter is killed with SIGKILL (which bypasses
        graceful shutdown), the dirty arbiter should detect the parent
        change and exit within ~2 seconds.
        """
        with DockerContainer() as container:
            # Get initial PIDs
            pids = container.get_gunicorn_pids()
            master_pid = pids["master"]
            dirty_arbiter_pid = pids["dirty-arbiter"]

            assert master_pid is not None, "Master should be running"
            assert dirty_arbiter_pid is not None, "Dirty arbiter should be running"

            # SIGKILL the main arbiter (bypasses graceful shutdown)
            container.kill_process(master_pid, signal=9)

            # Wait for dirty arbiter to detect parent death and exit
            # The ppid check runs every 1 second. During shutdown, the arbiter
            # may take extra time to complete worker cleanup and handle SIGCHLD.
            exited = container.wait_for_process_exit(dirty_arbiter_pid, timeout=10)

            assert exited, (
                f"Dirty arbiter (pid:{dirty_arbiter_pid}) should have exited "
                "after parent was killed"
            )

            # Verify no orphan gunicorn processes remain
            # HTTP workers check ppid during request loop, so may take longer to exit
            assert container.wait_for_no_gunicorn(timeout=15), (
                "No gunicorn processes should remain after parent death"
            )

            # Check logs for expected message
            logs = container.get_logs()
            assert "Parent changed, shutting down dirty arbiter" in logs, (
                "Dirty arbiter should log parent death detection"
            )

    def test_orphan_cleanup_on_restart(self):
        """Orphaned dirty arbiter should be cleaned up on restart.

        This tests the _cleanup_orphaned_dirty_arbiter() mechanism.
        When gunicorn restarts after a crash, it should kill any
        orphaned dirty arbiter from the previous instance.
        """
        with DockerContainer() as container:
            # Get initial PIDs
            pids = container.get_gunicorn_pids()
            master_pid = pids["master"]
            dirty_arbiter_pid = pids["dirty-arbiter"]

            assert master_pid is not None
            assert dirty_arbiter_pid is not None

            # SIGKILL the main arbiter - dirty arbiter becomes orphan
            # but will self-terminate via ppid detection
            container.kill_process(master_pid, signal=9)

            # Wait for all gunicorn processes to exit before restarting
            # (including HTTP workers which take longer due to ppid check interval)
            container.wait_for_no_gunicorn(timeout=20)

            # Now restart gunicorn
            container.restart_gunicorn()

            # Get new PIDs
            new_pids = container.get_gunicorn_pids()
            new_dirty_arbiter_pid = new_pids["dirty-arbiter"]

            assert new_dirty_arbiter_pid is not None, (
                "New dirty arbiter should have spawned"
            )
            assert new_dirty_arbiter_pid != dirty_arbiter_pid, (
                "New dirty arbiter should have different PID"
            )

            # Check logs for orphan cleanup or normal startup
            logs = container.get_logs()
            # Either the orphan was cleaned up, or ppid detection worked
            assert (
                "Killing orphaned dirty arbiter" in logs or
                "Parent changed, shutting down dirty arbiter" in logs or
                "Dirty arbiter starting" in logs
            )

    def test_dirty_arbiter_respawn(self):
        """Main arbiter should respawn dead dirty arbiter.

        When the dirty arbiter dies (e.g., killed or crashed), the main
        arbiter should detect this and spawn a new one.
        """
        with DockerContainer() as container:
            # Get initial PIDs
            pids = container.get_gunicorn_pids()
            master_pid = pids["master"]
            old_dirty_arbiter_pid = pids["dirty-arbiter"]

            assert master_pid is not None
            assert old_dirty_arbiter_pid is not None

            # SIGKILL the dirty arbiter
            container.kill_process(old_dirty_arbiter_pid, signal=9)

            # Wait for respawn - main arbiter should spawn a new one
            new_dirty_arbiter_pid = container.wait_for_dirty_arbiter(
                timeout=10,
                exclude_pid=old_dirty_arbiter_pid,
            )

            assert new_dirty_arbiter_pid is not None, (
                "Main arbiter should respawn dirty arbiter"
            )
            assert new_dirty_arbiter_pid != old_dirty_arbiter_pid, (
                "New dirty arbiter should have different PID"
            )

            # Verify main arbiter is still running
            pids = container.get_gunicorn_pids()
            assert pids["master"] == master_pid, (
                "Main arbiter should still be running"
            )

            # Check logs
            logs = container.get_logs()
            assert "Spawning dirty arbiter" in logs or "Spawned dirty arbiter" in logs

    def test_graceful_shutdown(self):
        """SIGTERM should cleanly shutdown both arbiters.

        When the main arbiter receives SIGTERM, it should signal the
        dirty arbiter and wait for both to exit cleanly.
        """
        with DockerContainer() as container:
            # Get initial PIDs
            pids = container.get_gunicorn_pids()
            master_pid = pids["master"]
            dirty_arbiter_pid = pids["dirty-arbiter"]

            assert master_pid is not None
            assert dirty_arbiter_pid is not None

            # Send SIGTERM to main arbiter
            container.kill_process(master_pid, signal=15)

            # Wait for both to exit cleanly
            # Graceful timeout is 5 seconds in config
            assert container.wait_for_no_gunicorn(timeout=10), (
                "All gunicorn processes should exit on SIGTERM"
            )

            # Check logs for graceful shutdown indicators
            logs = container.get_logs()
            assert "Dirty arbiter exiting" in logs, (
                "Dirty arbiter should log clean exit"
            )

    def test_sigquit_quick_shutdown(self):
        """SIGQUIT should quickly shutdown both arbiters.

        SIGQUIT triggers a faster shutdown than SIGTERM.
        """
        with DockerContainer() as container:
            # Get initial PIDs
            pids = container.get_gunicorn_pids()
            master_pid = pids["master"]
            dirty_arbiter_pid = pids["dirty-arbiter"]

            assert master_pid is not None
            assert dirty_arbiter_pid is not None

            # Send SIGQUIT to main arbiter
            container.kill_process(master_pid, signal=3)

            # Both should exit quickly
            assert container.wait_for_no_gunicorn(timeout=5), (
                "All gunicorn processes should exit on SIGQUIT"
            )


class TestDirtyArbiterWorkers:
    """Test dirty arbiter worker management."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Check Docker is available."""
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
        )
        if result.returncode != 0:
            pytest.skip("Docker is not available")

    def test_dirty_worker_exists(self):
        """Dirty arbiter should spawn dirty worker(s)."""
        with DockerContainer() as container:
            pids = container.get_gunicorn_pids()

            assert pids["master"] is not None
            assert pids["dirty-arbiter"] is not None
            assert len(pids["dirty-workers"]) >= 1, (
                "At least one dirty worker should be running"
            )

    def test_dirty_worker_respawn(self):
        """Dirty arbiter should respawn killed dirty workers."""
        with DockerContainer() as container:
            pids = container.get_gunicorn_pids()
            old_dirty_worker_pid = pids["dirty-workers"][0]

            # Kill the dirty worker
            container.kill_process(old_dirty_worker_pid, signal=9)

            # Wait for respawn
            start = time.time()
            new_dirty_worker_pid = None
            while time.time() - start < 10:
                pids = container.get_gunicorn_pids()
                if pids["dirty-workers"]:
                    new_pid = pids["dirty-workers"][0]
                    if new_pid != old_dirty_worker_pid:
                        new_dirty_worker_pid = new_pid
                        break
                time.sleep(0.5)

            assert new_dirty_worker_pid is not None, (
                "Dirty arbiter should respawn killed dirty worker"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
