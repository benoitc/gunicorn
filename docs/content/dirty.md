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

## Streaming

Dirty Arbiters support streaming responses for use cases like LLM token generation, where data is produced incrementally. This enables real-time delivery of results without waiting for complete execution.

### Streaming with Generators

Any dirty app action that returns a generator (sync or async) automatically streams chunks to the client:

```python
# myapp/llm.py
from gunicorn.dirty import DirtyApp

class LLMApp(DirtyApp):
    def init(self):
        from transformers import pipeline
        self.generator = pipeline("text-generation", model="gpt2")

    def generate(self, prompt):
        """Sync streaming - yields tokens."""
        for token in self.generator(prompt, stream=True):
            yield token["generated_text"]

    async def generate_async(self, prompt):
        """Async streaming - yields tokens."""
        import openai
        client = openai.AsyncOpenAI()
        stream = await client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            stream=True
        )
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def close(self):
        pass
```

### Client Streaming API

Use `stream()` for sync workers and `stream_async()` for async workers:

**Sync Workers (sync, gthread):**

```python
from gunicorn.dirty import get_dirty_client

def generate_view(request):
    client = get_dirty_client()

    def generate_response():
        for chunk in client.stream("myapp.llm:LLMApp", "generate", request.prompt):
            yield chunk

    return StreamingResponse(generate_response())
```

**Async Workers (ASGI):**

```python
from gunicorn.dirty import get_dirty_client_async

async def generate_view(request):
    client = await get_dirty_client_async()

    async def generate_response():
        async for chunk in client.stream_async("myapp.llm:LLMApp", "generate", request.prompt):
            yield chunk

    return StreamingResponse(generate_response())
```

### Streaming Protocol

Streaming uses a simple protocol with three message types:

1. **Chunk** (`type: "chunk"`) - Contains partial data
2. **End** (`type: "end"`) - Signals stream completion
3. **Error** (`type: "error"`) - Signals error during streaming

Example message flow:
```
Client -> Arbiter -> Worker: request
Worker -> Arbiter -> Client: chunk (data: "Hello")
Worker -> Arbiter -> Client: chunk (data: " ")
Worker -> Arbiter -> Client: chunk (data: "World")
Worker -> Arbiter -> Client: end
```

### Error Handling in Streams

Errors during streaming are delivered as error messages:

```python
def generate_view(request):
    client = get_dirty_client()

    try:
        for chunk in client.stream("myapp.llm:LLMApp", "generate", prompt):
            yield chunk
    except DirtyError as e:
        # Error occurred mid-stream
        yield f"\n[Error: {e.message}]"
```

### Best Practices for Streaming

1. **Use async generators for I/O-bound streaming** - e.g., API calls to external services
2. **Use sync generators for CPU-bound streaming** - e.g., local model inference
3. **Yield frequently** - Heartbeats are sent during streaming to keep workers alive
4. **Keep chunks small** - Smaller chunks provide better perceived latency
5. **Handle client disconnection** - Streams continue even if client disconnects; design accordingly

### Flask Example

```python
from flask import Flask, Response
from gunicorn.dirty import get_dirty_client

app = Flask(__name__)

@app.route("/chat", methods=["POST"])
def chat():
    prompt = request.json.get("prompt")
    client = get_dirty_client()

    def stream():
        for token in client.stream("myapp.llm:LLMApp", "generate", prompt):
            yield f"data: {token}\n\n"

    return Response(stream(), content_type="text/event-stream")
```

### FastAPI Example

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from gunicorn.dirty import get_dirty_client_async

app = FastAPI()

@app.post("/chat")
async def chat(prompt: str):
    client = await get_dirty_client_async()

    async def stream():
        async for token in client.stream_async("myapp.llm:LLMApp", "generate", prompt):
            yield f"data: {token}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
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
