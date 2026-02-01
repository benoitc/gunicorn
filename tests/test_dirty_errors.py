#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for dirty errors module."""

import pytest

from gunicorn.dirty.errors import (
    DirtyError,
    DirtyNoWorkersAvailableError,
)


class TestDirtyNoWorkersAvailableError:
    """Tests for DirtyNoWorkersAvailableError exception."""

    def test_error_contains_app_path(self):
        """Error includes the app_path."""
        error = DirtyNoWorkersAvailableError("myapp:Model")
        assert error.app_path == "myapp:Model"
        assert "myapp:Model" in str(error)
        assert "No workers available" in str(error)

    def test_error_with_custom_message(self):
        """Error can have a custom message."""
        error = DirtyNoWorkersAvailableError(
            "myapp:Model",
            message="Custom: no workers for heavy model"
        )
        assert error.app_path == "myapp:Model"
        assert "Custom: no workers" in str(error)

    def test_error_serialization_roundtrip(self):
        """Error survives to_dict/from_dict cycle."""
        original = DirtyNoWorkersAvailableError("myapp.ml:HugeModel")

        # Serialize
        data = original.to_dict()
        assert data["error_type"] == "DirtyNoWorkersAvailableError"
        assert data["details"]["app_path"] == "myapp.ml:HugeModel"

        # Deserialize
        restored = DirtyError.from_dict(data)
        assert isinstance(restored, DirtyNoWorkersAvailableError)
        assert restored.app_path == "myapp.ml:HugeModel"
        assert "No workers available" in str(restored)

    def test_error_is_dirty_error_subclass(self):
        """DirtyNoWorkersAvailableError is a DirtyError subclass."""
        error = DirtyNoWorkersAvailableError("app:Class")
        assert isinstance(error, DirtyError)

    def test_web_app_can_catch_specific_error(self):
        """Web app can catch DirtyNoWorkersAvailableError specifically."""
        def simulate_execute():
            raise DirtyNoWorkersAvailableError("myapp:HeavyModel")

        # Catch specific error
        try:
            simulate_execute()
            assert False, "Should have raised"
        except DirtyNoWorkersAvailableError as e:
            assert e.app_path == "myapp:HeavyModel"

    def test_can_catch_as_base_error(self):
        """Can catch DirtyNoWorkersAvailableError as DirtyError."""
        def simulate_execute():
            raise DirtyNoWorkersAvailableError("myapp:Model")

        try:
            simulate_execute()
            assert False, "Should have raised"
        except DirtyError as e:
            # Should catch it as the base class
            assert hasattr(e, "app_path")
