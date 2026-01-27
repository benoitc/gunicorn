#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for dirty arbiter configuration settings."""

import pytest

from gunicorn.config import Config


class TestDirtyConfig:
    """Tests for dirty arbiter configuration settings."""

    def test_dirty_apps_default(self):
        """Test dirty_apps default is empty list."""
        cfg = Config()
        assert cfg.dirty_apps == []

    def test_dirty_apps_single(self):
        """Test dirty_apps with single app."""
        cfg = Config()
        cfg.set("dirty_apps", ["myapp.ml:MLApp"])
        assert cfg.dirty_apps == ["myapp.ml:MLApp"]

    def test_dirty_apps_multiple(self):
        """Test dirty_apps with multiple apps."""
        cfg = Config()
        cfg.set("dirty_apps", [
            "myapp.ml:MLApp",
            "myapp.images:ImageApp",
        ])
        assert len(cfg.dirty_apps) == 2
        assert "myapp.ml:MLApp" in cfg.dirty_apps
        assert "myapp.images:ImageApp" in cfg.dirty_apps

    def test_dirty_workers_default(self):
        """Test dirty_workers default is 0 (disabled)."""
        cfg = Config()
        assert cfg.dirty_workers == 0

    def test_dirty_workers_set(self):
        """Test setting dirty_workers."""
        cfg = Config()
        cfg.set("dirty_workers", 2)
        assert cfg.dirty_workers == 2

    def test_dirty_workers_invalid_negative(self):
        """Test dirty_workers rejects negative values."""
        cfg = Config()
        with pytest.raises(ValueError):
            cfg.set("dirty_workers", -1)

    def test_dirty_timeout_default(self):
        """Test dirty_timeout default is 300 seconds."""
        cfg = Config()
        assert cfg.dirty_timeout == 300

    def test_dirty_timeout_set(self):
        """Test setting dirty_timeout."""
        cfg = Config()
        cfg.set("dirty_timeout", 600)
        assert cfg.dirty_timeout == 600

    def test_dirty_timeout_zero_disables(self):
        """Test dirty_timeout can be set to 0 to disable."""
        cfg = Config()
        cfg.set("dirty_timeout", 0)
        assert cfg.dirty_timeout == 0

    def test_dirty_threads_default(self):
        """Test dirty_threads default is 1."""
        cfg = Config()
        assert cfg.dirty_threads == 1

    def test_dirty_threads_set(self):
        """Test setting dirty_threads."""
        cfg = Config()
        cfg.set("dirty_threads", 4)
        assert cfg.dirty_threads == 4

    def test_dirty_graceful_timeout_default(self):
        """Test dirty_graceful_timeout default is 30 seconds."""
        cfg = Config()
        assert cfg.dirty_graceful_timeout == 30

    def test_dirty_graceful_timeout_set(self):
        """Test setting dirty_graceful_timeout."""
        cfg = Config()
        cfg.set("dirty_graceful_timeout", 60)
        assert cfg.dirty_graceful_timeout == 60

    def test_all_dirty_settings_accessible(self):
        """Test all dirty settings are accessible."""
        cfg = Config()
        # These should not raise AttributeError
        _ = cfg.dirty_apps
        _ = cfg.dirty_workers
        _ = cfg.dirty_timeout
        _ = cfg.dirty_threads
        _ = cfg.dirty_graceful_timeout


class TestDirtyConfigCLI:
    """Tests for dirty arbiter CLI argument parsing."""

    def test_dirty_workers_cli(self):
        """Test --dirty-workers CLI argument."""
        cfg = Config()
        parser = cfg.parser()
        args = parser.parse_args(["--dirty-workers", "3"])
        assert args.dirty_workers == 3

    def test_dirty_timeout_cli(self):
        """Test --dirty-timeout CLI argument."""
        cfg = Config()
        parser = cfg.parser()
        args = parser.parse_args(["--dirty-timeout", "600"])
        assert args.dirty_timeout == 600

    def test_dirty_threads_cli(self):
        """Test --dirty-threads CLI argument."""
        cfg = Config()
        parser = cfg.parser()
        args = parser.parse_args(["--dirty-threads", "8"])
        assert args.dirty_threads == 8

    def test_dirty_graceful_timeout_cli(self):
        """Test --dirty-graceful-timeout CLI argument."""
        cfg = Config()
        parser = cfg.parser()
        args = parser.parse_args(["--dirty-graceful-timeout", "45"])
        assert args.dirty_graceful_timeout == 45

    def test_dirty_app_cli(self):
        """Test --dirty-app CLI argument (can be repeated)."""
        cfg = Config()
        parser = cfg.parser()
        args = parser.parse_args([
            "--dirty-app", "myapp.ml:MLApp",
            "--dirty-app", "myapp.images:ImageApp",
        ])
        assert args.dirty_apps == ["myapp.ml:MLApp", "myapp.images:ImageApp"]
