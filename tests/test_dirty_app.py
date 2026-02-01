#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for dirty app module."""

import pytest

from gunicorn.dirty.app import (
    DirtyApp,
    load_dirty_app,
    load_dirty_apps,
    parse_dirty_app_spec,
)
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


class TestDirtyAppWorkersAttribute:
    """Tests for DirtyApp workers class attribute."""

    def test_default_workers_is_none(self):
        """Base DirtyApp has workers=None (all workers)."""
        assert DirtyApp.workers is None

    def test_subclass_can_set_workers(self):
        """Subclass can override workers=2."""

        class LimitedApp(DirtyApp):
            workers = 2

        assert LimitedApp.workers == 2

    def test_workers_inherited_by_default(self):
        """Subclass without workers attr inherits None."""

        class InheritedApp(DirtyApp):
            pass

        assert InheritedApp.workers is None

    def test_instance_has_workers_attribute(self):
        """Instance should have access to workers attribute."""
        app = DirtyApp()
        assert app.workers is None

        class LimitedApp(DirtyApp):
            workers = 3

        limited = LimitedApp()
        assert limited.workers == 3


class TestParseDirtyAppSpec:
    """Tests for parse_dirty_app_spec function."""

    def test_standard_format(self):
        """'mod:Class' returns ('mod:Class', None)."""
        import_path, count = parse_dirty_app_spec("mod:Class")
        assert import_path == "mod:Class"
        assert count is None

    def test_standard_format_with_dots(self):
        """'mod.sub.pkg:Class' returns ('mod.sub.pkg:Class', None)."""
        import_path, count = parse_dirty_app_spec("mod.sub.pkg:Class")
        assert import_path == "mod.sub.pkg:Class"
        assert count is None

    def test_with_worker_count(self):
        """'mod:Class:2' returns ('mod:Class', 2)."""
        import_path, count = parse_dirty_app_spec("mod:Class:2")
        assert import_path == "mod:Class"
        assert count == 2

    def test_worker_count_one(self):
        """'mod:Class:1' returns ('mod:Class', 1)."""
        import_path, count = parse_dirty_app_spec("mod:Class:1")
        assert import_path == "mod:Class"
        assert count == 1

    def test_worker_count_large(self):
        """'mod:Class:100' returns ('mod:Class', 100)."""
        import_path, count = parse_dirty_app_spec("mod:Class:100")
        assert import_path == "mod:Class"
        assert count == 100

    def test_worker_count_zero_raises(self):
        """'mod:Class:0' raises DirtyAppError."""
        with pytest.raises(DirtyAppError) as exc_info:
            parse_dirty_app_spec("mod:Class:0")
        assert "must be >= 1" in str(exc_info.value)

    def test_worker_count_negative_raises(self):
        """'mod:Class:-1' raises DirtyAppError."""
        with pytest.raises(DirtyAppError) as exc_info:
            parse_dirty_app_spec("mod:Class:-1")
        assert "must be >= 1" in str(exc_info.value)

    def test_non_numeric_raises(self):
        """'mod:Class:abc' raises DirtyAppError."""
        with pytest.raises(DirtyAppError) as exc_info:
            parse_dirty_app_spec("mod:Class:abc")
        assert "Expected integer" in str(exc_info.value)

    def test_no_colon_raises(self):
        """'mod.Class' (no colon) raises DirtyAppError."""
        with pytest.raises(DirtyAppError) as exc_info:
            parse_dirty_app_spec("mod.Class")
        assert "Invalid import path format" in str(exc_info.value)

    def test_too_many_colons_raises(self):
        """'mod:Class:2:extra' raises DirtyAppError."""
        with pytest.raises(DirtyAppError) as exc_info:
            parse_dirty_app_spec("mod:Class:2:extra")
        assert "Invalid import path format" in str(exc_info.value)

    def test_dotted_module_with_count(self):
        """'mod.sub:Class:2' handles dots correctly."""
        import_path, count = parse_dirty_app_spec("mod.sub:Class:2")
        assert import_path == "mod.sub:Class"
        assert count == 2


class TestGetAppWorkersAttribute:
    """Tests for get_app_workers_attribute function."""

    def test_get_workers_none_for_base_class(self):
        """Base DirtyApp returns workers=None."""
        from gunicorn.dirty.app import get_app_workers_attribute

        workers = get_app_workers_attribute("gunicorn.dirty.app:DirtyApp")
        assert workers is None

    def test_get_workers_from_class_attribute(self):
        """App with workers=2 class attribute returns 2."""
        from gunicorn.dirty.app import get_app_workers_attribute

        workers = get_app_workers_attribute("tests.support_dirty_app:HeavyModelApp")
        assert workers == 2

    def test_get_workers_none_for_inherited(self):
        """App without explicit workers attribute returns None."""
        from gunicorn.dirty.app import get_app_workers_attribute

        workers = get_app_workers_attribute("tests.support_dirty_app:TestDirtyApp")
        assert workers is None

    def test_get_workers_not_found_module(self):
        """Non-existent module raises DirtyAppNotFoundError."""
        from gunicorn.dirty.app import get_app_workers_attribute
        from gunicorn.dirty.errors import DirtyAppNotFoundError

        with pytest.raises(DirtyAppNotFoundError):
            get_app_workers_attribute("nonexistent.module:App")

    def test_get_workers_not_found_class(self):
        """Non-existent class raises DirtyAppNotFoundError."""
        from gunicorn.dirty.app import get_app_workers_attribute
        from gunicorn.dirty.errors import DirtyAppNotFoundError

        with pytest.raises(DirtyAppNotFoundError):
            get_app_workers_attribute("tests.support_dirty_app:NonExistentApp")

    def test_get_workers_invalid_format(self):
        """Invalid format raises DirtyAppError."""
        from gunicorn.dirty.app import get_app_workers_attribute
        from gunicorn.dirty.errors import DirtyAppError

        with pytest.raises(DirtyAppError) as exc_info:
            get_app_workers_attribute("invalid.format.no.colon")
        assert "Invalid import path format" in str(exc_info.value)
