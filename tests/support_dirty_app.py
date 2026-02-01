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


class HeavyModelApp(DirtyApp):
    """A dirty app that simulates a heavy model requiring limited workers.

    Uses the workers class attribute to limit how many workers load this app.
    """
    workers = 2  # Only 2 workers should load this app

    def __init__(self):
        self.initialized = False
        self.closed = False
        self.model_data = None
        self.worker_id = None

    def init(self):
        import os
        self.initialized = True
        # Store the worker PID to verify which worker handled the request
        self.worker_id = os.getpid()
        # Simulate loading a heavy model
        self.model_data = {"loaded": True, "worker": self.worker_id}

    def predict(self, data):
        """Simulate model prediction."""
        return {
            "prediction": f"result_for_{data}",
            "worker_id": self.worker_id,
        }

    def get_worker_id(self):
        """Return the worker ID that loaded this app."""
        return self.worker_id

    def close(self):
        self.closed = True
        self.model_data = None


class LightweightApp(DirtyApp):
    """A lightweight app that should load on all workers."""

    def __init__(self):
        self.initialized = False
        self.closed = False
        self.worker_id = None

    def init(self):
        import os
        self.initialized = True
        self.worker_id = os.getpid()

    def ping(self):
        """Simple ping action."""
        return {"pong": True, "worker_id": self.worker_id}

    def get_worker_id(self):
        """Return the worker ID that loaded this app."""
        return self.worker_id

    def close(self):
        self.closed = True
