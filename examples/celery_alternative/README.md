# Celery Alternative Example

This example demonstrates how to replace Celery with Gunicorn's **dirty arbiters** for background task processing, using **async ASGI** for non-blocking HTTP handling.

## Why Use This Instead of Celery?

### The Problem with Celery

Celery requires:
- An external message broker (Redis or RabbitMQ)
- Separate worker processes (`celery -A app worker`)
- Stateless workers that reload models/connections on every task
- Polling or WebSockets for progress updates

### What Dirty Arbiters Provide

| Feature | Celery | Dirty Arbiters |
|---------|--------|----------------|
| **External broker** | Required (Redis/RabbitMQ) | None - uses Unix sockets |
| **Deployment** | Multiple processes | Single `gunicorn` command |
| **Worker state** | Stateless | Stateful - keep ML models, DB connections loaded |
| **Progress updates** | Polling or WebSocket | Native streaming |
| **HTTP blocking** | N/A (separate process) | Non-blocking with async ASGI |

### When to Use Dirty Arbiters

**Good fit:**
- Tasks that benefit from keeping state (ML models, DB connection pools, caches)
- Tasks where you want immediate results (not fire-and-forget)
- Real-time progress streaming
- Simpler deployment without external dependencies

**Not ideal for:**
- True fire-and-forget queuing with persistence
- Distributed task execution across multiple machines
- Tasks that must survive server restarts

## How It Works

```
┌─────────────────────────────────────────────────────────────┐
│                    Gunicorn Master                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              ASGI Workers (uvloop)                   │   │
│  │   Non-blocking! One worker handles many requests     │   │
│  │   await client.execute_async() doesn't block         │   │
│  └──────────────────────────┬──────────────────────────┘   │
│                             │                               │
│                       Unix Socket IPC                       │
│                             │                               │
│  ┌──────────────────────────┼──────────────────────────┐   │
│  │                Dirty Workers (Stateful)              │   │
│  │                                                      │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐     │   │
│  │  │EmailWorker │  │ImageWorker │  │DataWorker  │ ... │   │
│  │  │ (2 procs)  │  │ (2 procs)  │  │ (4 procs)  │     │   │
│  │  │            │  │            │  │            │     │   │
│  │  │ SMTP conn  │  │ PIL loaded │  │ DB pool    │     │   │
│  │  │ kept alive │  │ in memory  │  │ cached     │     │   │
│  │  └────────────┘  └────────────┘  └────────────┘     │   │
│  │                                                      │   │
│  │                    Dirty Arbiter                     │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Key insight:** The HTTP workers use async I/O, so `await client.execute_async()` doesn't block the event loop. One ASGI worker can handle thousands of concurrent requests while waiting for dirty workers to complete tasks.

## Quick Start

### Local Development

```bash
# Install dependencies
pip install fastapi uvloop httpx pytest pytest-asyncio
pip install -e ../..  # Install gunicorn from source

# Run the application
gunicorn -c gunicorn_conf.py app:app

# In another terminal, test it
curl http://localhost:8000/health
curl -X POST http://localhost:8000/api/email/send \
  -H "Content-Type: application/json" \
  -d '{"to": "test@example.com", "subject": "Hello", "body": "World"}'

# Interactive API docs
open http://localhost:8000/docs
```

### Docker

```bash
# Build and run
docker compose up --build

# Run with tests
docker compose --profile test up --build --abort-on-container-exit
```

## Task Workers

Each worker class maintains state across requests:

### EmailWorker (2 workers)
- Keeps SMTP connection alive
- `send_email(to, subject, body)` - Send single email
- `send_bulk_emails(recipients, subject, body)` - Bulk send with streaming progress

### ImageWorker (2 workers)
- Keeps PIL/image libraries loaded
- `resize(image_data, width, height)` - Resize image
- `process_batch(images, operation)` - Batch process with streaming

### DataWorker (4 workers)
- Maintains DB connection pool and query cache
- `aggregate(data, group_by, agg_field)` - Aggregate data
- `etl_pipeline(source_data, transformations)` - ETL with streaming progress
- `cached_query(query_key, ttl)` - Query with in-memory caching

### ScheduledWorker (1 worker)
- For periodic tasks (call from cron)
- `cleanup_old_files(directory, max_age_days)`
- `generate_daily_report()`

## Streaming Progress Example

Real-time progress without polling:

```python
import httpx
import json

