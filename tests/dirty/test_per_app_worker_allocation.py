#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Integration tests for per-app worker allocation."""

import pytest

from gunicorn.config import Config
from gunicorn.dirty.arbiter import DirtyArbiter


class MockLog:
    """Mock logger for testing."""

    def __init__(self):
        self.messages = []

    def debug(self, msg, *args):
        self.messages.append(("debug", msg % args if args else msg))

    def info(self, msg, *args):
        self.messages.append(("info", msg % args if args else msg))

    def warning(self, msg, *args):
        self.messages.append(("warning", msg % args if args else msg))

    def error(self, msg, *args):
        self.messages.append(("error", msg % args if args else msg))

    def critical(self, msg, *args):
        self.messages.append(("critical", msg % args if args else msg))

    def exception(self, msg, *args):
        self.messages.append(("exception", msg % args if args else msg))

    def close_on_exec(self):
        pass

    def reopen_files(self):
        pass


class TestPerAppWorkerAllocation:
    """Integration tests for per-app worker allocation."""

    def test_heavy_app_loaded_on_limited_workers(self):
        """App with workers=2 only loaded on 2 of 4 workers."""
        cfg = Config()
        cfg.set("dirty_workers", 4)
        cfg.set("dirty_apps", [
            "tests.support_dirty_app:TestDirtyApp",      # unlimited
            "tests.support_dirty_app:SlowDirtyApp:2",    # limited to 2
        ])
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)

        # Simulate spawning 4 workers
        for i in range(4):
            apps = arbiter._get_apps_for_new_worker()
            arbiter._register_worker_apps(1000 + i, apps)

        # Check distribution
        unlimited_app = "tests.support_dirty_app:TestDirtyApp"
        limited_app = "tests.support_dirty_app:SlowDirtyApp"

        # Unlimited app should be on all 4 workers
        assert len(arbiter.app_worker_map[unlimited_app]) == 4

        # Limited app should only be on 2 workers
        assert len(arbiter.app_worker_map[limited_app]) == 2

        arbiter._cleanup_sync()

    def test_light_app_loaded_on_all_workers(self):
        """App with workers=None loaded on all workers."""
        cfg = Config()
        cfg.set("dirty_workers", 4)
        cfg.set("dirty_apps", [
            "tests.support_dirty_app:TestDirtyApp",
        ])
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)

        # Simulate spawning 4 workers
        for i in range(4):
            apps = arbiter._get_apps_for_new_worker()
            arbiter._register_worker_apps(1000 + i, apps)

        # App should be on all 4 workers
        app_path = "tests.support_dirty_app:TestDirtyApp"
        assert len(arbiter.app_worker_map[app_path]) == 4

        arbiter._cleanup_sync()

    def test_mixed_apps_correct_distribution(self):
        """Mix of limited and unlimited apps distributed correctly."""
        cfg = Config()
        cfg.set("dirty_workers", 4)
        cfg.set("dirty_apps", [
            "tests.support_dirty_app:TestDirtyApp",      # unlimited
            "tests.support_dirty_app:SlowDirtyApp:1",    # limited to 1
        ])
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)

        # Simulate spawning 4 workers
        for i in range(4):
            apps = arbiter._get_apps_for_new_worker()
            arbiter._register_worker_apps(1000 + i, apps)

        unlimited_app = "tests.support_dirty_app:TestDirtyApp"
        limited_app = "tests.support_dirty_app:SlowDirtyApp"

        # Unlimited app on all workers
        assert len(arbiter.app_worker_map[unlimited_app]) == 4

        # Limited app on only 1 worker
        assert len(arbiter.app_worker_map[limited_app]) == 1

        arbiter._cleanup_sync()

    @pytest.mark.asyncio
    async def test_request_routing_respects_allocation(self):
        """Requests only routed to workers with the target app."""
        cfg = Config()
        cfg.set("dirty_apps", [
            "tests.support_dirty_app:TestDirtyApp",
            "tests.support_dirty_app:SlowDirtyApp:1",
        ])
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)

        # Set up workers
        arbiter.workers[1001] = "worker1"
        arbiter.workers[1002] = "worker2"

        # Worker 1001 has both apps, worker 1002 has only TestDirtyApp
        arbiter._register_worker_apps(1001, [
            "tests.support_dirty_app:TestDirtyApp",
            "tests.support_dirty_app:SlowDirtyApp",
        ])
        arbiter._register_worker_apps(1002, [
            "tests.support_dirty_app:TestDirtyApp",
        ])

        # Request for SlowDirtyApp should only go to worker 1001
        worker = await arbiter._get_available_worker("tests.support_dirty_app:SlowDirtyApp")
        assert worker == 1001

        # Request for TestDirtyApp should go to either
        worker = await arbiter._get_available_worker("tests.support_dirty_app:TestDirtyApp")
        assert worker in [1001, 1002]

        arbiter._cleanup_sync()

    def test_worker_crash_app_reassigned_to_new_worker(self):
        """When worker dies, new worker gets the app it had."""
        cfg = Config()
        cfg.set("dirty_apps", [
            "tests.support_dirty_app:TestDirtyApp",
            "tests.support_dirty_app:SlowDirtyApp:1",
        ])
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.pid = 12345

        # Set up initial workers
        arbiter.workers[1001] = "worker1"
        arbiter.worker_sockets[1001] = "/tmp/fake1.sock"

        # Worker 1001 has both apps
        arbiter._register_worker_apps(1001, [
            "tests.support_dirty_app:TestDirtyApp",
            "tests.support_dirty_app:SlowDirtyApp",
        ])

        # Simulate worker crash
        arbiter._cleanup_worker(1001)

        # Apps should be queued for respawn
        assert len(arbiter._pending_respawns) == 1
        pending_apps = arbiter._pending_respawns[0]
        assert "tests.support_dirty_app:TestDirtyApp" in pending_apps
        assert "tests.support_dirty_app:SlowDirtyApp" in pending_apps

        arbiter._cleanup_sync()

    @pytest.mark.asyncio
    async def test_worker_crash_other_workers_still_serve_app(self):
        """When one of two workers dies, other still serves requests."""
        cfg = Config()
        cfg.set("dirty_apps", [
            "tests.support_dirty_app:TestDirtyApp",
        ])
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.pid = 12345

        # Set up two workers for the same app
        arbiter.workers[1001] = "worker1"
        arbiter.worker_sockets[1001] = "/tmp/fake1.sock"
        arbiter.workers[1002] = "worker2"
        arbiter.worker_sockets[1002] = "/tmp/fake2.sock"

        app_path = "tests.support_dirty_app:TestDirtyApp"
        arbiter._register_worker_apps(1001, [app_path])
        arbiter._register_worker_apps(1002, [app_path])

        # Both workers serve the app
        assert len(arbiter.app_worker_map[app_path]) == 2

        # Worker 1001 crashes
        arbiter._cleanup_worker(1001)

        # Worker 1002 still serves requests
        assert len(arbiter.app_worker_map[app_path]) == 1
        assert 1002 in arbiter.app_worker_map[app_path]

        worker = await arbiter._get_available_worker(app_path)
        assert worker == 1002

        arbiter._cleanup_sync()

    @pytest.mark.asyncio
    async def test_worker_crash_sole_worker_app_unavailable_until_respawn(self):
        """When sole worker for app dies, requests fail until respawn."""
        cfg = Config()
        cfg.set("dirty_apps", [
            "tests.support_dirty_app:SlowDirtyApp:1",
        ])
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)
        arbiter.pid = 12345

        # Only one worker for this app
        arbiter.workers[1001] = "worker1"
        arbiter.worker_sockets[1001] = "/tmp/fake1.sock"

        app_path = "tests.support_dirty_app:SlowDirtyApp"
        arbiter._register_worker_apps(1001, [app_path])

        # Worker crashes
        arbiter._cleanup_worker(1001)

        # No workers available for the app
        worker = await arbiter._get_available_worker(app_path)
        assert worker is None

        arbiter._cleanup_sync()

    def test_config_format_module_class_n(self):
        """Config 'mod:Class:2' correctly limits to 2 workers."""
        cfg = Config()
        cfg.set("dirty_apps", [
            "tests.support_dirty_app:TestDirtyApp:2",
        ])
        log = MockLog()

        arbiter = DirtyArbiter(cfg=cfg, log=log)

        # Check parsed spec
        app_path = "tests.support_dirty_app:TestDirtyApp"
        assert arbiter.app_specs[app_path]["worker_count"] == 2

        arbiter._cleanup_sync()
