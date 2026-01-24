---
title: Dirty Arbiters
menu:
    guides:
        weight: 10
---

# Dirty Arbiters

Dirty Arbiters provide a separate process pool for executing long-running, blocking operations (AI model loading, heavy computation) without blocking HTTP workers. This feature is inspired by Erlang's dirty schedulers.

## Overview

Traditional Gunicorn workers are designed to handle HTTP requests quickly. Long-running operations like loading ML models or performing heavy computation can block these workers, reducing the server's ability to handle concurrent requests.

Dirty Arbiters solve this by providing:

- **Separate worker pool** - Completely separate from HTTP workers, can be killed/restarted independently
- **Stateful workers** - Loaded resources persist in dirty worker memory
- **Message-passing IPC** - Communication via Unix sockets with JSON serialization
- **Explicit API** - Clear `execute()` calls (no hidden IPC)
- **Asyncio-based** - Enables future streaming support and clean concurrent handling

## Architecture

```
                    +-------------------+
                    |   Main Arbiter    |
                    +--------+----------+
                             |
          +------------------+------------------+
          |                                     |
    +-----v-----+                        +------v------+
    | HTTP      |                        | Dirty       |
    | Workers   |<-- Unix Socket IPC --> | Arbiter     |
    +-----------+                        +------+------+
                                                |
                                    +-----------+-----------+
                                    |           |           |
                              +-----v---+ +-----v---+ +-----v---+
                              | Dirty   | | Dirty   | | Dirty   |
                              | Worker  | | Worker  | | Worker  |
                              +---------+ +---------+ +---------+
                                 ^             ^            ^
                                 |    All workers load all dirty apps
                                 +----[MLApp, ImageApp, ...]-----+
```

## Configuration

Add these settings to your Gunicorn configuration file or command line:

```python
# gunicorn.conf.py
dirty_apps = [
    "myapp.ml:MLApp",
    "myapp.images:ImageApp",
]
dirty_workers = 2          # Number of dirty workers
dirty_timeout = 300        # Task timeout in seconds
dirty_threads = 1          # Threads per worker
dirty_graceful_timeout = 30  # Shutdown timeout
```

Or via command line:

```bash
gunicorn myapp:app \
    --dirty-app myapp.ml:MLApp \
    --dirty-app myapp.images:ImageApp \
    --dirty-workers 2 \
    --dirty-timeout 300
```

### Configuration Options

| Setting | Default | Description |
|---------|---------|-------------|
| `dirty_apps` | `[]` | List of dirty app import paths |
| `dirty_workers` | `0` | Number of dirty workers (0 = disabled) |
| `dirty_timeout` | `300` | Task timeout in seconds |
| `dirty_threads` | `1` | Threads per dirty worker |
| `dirty_graceful_timeout` | `30` | Graceful shutdown timeout |

## Creating a Dirty App

Dirty apps inherit from `DirtyApp` and implement three methods:

```python
# myapp/dirty.py
from gunicorn.dirty import DirtyApp

class MLApp(DirtyApp):
    """Dirty application for ML workloads."""

    def __init__(self):
        self.models = {}

    def init(self):
        """Called once at dirty worker startup."""
        # Pre-load commonly used models
        self.models['default'] = self._load_model('base-model')

    def __call__(self, action, *args, **kwargs):
        """Dispatch to action methods."""
        method = getattr(self, action, None)
        if method is None:
            raise ValueError(f"Unknown action: {action}")
        return method(*args, **kwargs)

    def load_model(self, name):
        """Load a model into memory."""
        if name not in self.models:
            self.models[name] = self._load_model(name)
        return {"loaded": True, "name": name}

    def inference(self, model_name, input_text):
        """Run inference on loaded model."""
        model = self.models.get(model_name)
        if not model:
            raise ValueError(f"Model not loaded: {model_name}")
        return model.predict(input_text)

    def _load_model(self, name):
        import torch
        model = torch.load(f"models/{name}.pt")
        return model

    def close(self):
        """Cleanup on shutdown."""
        for model in self.models.values():
            del model
```

### DirtyApp Interface

| Method | Description |
|--------|-------------|
| `init()` | Called once when dirty worker starts, after instantiation. Load resources here. |
| `__call__(action, *args, **kwargs)` | Handle requests from HTTP workers. |
| `close()` | Called when dirty worker shuts down. Cleanup resources. |

### Initialization Sequence

When a dirty worker starts, initialization happens in this order:

1. **Fork** - Worker process is forked from dirty arbiter
2. **`dirty_post_fork(arbiter, worker)`** - Hook called immediately after fork
3. **App instantiation** - Each dirty app class is instantiated (`__init__`)
4. **`app.init()`** - Called for each app after instantiation (load models, resources)
5. **`dirty_worker_init(worker)`** - Hook called after ALL apps are initialized
6. **Run loop** - Worker starts accepting requests from HTTP workers

