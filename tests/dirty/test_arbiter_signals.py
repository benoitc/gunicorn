#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for dirty arbiter TTIN/TTOU signal handling."""

import signal
from unittest.mock import Mock

import pytest


class TestDirtyArbiterSignals:
    """Test TTIN/TTOU signal handling in DirtyArbiter."""

    @pytest.fixture
    def arbiter(self, tmp_path):
        """Create a DirtyArbiter for testing."""
        from gunicorn.dirty.arbiter import DirtyArbiter

        cfg = Mock()
        cfg.dirty_workers = 2
        cfg.dirty_apps = []
        cfg.dirty_timeout = 30
        cfg.dirty_graceful_timeout = 30
        cfg.on_dirty_starting = Mock()
        log = Mock()

        arbiter = DirtyArbiter(cfg, log, socket_path=str(tmp_path / "test.sock"))
        return arbiter

    def test_initial_num_workers_from_config(self, arbiter):
        """num_workers should be initialized from config."""
        assert arbiter.num_workers == 2

    def test_ttin_increases_num_workers(self, arbiter):
        """SIGTTIN should increase num_workers by 1."""
        assert arbiter.num_workers == 2
        arbiter._signal_handler(signal.SIGTTIN, None)
        assert arbiter.num_workers == 3

    def test_ttin_logs_info(self, arbiter):
        """SIGTTIN should log info about the change."""
        arbiter._signal_handler(signal.SIGTTIN, None)
        arbiter.log.info.assert_called()
        call_args = arbiter.log.info.call_args[0]
        assert "SIGTTIN" in call_args[0]
        assert "3" in str(call_args)

    def test_ttou_decreases_num_workers(self, arbiter):
        """SIGTTOU should decrease num_workers by 1."""
        arbiter.num_workers = 3
        arbiter._signal_handler(signal.SIGTTOU, None)
        assert arbiter.num_workers == 2

    def test_ttou_logs_info(self, arbiter):
        """SIGTTOU should log info about the change."""
        arbiter.num_workers = 3
        arbiter._signal_handler(signal.SIGTTOU, None)
        arbiter.log.info.assert_called()
        call_args = arbiter.log.info.call_args[0]
        assert "SIGTTOU" in call_args[0]
        assert "2" in str(call_args)

    def test_ttou_respects_minimum_one_worker(self, arbiter):
        """SIGTTOU should not go below 1 worker by default."""
        arbiter.num_workers = 1
        arbiter._signal_handler(signal.SIGTTOU, None)
        assert arbiter.num_workers == 1

    def test_ttou_logs_warning_at_minimum(self, arbiter):
        """SIGTTOU should log warning when at minimum."""
        arbiter.num_workers = 1
        arbiter._signal_handler(signal.SIGTTOU, None)
        arbiter.log.warning.assert_called()
        call_args = arbiter.log.warning.call_args[0]
        assert "Cannot decrease below" in call_args[0]

    def test_ttou_respects_app_minimum(self, arbiter):
        """SIGTTOU should not go below app-required minimum."""
        # App requires 3 workers
        arbiter.app_specs = {
            'myapp:HeavyTask': {
                'import_path': 'myapp:HeavyTask',
                'worker_count': 3,
                'original_spec': 'myapp:HeavyTask:3',
            }
        }
        arbiter.num_workers = 3

        # Should not decrease below 3
        arbiter._signal_handler(signal.SIGTTOU, None)
        assert arbiter.num_workers == 3
        arbiter.log.warning.assert_called()

    def test_ttou_with_unlimited_app(self, arbiter):
        """Apps with worker_count=None should not impose minimum."""
        arbiter.app_specs = {
            'myapp:UnlimitedTask': {
                'import_path': 'myapp:UnlimitedTask',
                'worker_count': None,
                'original_spec': 'myapp:UnlimitedTask',
            }
        }
        arbiter.num_workers = 2

        # Should decrease to 1 (default minimum)
        arbiter._signal_handler(signal.SIGTTOU, None)
        assert arbiter.num_workers == 1

    def test_multiple_ttin_signals(self, arbiter):
        """Multiple TTIN signals should keep incrementing."""
        assert arbiter.num_workers == 2
        arbiter._signal_handler(signal.SIGTTIN, None)
        arbiter._signal_handler(signal.SIGTTIN, None)
        arbiter._signal_handler(signal.SIGTTIN, None)
        assert arbiter.num_workers == 5

    def test_multiple_ttou_signals(self, arbiter):
        """Multiple TTOU signals should decrement until minimum."""
        arbiter.num_workers = 5
        arbiter._signal_handler(signal.SIGTTOU, None)
        arbiter._signal_handler(signal.SIGTTOU, None)
        arbiter._signal_handler(signal.SIGTTOU, None)
        arbiter._signal_handler(signal.SIGTTOU, None)
        # Should stop at 1
        assert arbiter.num_workers == 1


