---
title: Dirty Arbiters
menu:
    guides:
        weight: 10
---

# Dirty Arbiters

!!! warning "Beta Feature"
    Dirty Arbiters is a beta feature introduced in Gunicorn 25.0.0. While it has been tested,
    the API and behavior may change in future releases. Please report any issues on
    [GitHub](https://github.com/benoitc/gunicorn/issues).

Dirty Arbiters provide a separate process pool for executing long-running, blocking operations (AI model loading, heavy computation) without blocking HTTP workers. This feature is inspired by Erlang's dirty schedulers.

## Overview

Traditional Gunicorn workers are designed to handle HTTP requests quickly. Long-running operations like loading ML models or performing heavy computation can block these workers, reducing the server's ability to handle concurrent requests.

Dirty Arbiters solve this by providing:

- **Separate worker pool** - Completely separate from HTTP workers, can be killed/restarted independently
- **Stateful workers** - Loaded resources persist in dirty worker memory
- **Message-passing IPC** - Communication via Unix sockets with binary TLV protocol
- **Explicit API** - Clear `execute()` calls (no hidden IPC)
- **Asyncio-based** - Clean concurrent handling with streaming support

## Design Philosophy

Dirty Arbiters follow several key design principles:

### Separate Process Hierarchy

Unlike threads or in-process pools, Dirty Arbiters use a fully separate process tree:

- **Isolation** - A crash or memory leak in a dirty worker cannot affect HTTP workers
- **Independent lifecycle** - Dirty workers can be killed/restarted without affecting request handling
- **Resource accounting** - OS-level memory limits can be applied per-process
- **Clean shutdown** - Each process tree can be signaled and terminated independently

### Erlang Inspiration

The name and concept come from Erlang's "dirty schedulers" - special schedulers that handle operations that would block normal schedulers. In Erlang, dirty schedulers run NIFs (Native Implemented Functions) that can't yield. Similarly, Gunicorn's Dirty Arbiters handle Python operations that would block HTTP workers.

### Why Asyncio

The Dirty Arbiter uses asyncio for its core loop rather than the main arbiter's select-based approach:

- **Non-blocking IPC** - Can handle many concurrent client connections efficiently
- **Concurrent request routing** - Multiple requests can be dispatched to workers simultaneously
- **Streaming support** - Native async generators for streaming responses
- **Clean signal handling** - Signals integrate cleanly via `loop.add_signal_handler()`

### Stateful Applications

Traditional WSGI apps are request-scoped - they're invoked per-request and don't maintain state between requests. Dirty apps are different:

- **Long-lived** - Apps persist in worker memory for the worker's lifetime
- **Pre-loaded resources** - Models, connections, and caches stay loaded
- **Explicit state management** - Apps control their own lifecycle via `init()` and `close()`

This makes dirty apps ideal for ML inference, where loading a model once and reusing it for many requests is essential.

## Architecture

```
                         +-------------------+
                         |   Main Arbiter    |
                         | (manages both)    |
                         +--------+----------+
                                  |
                    SIGTERM/SIGHUP/SIGUSR1 (forwarded)
                                  |
           +----------------------+----------------------+
           |                                             |
     +-----v-----+                                +------v------+
     | HTTP      |                                | Dirty       |
     | Workers   |                                | Arbiter     |
     +-----------+                                +------+------+
           |                                             |
           |    Unix Socket IPC                   SIGTERM/SIGHUP
           |    /tmp/gunicorn_dirty_<pid>.sock          |
           +------------------>---------------------->---+
                                             +-----------+-----------+
                                             |           |           |
                                       +-----v---+ +-----v---+ +-----v---+
                                       | Dirty   | | Dirty   | | Dirty   |
                                       | Worker  | | Worker  | | Worker  |
                                       +---------+ +---------+ +---------+
                                          ^   |        ^   |       ^   |
                                          |   |        |   |       |   |
                                    Heartbeat (mtime every dirty_timeout/2)
                                          |   |        |   |       |   |
                                          +---+--------+---+-------+---+
                                                       |
                                     Workers load apps based on allocation
                                     Worker 1: [MLApp, ImageApp, HeavyApp]
                                     Worker 2: [MLApp, ImageApp, HeavyApp]
                                     Worker 3: [MLApp, ImageApp]  (HeavyApp workers=2)
```

### Process Relationships

| Component | Parent | Communication |
|-----------|--------|---------------|
| Main Arbiter | init/systemd | Signals from OS |
| HTTP Workers | Main Arbiter | Pipes, signals |
| Dirty Arbiter | Main Arbiter | Signals, exit status |
| Dirty Workers | Dirty Arbiter | Unix socket, signals, WorkerTmp |

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

## Per-App Worker Allocation

By default, all dirty workers load all configured apps. For apps that consume significant memory (like large ML models), you can limit how many workers load a specific app.

### Why Per-App Allocation?

Consider a scenario with a 10GB ML model and 8 dirty workers:

- **Default behavior**: 8 workers × 10GB = 80GB RAM
- **With `workers=2`**: 2 workers × 10GB = 20GB RAM (75% savings)

Requests for the limited app are routed only to workers that have it loaded.

### Configuration Methods

**Method 1: Class Attribute**

Set the `workers` attribute on your DirtyApp class:

```python
from gunicorn.dirty import DirtyApp

class HeavyModelApp(DirtyApp):
    workers = 2  # Only 2 workers will load this app

    def init(self):
        self.model = load_10gb_model()

    def predict(self, data):
        return self.model.predict(data)

    def close(self):
        pass
```

**Method 2: Config Override**

Use the `module:class:N` format in your config:

```python
# gunicorn.conf.py
dirty_apps = [
    "myapp.light:LightApp",           # All workers (default)
    "myapp.heavy:HeavyModelApp:2",    # Only 2 workers
    "myapp.single:SingletonApp:1",    # Only 1 worker
]
dirty_workers = 4
```

Config overrides take precedence over class attributes.

### Worker Distribution

When workers spawn, apps are assigned based on their limits:

```
Example with dirty_workers=4:
  - LightApp (workers=None):  Loaded on workers 1, 2, 3, 4
  - HeavyModelApp (workers=2): Loaded on workers 1, 2
  - SingletonApp (workers=1):  Loaded on worker 1

Worker 1: [LightApp, HeavyModelApp, SingletonApp]
Worker 2: [LightApp, HeavyModelApp]
Worker 3: [LightApp]
Worker 4: [LightApp]
```

### Request Routing

Requests are automatically routed to workers that have the target app:

```python
client = get_dirty_client()

# Goes to any of 4 workers (round-robin)
client.execute("myapp.light:LightApp", "action")

# Goes to worker 1 or 2 only (round-robin between those)
client.execute("myapp.heavy:HeavyModelApp", "predict", data)

# Always goes to worker 1
client.execute("myapp.single:SingletonApp", "process")
```

### Error Handling

If no workers have the requested app loaded, a `DirtyNoWorkersAvailableError` is raised:

```python
from gunicorn.dirty import get_dirty_client
from gunicorn.dirty.errors import DirtyNoWorkersAvailableError

def my_view(request):
    client = get_dirty_client()
    try:
        result = client.execute("myapp.heavy:HeavyModelApp", "predict", data)
    except DirtyNoWorkersAvailableError as e:
        # All workers with this app are down or app not configured
        return {"error": "Service temporarily unavailable", "app": e.app_path}
```

### Worker Crash Recovery

When a worker crashes, its replacement gets the **same apps** as the dead worker:

```
Timeline:
  t=0: Worker 1 crashes (had HeavyModelApp)
  t=1: Arbiter detects crash, queues respawn
  t=2: New Worker 5 spawns with same apps as Worker 1
  t=3: HeavyModelApp still available on Worker 2 during gap
```

This ensures:

- No memory redistribution on existing workers
- Predictable replacement behavior
- The heavy model is only loaded on the new worker

### Best Practices

1. **Set realistic limits** - Don't set `workers=1` unless truly necessary (single point of failure)
2. **Monitor memory** - Track per-worker memory to tune allocation
3. **Handle unavailability** - Catch `DirtyNoWorkersAvailableError` gracefully
4. **Use class attributes for app-specific limits** - Makes the limit part of the app definition
5. **Use config for deployment-specific overrides** - Different limits for dev vs prod

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

| Method/Attribute | Description |
|------------------|-------------|
| `workers` | Class attribute. Number of workers to load this app (`None` = all workers). |
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

## Binary Protocol

The dirty worker IPC uses a binary protocol inspired by OpenBSD msgctl/msgsnd for efficient data transfer. This eliminates base64 encoding overhead for binary data like images, audio, or model weights.

### Header Format (16 bytes)

```
+--------+--------+--------+--------+--------+--------+--------+--------+
|  Magic (2B)     | Ver(1) | MType  |        Payload Length (4B)        |
+--------+--------+--------+--------+--------+--------+--------+--------+
|                       Request ID (8 bytes)                            |
+--------+--------+--------+--------+--------+--------+--------+--------+
```

- **Magic**: `0x47 0x44` ("GD" for Gunicorn Dirty)
- **Version**: `0x01`
- **MType**: Message type (`0x01`=REQUEST, `0x02`=RESPONSE, `0x03`=ERROR, `0x04`=CHUNK, `0x05`=END)
- **Length**: Payload size (big-endian uint32, max 64MB)
- **Request ID**: uint64 identifier

### TLV Payload Encoding

Payloads use Type-Length-Value encoding:

| Type | Code | Description |
|------|------|-------------|
| None | `0x00` | No value bytes |
| Bool | `0x01` | 1 byte (0x00/0x01) |
| Int64 | `0x05` | 8 bytes big-endian signed |
| Float64 | `0x06` | 8 bytes IEEE 754 |
| Bytes | `0x10` | 4-byte length + raw bytes |
| String | `0x11` | 4-byte length + UTF-8 |
| List | `0x20` | 4-byte count + elements |
| Dict | `0x21` | 4-byte count + key-value pairs |

### Binary Data Benefits

The binary protocol allows passing raw bytes directly without encoding:

```python
# Image processing with binary data
def resize(self, image_data, width, height):
    """Resize an image - image_data is raw bytes."""
    img = Image.open(io.BytesIO(image_data))
    resized = img.resize((width, height))
    buffer = io.BytesIO()
    resized.save(buffer, format='PNG')
    return buffer.getvalue()  # Returns raw bytes

# Called from HTTP worker
thumbnail = client.execute(
    "myapp.images:ImageApp",
    "thumbnail",
    raw_image_bytes,  # No base64 encoding needed
    size=256
)
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

## Stash (Shared State via Message Passing)

Stash provides shared state between dirty workers, similar to Erlang's ETS (Erlang Term Storage). Workers remain fully isolated - all state access goes through message passing to the arbiter.

### Architecture

```
                    +------------------+
                    |   Dirty Arbiter  |
                    |                  |
                    |  stash_tables:   |
                    |    sessions: {}  |
                    |    cache: {}     |
                    +--------+---------+
                             |
              Unix Socket IPC (message passing)
                             |
         +-------------------+-------------------+
         |                   |                   |
   +-----v-----+       +-----v-----+       +-----v-----+
   |  Worker 1 |       |  Worker 2 |       |  Worker 3 |
   |           |       |           |       |           |
   | (isolated)|       | (isolated)|       | (isolated)|
   +-----------+       +-----------+       +-----------+

   Workers have NO shared memory.
   All stash operations are IPC messages to arbiter.
```

### How It Works

1. Worker calls `stash.put("sessions", "user:1", data)`
2. Worker sends message to arbiter via Unix socket
3. Arbiter stores data in its memory (`self.stash_tables`)
4. Arbiter sends response back to worker
5. Worker receives confirmation

This is **not** shared memory - workers remain fully isolated. The arbiter acts as a centralized store that workers communicate with via message passing. This matches Erlang's model where ETS tables are owned by a process.

### Basic Usage

```python
from gunicorn.dirty import stash

# Store a value (table auto-created)
# This sends a message to arbiter, which stores it
stash.put("sessions", "user:123", {"name": "Alice", "role": "admin"})

# Retrieve a value
# This sends a request to arbiter, which returns the value
user = stash.get("sessions", "user:123")

# Delete a key
stash.delete("sessions", "user:123")

# Check existence
if stash.exists("sessions", "user:123"):
    print("Session exists")

# List keys with pattern matching
keys = stash.keys("sessions", pattern="user:*")
```

### Dict-like Interface

For more Pythonic access, use the table interface:

```python
from gunicorn.dirty import stash

# Get a table reference
sessions = stash.table("sessions")

# Dict-like operations (each is an IPC message)
sessions["user:123"] = {"name": "Alice"}
user = sessions["user:123"]
del sessions["user:123"]

# Iteration
for key in sessions:
    print(key, sessions[key])

# Length
count = len(sessions)
```

### Table Management

```python
from gunicorn.dirty import stash

# Explicit table creation (idempotent)
stash.ensure("cache")

# Get table info
info = stash.info("sessions")
print(f"Table has {info['size']} entries")

# Clear all entries in a table
stash.clear("sessions")

# Delete entire table
stash.delete_table("sessions")

# List all tables
tables = stash.tables()
```

### Using Stash in DirtyApp

Declare tables your app uses with the `stashes` class attribute:

```python
from gunicorn.dirty import DirtyApp, stash

class SessionApp(DirtyApp):
    # Tables declared here are auto-created on startup
    stashes = ["sessions", "counters"]

    def init(self):
        # Initialize counter if needed
        if not stash.exists("counters", "requests"):
            stash.put("counters", "requests", 0)

    def login(self, user_id, user_data):
        """Store session - any worker can read it via arbiter."""
        stash.put("sessions", f"user:{user_id}", {
            "data": user_data,
            "logged_in_at": time.time(),
        })
        self._increment_counter()
        return {"status": "ok"}

    def get_session(self, user_id):
        """Get session - request goes to arbiter."""
        return stash.get("sessions", f"user:{user_id}")

    def _increment_counter(self):
        """Increment global counter via arbiter."""
        current = stash.get("counters", "requests", 0)
        stash.put("counters", "requests", current + 1)

    def close(self):
        pass
```

### API Reference

| Function | Description |
|----------|-------------|
| `stash.put(table, key, value)` | Store a value (table auto-created) |
| `stash.get(table, key, default=None)` | Retrieve a value |
| `stash.delete(table, key)` | Delete a key, returns True if deleted |
| `stash.exists(table, key=None)` | Check if table/key exists |
| `stash.keys(table, pattern=None)` | List keys, optional glob pattern |
| `stash.clear(table)` | Delete all entries in table |
| `stash.info(table)` | Get table info (size, etc.) |
| `stash.ensure(table)` | Create table if not exists |
| `stash.delete_table(table)` | Delete entire table |
| `stash.tables()` | List all table names |
| `stash.table(name)` | Get dict-like interface |

### Patterns and Use Cases

**Session Storage:**
```python
# Store session on login (worker 1)
stash.put("sessions", f"user:{user_id}", session_data)

# Check session on request (may be worker 2)
session = stash.get("sessions", f"user:{user_id}")
if session is None:
    raise AuthError("Not logged in")
```

**Shared Cache:**
```python
def get_expensive_result(key):
    # Check cache first (via arbiter)
    cached = stash.get("cache", key)
    if cached is not None:
        return cached

    # Compute and cache
    result = expensive_computation()
    stash.put("cache", key, result)
    return result
```

**Global Counters:**
```python
def increment_counter(name):
    # Note: not atomic - two workers could read same value
    current = stash.get("counters", name, 0)
    stash.put("counters", name, current + 1)
    return current + 1
```

**Feature Flags:**
```python
# Set flag (from admin endpoint)
stash.put("flags", "new_feature", True)

# Check flag (from any worker)
if stash.get("flags", "new_feature", False):
    enable_new_feature()
```

### Error Handling

```python
from gunicorn.dirty.stash import (
    StashError,
    StashTableNotFoundError,
    StashKeyNotFoundError,
)

try:
    info = stash.info("nonexistent")
except StashTableNotFoundError as e:
    print(f"Table not found: {e.table_name}")

# Using get() with default avoids KeyNotFoundError
value = stash.get("table", "key", default="fallback")
```

### Best Practices

1. **Use descriptive table names** - `user_sessions`, `ml_cache`, not `data`
2. **Use key prefixes** - `user:123`, `cache:model:v1` for organization
3. **Handle missing data** - Always provide defaults or check existence
4. **Don't store large data** - Each access is an IPC round-trip
5. **Remember it's ephemeral** - Data is lost on arbiter restart

### Advantages

- **Worker isolation** - Workers remain fully isolated; no shared memory bugs
- **Simple API** - Dict-like interface, no locking required
- **Binary support** - Efficiently stores bytes (images, model weights)
- **Pattern matching** - `keys(pattern="user:*")` for querying
- **Zero setup** - Works automatically with dirty workers
- **Table-based** - Organize data into logical namespaces

### Limitations

- **No persistence** - Data lives only in arbiter memory
- **No transactions** - No atomic read-modify-write operations
- **No TTL** - Entries don't expire automatically
- **IPC overhead** - Each operation is a network round-trip
- **Single arbiter** - Not distributed across multiple machines

For persistent or distributed state, use Redis, PostgreSQL, or similar external systems.

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

Dirty Arbiters integrate with the main arbiter's signal handling. Signals are forwarded from the main arbiter to the dirty arbiter, which then propagates them to workers.

### Signal Flow

```
  Main Arbiter                    Dirty Arbiter                 Dirty Workers
       |                                |                             |
  SIGTERM/SIGHUP/SIGUSR1 ------>  signal_handler()                    |
       |                                |                             |
       |                          call_soon_threadsafe()              |
       |                                |                             |
       |                          handle_signal()                     |
       |                                |                             |
       |                                +------> os.kill(worker, sig) |
       |                                                              |
```

### Signal Reference

| Signal | At Dirty Arbiter | At Dirty Workers | Notes |
|--------|-----------------|------------------|-------|
| `SIGTERM` | Sets `self.alive = False`, waits for graceful shutdown | Exits after completing current request | Graceful shutdown with timeout |
| `SIGQUIT` | Immediate exit via `sys.exit(0)` | Killed immediately | Fast shutdown, no cleanup |
| `SIGHUP` | Kills all workers, spawns new ones | Exits immediately | Hot reload of workers |
| `SIGUSR1` | Reopens log files, forwards to workers | Reopens log files | Log rotation support |
| `SIGTTIN` | Increases worker count by 1 | N/A | Dynamic scaling up |
| `SIGTTOU` | Decreases worker count by 1 | N/A | Dynamic scaling down |
| `SIGCHLD` | Handled by event loop, triggers reap | N/A | Worker death detection |
| `SIGINT` | Same as SIGTERM | Same as SIGTERM | Ctrl-C handling |

### Dynamic Scaling with TTIN/TTOU

You can dynamically scale the number of dirty workers at runtime using signals, without restarting gunicorn:

```bash
# Find the dirty arbiter process
ps aux | grep dirty-arbiter
# Or use the PID file (location depends on your app name)
cat /tmp/gunicorn-dirty-myapp.pid

# Increase dirty workers by 1
kill -TTIN <dirty-arbiter-pid>

# Decrease dirty workers by 1
kill -TTOU <dirty-arbiter-pid>
```

**Minimum Worker Constraint:** The dirty arbiter will not decrease below the minimum number of workers required by your app configurations. For example, if you have an app with `workers = 3`, you cannot scale below 3 dirty workers. When this limit is reached, a warning is logged:

```
WARNING: SIGTTOU: Cannot decrease below 3 workers (required by app specs)
```

**Use Cases:**

- **Burst handling** - Scale up when you anticipate heavy load
- **Cost optimization** - Scale down during low-traffic periods
- **Recovery** - Scale up if workers are busy with long-running tasks

### Forwarded Signals

The main arbiter forwards these signals to the dirty arbiter process:

- **SIGTERM** - Graceful shutdown of entire process tree
- **SIGHUP** - Worker reload (main arbiter reloads HTTP workers, dirty arbiter reloads dirty workers)
- **SIGUSR1** - Log rotation across all processes

### Async Signal Handling

The dirty arbiter uses asyncio's signal integration for safe handling in the event loop:

```python
# Signals are registered with the event loop
loop.add_signal_handler(signal.SIGTERM, self.signal_handler, signal.SIGTERM)

def signal_handler(self, sig):
    # Use call_soon_threadsafe for thread-safe event loop integration
    self.loop.call_soon_threadsafe(self.handle_signal, sig)
```

This pattern ensures signals don't interrupt asyncio operations mid-execution, preventing race conditions and partial state updates.

## Liveness and Health Monitoring

Dirty Arbiters implement multiple layers of health monitoring to ensure workers remain responsive and orphaned processes are cleaned up.

### Heartbeat Mechanism

Each dirty worker maintains a "worker tmp" file whose mtime serves as a heartbeat:

```
Worker Lifecycle:
  1. Worker spawns, creates WorkerTmp file
  2. Worker touches file every (dirty_timeout / 2) seconds
  3. Arbiter checks all worker mtimes every 1 second
  4. If mtime > dirty_timeout seconds old, worker is killed
```

This file-based heartbeat has several advantages:

- **OS-level tracking** - No IPC required, works even if worker is stuck in C code
- **Crash detection** - Arbiter notices immediately when worker stops updating
- **Graceful recovery** - Worker killed with SIGKILL, arbiter spawns replacement

### Timeout Detection

The arbiter's monitoring loop checks worker health every second:

```python
# Pseudocode for worker monitoring
for worker in self.workers:
    mtime = worker.tmp.last_update()
    if time.time() - mtime > self.dirty_timeout:
        log.warning(f"Worker {worker.pid} timed out, killing")
        os.kill(worker.pid, signal.SIGKILL)
```

When a worker is killed:

1. `SIGCHLD` is delivered to the arbiter
2. Arbiter reaps the worker process
3. `dirty_worker_exit` hook is called
4. A new worker is spawned to maintain `dirty_workers` count

### Parent Death Detection

Dirty arbiters monitor their parent process (the main arbiter) to detect orphaning:

```python
# In the dirty arbiter's main loop
if os.getppid() != self.parent_pid:
    log.info("Parent died, shutting down")
    self.alive = False
```

This check runs every iteration of the event loop (typically sub-millisecond). When parent death is detected:

1. Arbiter sets `self.alive = False`
2. All workers are sent SIGTERM
3. Arbiter waits for graceful shutdown (up to `dirty_graceful_timeout`)
4. Remaining workers are sent SIGKILL
5. Arbiter exits

### Orphan Cleanup

To handle edge cases where the dirty arbiter itself crashes, a well-known PID file is used:

**PID file location**: `/tmp/gunicorn_dirty_<main_arbiter_pid>.pid`

On startup, the dirty arbiter:

1. Checks if PID file exists
2. If yes, reads the old PID and attempts to kill it (`SIGTERM`)
3. Waits briefly for cleanup
4. Writes its own PID to the file
5. On exit, removes the PID file

This ensures that if a dirty arbiter crashes and the main arbiter restarts it, the old orphaned process is terminated.

### Respawn Behavior

| Component | Respawn Trigger | Respawn Behavior |
|-----------|-----------------|------------------|
| Dirty Worker | Exit, timeout, or crash | Immediate respawn to maintain `dirty_workers` count |
| Dirty Arbiter | Exit or crash | Main arbiter respawns if not shutting down |

The dirty arbiter maintains a target worker count and continuously spawns workers until the target is reached:

```python
while len(self.workers) < self.num_workers:
    self.spawn_worker()
```

### Monitoring Recommendations

For production deployments, consider:

1. **Log monitoring** - Watch for "Worker timed out" messages indicating hung workers
2. **Process monitoring** - Use systemd or supervisord to monitor the main arbiter
3. **Metrics** - Track respawn frequency to detect unstable workers

```bash
# Check for recent worker timeouts
grep "Worker.*timed out" /var/log/gunicorn.log | tail -20

# Monitor process tree
watch -n 1 'pstree -p $(cat gunicorn.pid)'
```

## Error Handling

The dirty client raises specific exceptions:

```python
from gunicorn.dirty.errors import (
    DirtyError,
    DirtyTimeoutError,
    DirtyConnectionError,
    DirtyAppError,
    DirtyAppNotFoundError,
    DirtyNoWorkersAvailableError,
)

try:
    result = client.execute("myapp.ml:MLApp", "inference", "model", data)
except DirtyTimeoutError:
    # Operation timed out
    pass
except DirtyAppNotFoundError:
    # App not loaded in dirty workers
    pass
except DirtyNoWorkersAvailableError as e:
    # No workers have this app (all crashed or app limited to 0 workers)
    print(f"No workers for app: {e.app_path}")
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
5. **Keep responses serializable** - results are passed via binary IPC (supports bytes directly)

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

## Complete Examples

For full working examples with Docker deployment, see:

- [Embedding Service Example](https://github.com/benoitc/gunicorn/tree/master/examples/embedding_service) - FastAPI-based text embedding API using sentence-transformers with dirty workers for ML model management.
- [Streaming Chat Example](https://github.com/benoitc/gunicorn/tree/master/examples/streaming_chat) - Simulated LLM chat with token-by-token SSE streaming, demonstrating dirty worker generators and real-time response delivery.
