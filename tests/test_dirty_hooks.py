#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for dirty arbiter hooks."""

import pytest

from gunicorn.config import Config


class TestDirtyHooksConfig:
    """Tests for dirty hook configuration settings."""

    def test_on_dirty_starting_default(self):
        """Test on_dirty_starting default is a callable."""
        cfg = Config()
        assert callable(cfg.on_dirty_starting)

    def test_on_dirty_starting_custom(self):
        """Test setting custom on_dirty_starting hook."""
        hook_calls = []

        def my_hook(arbiter):
            hook_calls.append(arbiter)

        cfg = Config()
        cfg.set("on_dirty_starting", my_hook)

        # Call the hook
        cfg.on_dirty_starting("test_arbiter")

        assert hook_calls == ["test_arbiter"]

    def test_dirty_post_fork_default(self):
        """Test dirty_post_fork default is a callable."""
        cfg = Config()
        assert callable(cfg.dirty_post_fork)

    def test_dirty_post_fork_custom(self):
        """Test setting custom dirty_post_fork hook."""
        hook_calls = []

        def my_hook(arbiter, worker):
            hook_calls.append((arbiter, worker))

        cfg = Config()
        cfg.set("dirty_post_fork", my_hook)

        # Call the hook
        cfg.dirty_post_fork("test_arbiter", "test_worker")

        assert hook_calls == [("test_arbiter", "test_worker")]

    def test_dirty_worker_init_default(self):
        """Test dirty_worker_init default is a callable."""
        cfg = Config()
        assert callable(cfg.dirty_worker_init)

    def test_dirty_worker_init_custom(self):
        """Test setting custom dirty_worker_init hook."""
        hook_calls = []

        def my_hook(worker):
            hook_calls.append(worker)

        cfg = Config()
        cfg.set("dirty_worker_init", my_hook)

        # Call the hook
        cfg.dirty_worker_init("test_worker")

        assert hook_calls == ["test_worker"]

    def test_dirty_worker_exit_default(self):
        """Test dirty_worker_exit default is a callable."""
        cfg = Config()
        assert callable(cfg.dirty_worker_exit)

    def test_dirty_worker_exit_custom(self):
        """Test setting custom dirty_worker_exit hook."""
        hook_calls = []

        def my_hook(arbiter, worker):
            hook_calls.append((arbiter, worker))

        cfg = Config()
        cfg.set("dirty_worker_exit", my_hook)

        # Call the hook
        cfg.dirty_worker_exit("test_arbiter", "test_worker")

        assert hook_calls == [("test_arbiter", "test_worker")]


class TestDirtyHooksValidation:
    """Tests for hook validation."""

    def test_on_dirty_starting_requires_callable(self):
        """Test that on_dirty_starting requires a callable."""
        cfg = Config()
        with pytest.raises(TypeError):
            cfg.set("on_dirty_starting", "not_a_callable")

    def test_dirty_post_fork_requires_callable(self):
        """Test that dirty_post_fork requires a callable."""
        cfg = Config()
        with pytest.raises(TypeError):
            cfg.set("dirty_post_fork", 123)