class TestGetMinimumWorkers:
    """Test _get_minimum_workers calculation."""

    @pytest.fixture
    def arbiter(self, tmp_path):
        """Create a DirtyArbiter for testing."""
        from gunicorn.dirty.arbiter import DirtyArbiter

        cfg = Mock()
        cfg.dirty_workers = 2
        cfg.dirty_apps = []
        cfg.dirty_timeout = 30
        cfg.dirty_graceful_timeout = 30
        cfg.on_dirty_starting = Mock()
        log = Mock()

        arbiter = DirtyArbiter(cfg, log, socket_path=str(tmp_path / "test.sock"))
        return arbiter

    def test_minimum_workers_no_apps(self, arbiter):
        """With no apps, minimum should be 1."""
        arbiter.app_specs = {}
        assert arbiter._get_minimum_workers() == 1

    def test_minimum_workers_single_app_with_limit(self, arbiter):
        """Single app with worker_count should set minimum."""
        arbiter.app_specs = {
            'app:Task': {
                'import_path': 'app:Task',
                'worker_count': 3,
                'original_spec': 'app:Task:3',
            }
        }
        assert arbiter._get_minimum_workers() == 3

    def test_minimum_workers_single_app_unlimited(self, arbiter):
        """Single app with worker_count=None should use default minimum."""
        arbiter.app_specs = {
            'app:Task': {
                'import_path': 'app:Task',
                'worker_count': None,
                'original_spec': 'app:Task',
            }
        }
        assert arbiter._get_minimum_workers() == 1

    def test_minimum_workers_multiple_apps_with_limits(self, arbiter):
        """Multiple apps should use the maximum worker_count."""
        arbiter.app_specs = {
            'app1:Task1': {
                'import_path': 'app1:Task1',
                'worker_count': 2,
                'original_spec': 'app1:Task1:2',
            },
            'app2:Task2': {
                'import_path': 'app2:Task2',
                'worker_count': 4,
                'original_spec': 'app2:Task2:4',
            },
            'app3:Task3': {
                'import_path': 'app3:Task3',
                'worker_count': 3,
                'original_spec': 'app3:Task3:3',
            },
        }
        # Maximum of (2, 4, 3) = 4
        assert arbiter._get_minimum_workers() == 4

    def test_minimum_workers_mixed_limited_and_unlimited(self, arbiter):
        """Mixed apps should use max of limited apps only."""
        arbiter.app_specs = {
            'app1:Task1': {
                'import_path': 'app1:Task1',
                'worker_count': 2,
                'original_spec': 'app1:Task1:2',
            },
            'app2:Task2': {
                'import_path': 'app2:Task2',
                'worker_count': None,
                'original_spec': 'app2:Task2',
            },
            'app3:Task3': {
                'import_path': 'app3:Task3',
                'worker_count': 4,
                'original_spec': 'app3:Task3:4',
            },
        }
        # Maximum of (2, 4) = 4, None is ignored
        assert arbiter._get_minimum_workers() == 4

    def test_minimum_workers_all_unlimited(self, arbiter):
        """All unlimited apps should use default minimum."""
        arbiter.app_specs = {
            'app1:Task1': {
                'import_path': 'app1:Task1',
                'worker_count': None,
                'original_spec': 'app1:Task1',
            },
            'app2:Task2': {
                'import_path': 'app2:Task2',
                'worker_count': None,
                'original_spec': 'app2:Task2',
            },
        }
        assert arbiter._get_minimum_workers() == 1
