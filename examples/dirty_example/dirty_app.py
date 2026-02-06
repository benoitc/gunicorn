#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Example Dirty Application - Simulates ML Model Loading and Inference

This demonstrates how to create a DirtyApp that:
1. Loads "models" at startup (init)
2. Handles requests from HTTP workers (__call__)
3. Cleans up on shutdown (close)
"""

import time
import hashlib
from gunicorn.dirty.app import DirtyApp


class MLApp(DirtyApp):
    """
    Example dirty application that simulates ML model operations.

    In a real application, this would load actual ML models like:
    - PyTorch models
    - TensorFlow models
    - Scikit-learn models
    - LLM models (Hugging Face, etc.)
    """

    def __init__(self):
        self.models = {}
        self.load_count = 0
        self.inference_count = 0

    def init(self):
        """Called once when dirty worker starts."""
        print(f"[MLApp] Initializing... (pid: {__import__('os').getpid()})")
        # Simulate loading a default model (takes time)
        self._load_model("default")
        print(f"[MLApp] Initialization complete. Models loaded: {list(self.models.keys())}")

    def __call__(self, action, *args, **kwargs):
        """Dispatch to action methods."""
        method = getattr(self, action, None)
        if method is None or action.startswith('_'):
            raise ValueError(f"Unknown action: {action}")
        return method(*args, **kwargs)

    def _load_model(self, name):
        """Simulate loading a model (expensive operation)."""
        print(f"[MLApp] Loading model '{name}'...")
        # Simulate model loading time
        time.sleep(0.5)
        # Create a fake "model" object
        self.models[name] = {
            "name": name,
            "loaded_at": time.time(),
            "version": "1.0.0",
            "parameters": 1_000_000,  # Simulated parameter count
        }
        self.load_count += 1
        print(f"[MLApp] Model '{name}' loaded successfully")
        return self.models[name]

    def load_model(self, name):
        """Load a model into memory (called from HTTP workers)."""
        if name in self.models:
            return {"status": "already_loaded", "model": self.models[name]}

        model = self._load_model(name)
        return {"status": "loaded", "model": model}

    def list_models(self):
        """List all loaded models."""
        return {
            "models": list(self.models.keys()),
            "count": len(self.models),
            "total_loads": self.load_count,
            "total_inferences": self.inference_count,
        }

    def inference(self, model_name, input_data):
        """Run inference on a loaded model."""
        if model_name not in self.models:
            raise ValueError(f"Model not loaded: {model_name}")

        model = self.models[model_name]
        self.inference_count += 1

        # Simulate inference (compute a hash as a "prediction")
        time.sleep(0.1)  # Simulate computation time

        result = {
            "model": model_name,
            "input_hash": hashlib.md5(str(input_data).encode()).hexdigest()[:8],
            "prediction": f"result_{self.inference_count}",
            "confidence": 0.95,
            "inference_time_ms": 100,
        }
        return result

    def unload_model(self, name):
        """Unload a model from memory."""
        if name not in self.models:
            return {"status": "not_found", "name": name}

        del self.models[name]
        return {"status": "unloaded", "name": name}

    def close(self):
        """Cleanup on shutdown."""
        print(f"[MLApp] Shutting down. Total inferences: {self.inference_count}")
        self.models.clear()


class ComputeApp(DirtyApp):
    """
    Example dirty application for CPU-intensive computations.

    This demonstrates operations that would block HTTP workers
    but are fine in dirty workers.
    """

    def __init__(self):
        self.computation_count = 0

    def init(self):
        print(f"[ComputeApp] Initialized (pid: {__import__('os').getpid()})")

    def __call__(self, action, *args, **kwargs):
        method = getattr(self, action, None)
        if method is None or action.startswith('_'):
            raise ValueError(f"Unknown action: {action}")
        return method(*args, **kwargs)

    def fibonacci(self, n):
        """Compute fibonacci number (CPU-intensive for large n)."""
        self.computation_count += 1

        if n <= 1:
            return {"n": n, "result": n, "computation_id": self.computation_count}

        a, b = 0, 1
        for _ in range(2, n + 1):
            a, b = b, a + b

        return {"n": n, "result": b, "computation_id": self.computation_count}

    def prime_check(self, n):
        """Check if a number is prime (CPU-intensive for large n)."""
        self.computation_count += 1

        if n < 2:
            is_prime = False
        elif n == 2:
            is_prime = True
        elif n % 2 == 0:
            is_prime = False
        else:
            is_prime = True
            for i in range(3, int(n**0.5) + 1, 2):
                if n % i == 0:
                    is_prime = False
                    break

        return {"n": n, "is_prime": is_prime, "computation_id": self.computation_count}

    def stats(self):
        """Get computation statistics."""
        return {"total_computations": self.computation_count}

    def close(self):
        print(f"[ComputeApp] Shutting down. Total computations: {self.computation_count}")