async with httpx.AsyncClient() as client:
    async with client.stream(
        "POST",
        "http://localhost:8000/api/email/send-bulk",
        json={
            "recipients": ["a@x.com", "b@x.com", "c@x.com"],
            "subject": "Newsletter",
            "body": "Hello!",
        },
    ) as response:
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                progress = json.loads(line[6:])
                if progress["type"] == "progress":
                    print(f"Progress: {progress['percent']}%")
                elif progress["type"] == "complete":
                    print(f"Done! Sent: {progress['sent']}")
```

## Celery Migration Guide

### Before (Celery)

```python
# tasks.py
from celery import Celery

app = Celery('tasks', broker='redis://localhost')

@app.task
def send_email(to, subject, body):
    smtp = smtplib.SMTP(...)  # New connection every task!
    smtp.send(...)
    return {"status": "sent"}

@app.task(bind=True)
def send_bulk(self, recipients, subject, body):
    for i, to in enumerate(recipients):
        send_email(to, subject, body)
        self.update_state(state='PROGRESS', meta={'current': i})  # Requires polling!
```

```python
# views.py - Flask
from tasks import send_email

@app.route('/send')
def send_view():
    send_email.delay(to, subject, body)  # Fire and forget
    return {"status": "queued"}  # Can't get result without polling
```

### After (Dirty Arbiters)

```python
# tasks.py
from gunicorn.dirty.app import DirtyApp

class EmailWorker(DirtyApp):
    workers = 2

    def init(self):
        self.smtp = smtplib.SMTP(...)  # Connected once, reused!

    def __call__(self, action, *args, **kwargs):
        return getattr(self, action)(*args, **kwargs)

    def send_email(self, to, subject, body):
        self.smtp.send(...)  # Reuses connection
        return {"status": "sent"}

    def send_bulk(self, recipients, subject, body):
        for i, to in enumerate(recipients):
            self.send_email(to, subject, body)
            yield {"type": "progress", "current": i}  # Native streaming!
```

```python
# views.py - FastAPI (async)
from gunicorn.dirty import get_dirty_client_async

@app.post('/send')
async def send_view(data: EmailRequest):
    client = await get_dirty_client_async()
    # Non-blocking! Other requests handled while waiting
    result = await client.execute_async("tasks:EmailWorker", "send_email", ...)
    return result  # Immediate result, no polling!
```

## Configuration

```python
# gunicorn_conf.py

# ASGI workers for non-blocking HTTP
worker_class = "asgi"
asgi_loop = "uvloop"
workers = 4

# Dirty workers (replace Celery)
dirty_apps = [
    "tasks:EmailWorker",
    "tasks:ImageWorker",
    "tasks:DataWorker",
]
dirty_workers = 9
dirty_timeout = 300
```

## Running Tests

```bash
# Unit tests (no server needed)
pytest tests/test_tasks.py -v

# Integration tests (server must be running)
APP_URL=http://localhost:8000 pytest tests/test_integration.py -v

# All tests via Docker
docker compose --profile test up --build --abort-on-container-exit
```

## API Endpoints

Visit `/docs` for interactive Swagger documentation.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/email/send` | POST | Send single email |
| `/api/email/send-bulk` | POST | Bulk send (SSE streaming) |
| `/api/image/resize` | POST | Resize image |
| `/api/image/process-batch` | POST | Batch process (SSE streaming) |
| `/api/data/aggregate` | POST | Aggregate data |
| `/api/data/etl` | POST | ETL pipeline (SSE streaming) |
| `/api/data/query` | POST | Cached query |
| `/api/scheduled/*` | POST | Scheduled tasks |
| `/health` | GET | Health check |
