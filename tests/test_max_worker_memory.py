#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for the --max-worker-memory feature."""

import os
from unittest import mock

import pytest

from gunicorn.config import Config


class TestMaxWorkerMemoryConfig:
    """Tests for the MaxWorkerMemory config setting."""

    def test_default_is_zero(self):
        cfg = Config()
        assert cfg.max_worker_memory == 0

    def test_set_via_config(self):
        cfg = Config()
        cfg.set("max_worker_memory", 100)
        assert cfg.max_worker_memory == 100

    def test_rejects_negative(self):
        cfg = Config()
        with pytest.raises(Exception):
            cfg.set("max_worker_memory", -1)


class TestGetRss:
    """Tests for Worker._get_rss()."""

    def test_returns_positive_int(self):
        from gunicorn.workers.base import Worker
        rss = Worker._get_rss()
        assert isinstance(rss, int)
        assert rss > 0

    def test_fallback_when_proc_unavailable(self):
        """_get_rss falls back to resource.getrusage when /proc is absent."""
        from gunicorn.workers.base import Worker
        with mock.patch("builtins.open", side_effect=OSError("no /proc")):
            rss = Worker._get_rss()
        assert isinstance(rss, int)
        assert rss > 0

    def test_fallback_on_malformed_proc(self):
        """_get_rss falls back gracefully if /proc content is malformed."""
        from gunicorn.workers.base import Worker
        fake_content = "Name:\tpython\nVmPeak:\t12345 kB\n"
        with mock.patch("builtins.open", mock.mock_open(read_data=fake_content)):
            rss = Worker._get_rss()
        assert isinstance(rss, int)
        assert rss > 0


class TestCheckMemoryUsage:
    """Tests for Worker._check_memory_usage()."""

    def _make_worker(self, max_worker_memory_mb=0):
        from gunicorn.workers.base import Worker

        cfg = Config()
        cfg.set("max_worker_memory", max_worker_memory_mb)

        with mock.patch("gunicorn.workers.base.WorkerTmp"):
            worker = Worker(
                age=1, ppid=os.getpid(), sockets=[],
                app=mock.Mock(), timeout=30, cfg=cfg, log=mock.Mock(),
            )
        return worker

    def test_disabled_when_zero(self):
        """No recycling when max_worker_memory is 0 (disabled)."""
        worker = self._make_worker(0)
        worker._check_memory_usage()
        assert worker.alive is True
        worker.log.warning.assert_not_called()

    def test_triggers_shutdown_when_exceeded(self):
        """Worker sets alive=False when RSS exceeds limit."""
        worker = self._make_worker(1)  # 1 MB — current process is larger
        worker._check_memory_usage()
        assert worker.alive is False
        worker.log.warning.assert_called_once()

    def test_no_shutdown_when_within_limit(self):
        """Worker stays alive when RSS is within limit."""
        worker = self._make_worker(999999)  # ~1 TB — way above current RSS
        worker._check_memory_usage()
        assert worker.alive is True
        worker.log.warning.assert_not_called()

    def test_log_message_contains_mb(self):
        """Warning log message reports memory in MB."""
        worker = self._make_worker(1)
        worker._check_memory_usage()
        msg = worker.log.warning.call_args[0][0]
        assert "MB" in msg


try:
    import tornado  # noqa: F401
    HAS_TORNADO = True
except ImportError:
    HAS_TORNADO = False


@pytest.mark.skipif(not HAS_TORNADO, reason="tornado not installed")
class TestTornadoWorkerMemoryCheck:
    """Tests that memory check is called in tornado worker."""

    def create_worker(self, max_worker_memory_mb=0):
        from gunicorn.workers import gtornado

        cfg = Config()
        cfg.set("workers", 1)
        cfg.set("max_worker_memory", max_worker_memory_mb)

        worker = gtornado.TornadoWorker(
            age=1,
            ppid=os.getpid(),
            sockets=[],
            app=mock.Mock(),
            timeout=30,
            cfg=cfg,
            log=mock.Mock(),
        )
        return worker

    def test_memory_check_called_on_handle_request(self):
        worker = self.create_worker()
        worker.nr = 0
        worker.alive = True
        with mock.patch.object(worker, "_check_memory_usage") as mock_check:
            worker.handle_request()
            mock_check.assert_called_once()

    def test_memory_limit_triggers_shutdown(self):
        worker = self.create_worker(max_worker_memory_mb=1)  # 1 MB
        worker.nr = 0
        worker.alive = True
        worker.handle_request()
        assert worker.alive is False
