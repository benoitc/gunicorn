#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for dirty app module."""

import pytest

from gunicorn.dirty.app import DirtyApp, load_dirty_app, load_dirty_apps
from gunicorn.dirty.errors import DirtyAppError, DirtyAppNotFoundError


class TestDirtyAppBase:
    """Tests for DirtyApp base class."""

    def test_base_class_methods_exist(self):
        """Test that base class has all required methods."""
        app = DirtyApp()
        assert hasattr(app, 'init')
        assert hasattr(app, '__call__')
        assert hasattr(app, 'close')
        assert callable(app.init)
        assert callable(app.close)

    def test_base_init_is_noop(self):
        """Test that base init does nothing."""
        app = DirtyApp()
        result = app.init()
        assert result is None

    def test_base_close_is_noop(self):
        """Test that base close does nothing."""
        app = DirtyApp()
        result = app.close()
        assert result is None

    def test_base_call_dispatches_to_method(self):
        """Test that base __call__ dispatches to methods."""
        class TestApp(DirtyApp):
            def my_action(self, x, y):
                return x + y

        app = TestApp()
        result = app("my_action", 1, 2)
        assert result == 3

    def test_base_call_unknown_action(self):
        """Test that __call__ raises for unknown action."""
        app = DirtyApp()
        with pytest.raises(ValueError) as exc_info:
            app("unknown_action")
        assert "Unknown action" in str(exc_info.value)

    def test_base_call_private_method_rejected(self):
        """Test that __call__ rejects private methods."""
        class TestApp(DirtyApp):
            def _private(self):
                return "secret"

        app = TestApp()
        with pytest.raises(ValueError) as exc_info:
            app("_private")
        assert "Unknown action" in str(exc_info.value)


class TestLoadDirtyApp:
    """Tests for load_dirty_app function."""

    def test_load_valid_app(self):
        """Test loading a valid dirty app."""
        app = load_dirty_app("tests.support_dirty_app:TestDirtyApp")
        assert app is not None
        assert hasattr(app, 'init')
        assert hasattr(app, 'close')

    def test_load_app_instance_not_initialized(self):
        """Test that loaded app is not auto-initialized."""
        app = load_dirty_app("tests.support_dirty_app:TestDirtyApp")
        assert app.initialized is False

    def test_load_app_init_can_be_called(self):
        """Test that init can be called on loaded app."""
        app = load_dirty_app("tests.support_dirty_app:TestDirtyApp")
        app.init()
        assert app.initialized is True
        assert app.data['init_called'] is True

    def test_load_app_call_works(self):
        """Test that loaded app can be called."""
        app = load_dirty_app("tests.support_dirty_app:TestDirtyApp")
        result = app("compute", 2, 3, operation="add")
        assert result == 5

        result = app("compute", 2, 3, operation="multiply")
        assert result == 6

    def test_load_app_close_works(self):
        """Test that close works on loaded app."""
        app = load_dirty_app("tests.support_dirty_app:TestDirtyApp")
        app("store", "key", "value")
        assert app.data.get("key") == "value"

        app.close()
        assert app.closed is True
        assert app.data == {}

    def test_load_missing_module(self):
        """Test loading from non-existent module."""
        with pytest.raises(DirtyAppNotFoundError) as exc_info:
            load_dirty_app("nonexistent.module:App")
        assert "not found" in str(exc_info.value).lower()

    def test_load_missing_class(self):
        """Test loading non-existent class from valid module."""
        with pytest.raises(DirtyAppNotFoundError):
            load_dirty_app("tests.support_dirty_app:NonExistentApp")

    def test_load_invalid_format_no_colon(self):
        """Test loading with invalid format (no colon)."""
        with pytest.raises(DirtyAppError) as exc_info:
            load_dirty_app("tests.support_dirty_app.TestDirtyApp")
        assert "Invalid import path format" in str(exc_info.value)

    def test_load_not_a_class(self):
        """Test loading something that's not a class."""
        with pytest.raises(DirtyAppError) as exc_info:
            load_dirty_app("tests.support_dirty_app:not_a_class")
        assert "not a class" in str(exc_info.value).lower()

    def test_load_broken_instantiation(self):
        """Test loading an app that fails during instantiation."""
        with pytest.raises(DirtyAppError) as exc_info:
            load_dirty_app("tests.support_dirty_app:BrokenInstantiationApp")
        assert "Failed to instantiate" in str(exc_info.value)


class TestLoadDirtyApps:
    """Tests for load_dirty_apps function."""

    def test_load_multiple_apps(self):
        """Test loading multiple apps."""
        apps = load_dirty_apps([
            "tests.support_dirty_app:TestDirtyApp",
        ])
        assert len(apps) == 1
        assert "tests.support_dirty_app:TestDirtyApp" in apps

    def test_load_empty_list(self):
        """Test loading with empty list."""
        apps = load_dirty_apps([])
        assert apps == {}

    def test_load_multiple_fails_on_first_error(self):
        """Test that loading stops on first error."""
        with pytest.raises(DirtyAppNotFoundError):
            load_dirty_apps([
                "tests.support_dirty_app:TestDirtyApp",
                "nonexistent:App",  # This should fail
            ])


class TestDirtyAppStateful:
    """Tests for stateful dirty app behavior."""

    def test_app_maintains_state(self):
        """Test that app maintains state between calls."""
        app = load_dirty_app("tests.support_dirty_app:TestDirtyApp")
        app.init()

        # Store some data
        app("store", "model", {"weights": [1, 2, 3]})
        app("store", "config", {"lr": 0.001})

        # Retrieve data
        model = app("retrieve", "model")
        config = app("retrieve", "config")

        assert model == {"weights": [1, 2, 3]}
        assert config == {"lr": 0.001}

    def test_app_error_handling(self):
        """Test that errors from app are raised properly."""
        app = load_dirty_app("tests.support_dirty_app:TestDirtyApp")

        with pytest.raises(ValueError) as exc_info:
            app("compute", 1, 2, operation="invalid")
        assert "Unknown operation" in str(exc_info.value)