This means:

- Use `__init__` for basic setup (initialize empty containers, store config)
- Use `init()` for heavy loading (ML models, database connections, large files)
- The `dirty_worker_init` hook fires only after all apps have completed their `init()` calls

## Using from HTTP Workers

### Sync Workers (sync, gthread)

```python
from gunicorn.dirty import get_dirty_client

def my_view(request):
    client = get_dirty_client()

    # Load a model
    client.execute("myapp.ml:MLApp", "load_model", "gpt-4")

    # Run inference
    result = client.execute(
        "myapp.ml:MLApp",
        "inference",
        "gpt-4",
        input_text=request.data
    )
    return result
```

### Async Workers (ASGI)

```python
from gunicorn.dirty import get_dirty_client_async

async def my_view(request):
    client = await get_dirty_client_async()

    # Non-blocking execution
    await client.execute_async("myapp.ml:MLApp", "load_model", "gpt-4")

    result = await client.execute_async(
        "myapp.ml:MLApp",
        "inference",
        "gpt-4",
        input_text=request.data
    )
    return result
```

## Lifecycle Hooks

Dirty Arbiters provide hooks for customization:

```python
# gunicorn.conf.py

def on_dirty_starting(arbiter):
    """Called just before the dirty arbiter starts."""
    print("Dirty arbiter starting...")

def dirty_post_fork(arbiter, worker):
    """Called just after a dirty worker is forked."""
    print(f"Dirty worker {worker.pid} forked")

def dirty_worker_init(worker):
    """Called after a dirty worker initializes all apps."""
    print(f"Dirty worker {worker.pid} initialized")

def dirty_worker_exit(arbiter, worker):
    """Called when a dirty worker exits."""
    print(f"Dirty worker {worker.pid} exiting")

on_dirty_starting = on_dirty_starting
dirty_post_fork = dirty_post_fork
dirty_worker_init = dirty_worker_init
dirty_worker_exit = dirty_worker_exit
```

## Signal Handling

Dirty Arbiters respond to the following signals:

| Signal | Action |
|--------|--------|
| `SIGTERM` | Graceful shutdown |
| `SIGQUIT` | Immediate shutdown |
| `SIGHUP` | Reload workers |
| `SIGUSR1` | Reopen log files |

## Error Handling

The dirty client raises specific exceptions:

```python
from gunicorn.dirty import (
    DirtyError,
    DirtyTimeoutError,
    DirtyConnectionError,
    DirtyAppError,
    DirtyAppNotFoundError,
)

try:
    result = client.execute("myapp.ml:MLApp", "inference", "model", data)
except DirtyTimeoutError:
    # Operation timed out
    pass
except DirtyAppNotFoundError:
    # App not loaded in dirty workers
    pass
except DirtyAppError as e:
    # Error during app execution
    print(f"App error: {e.message}, traceback: {e.traceback}")
except DirtyConnectionError:
    # Connection to dirty arbiter failed
    pass
```

## Best Practices

1. **Pre-load commonly used resources** in `init()` to avoid cold starts
2. **Set appropriate timeouts** based on your workload
3. **Handle errors gracefully** - dirty workers may restart
4. **Use meaningful action names** for easier debugging
5. **Keep responses JSON-serializable** - results are passed via IPC

## Monitoring

Monitor dirty workers using standard process monitoring:

```bash
# Check dirty arbiter and workers
ps aux | grep "dirty"

# View logs
tail -f gunicorn.log | grep dirty
```

## Example: Image Processing

```python
# myapp/images.py
from gunicorn.dirty import DirtyApp
from PIL import Image
import io

class ImageApp(DirtyApp):
    def init(self):
        # Pre-import heavy libraries
        import cv2
        self.cv2 = cv2

    def resize(self, image_data, width, height):
        """Resize an image."""
        img = Image.open(io.BytesIO(image_data))
        resized = img.resize((width, height))
        buffer = io.BytesIO()
        resized.save(buffer, format='PNG')
        return buffer.getvalue()

    def thumbnail(self, image_data, size=128):
        """Create a thumbnail."""
        img = Image.open(io.BytesIO(image_data))
        img.thumbnail((size, size))
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG')
        return buffer.getvalue()

    def close(self):
        pass
```

Usage:

```python
from gunicorn.dirty import get_dirty_client

def upload_image(request):
    client = get_dirty_client()

    # Create thumbnail in dirty worker
    thumbnail = client.execute(
        "myapp.images:ImageApp",
        "thumbnail",
        request.files['image'].read(),
        size=256
    )

    return save_thumbnail(thumbnail)
```
