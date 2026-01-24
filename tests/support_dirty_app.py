#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Support module for dirty app tests."""

from gunicorn.dirty.app import DirtyApp


class TestDirtyApp(DirtyApp):
    """A simple dirty app for testing."""

    def __init__(self):
        self.initialized = False
        self.closed = False
        self.data = {}

    def init(self):
        self.initialized = True
        self.data['init_called'] = True

    def store(self, key, value):
        self.data[key] = value
        return {"stored": True, "key": key}

    def retrieve(self, key):
        return self.data.get(key)

    def compute(self, a, b, operation="add"):
        if operation == "add":
            return a + b
        elif operation == "multiply":
            return a * b
        else:
            raise ValueError(f"Unknown operation: {operation}")

    def close(self):
        self.closed = True
        self.data.clear()


class BrokenInitApp(DirtyApp):
    """A dirty app that fails during init."""

    def init(self):
        raise RuntimeError("Init failed!")


class BrokenInstantiationApp(DirtyApp):
    """A dirty app that fails during instantiation."""

    def __init__(self):
        raise RuntimeError("Cannot instantiate!")


class NotAClass:
    """Not a class, just an instance for testing."""
    pass


not_a_class = NotAClass()


class MissingCallApp:
    """An invalid dirty app missing __call__."""

    def init(self):
        pass

    def close(self):
        pass


class SlowDirtyApp(DirtyApp):
    """A dirty app with slow methods for timeout testing."""

    def __init__(self):
        self.initialized = False
        self.closed = False

    def init(self):
        self.initialized = True

    def slow_action(self, delay=1.0):
        """An action that takes time to complete."""
        import time
        time.sleep(delay)
        return {"delayed": True, "duration": delay}

    def fast_action(self):
        """A fast action for comparison."""
        return {"fast": True}

    def close(self):
        self.closed = True
