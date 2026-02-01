# Celery Alternative Example

This example demonstrates how to replace Celery with Gunicorn's **dirty arbiters** for background task processing.

## Why Replace Celery?

| Aspect | Celery | Dirty Arbiters |
|--------|--------|----------------|
| Dependencies | Redis/RabbitMQ + Celery | None (built into Gunicorn) |
| Deployment | Multiple processes/containers | Single process |
| State | Stateless workers | Stateful workers (keep models loaded) |
| Progress | Polling or WebSocket | Native streaming |
| Configuration | Separate config | Same gunicorn.conf.py |

## Quick Start

### Local Development

```bash
# Install dependencies
pip install flask requests pytest
pip install -e ../..  # Install gunicorn from source

# Run the application
gunicorn -c gunicorn_conf.py app:app

# In another terminal, test it
curl http://localhost:8000/health
curl -X POST http://localhost:8000/api/email/send \
  -H "Content-Type: application/json" \
  -d '{"to": "test@example.com", "subject": "Hello", "body": "World"}'
```

### Docker

```bash
# Build and run
docker compose up --build

# Run with tests
docker compose --profile test up --build --abort-on-container-exit
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Gunicorn Master                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ HTTP Worker │  │ HTTP Worker │  │ HTTP Worker │  ...    │
│  │  (gthread)  │  │  (gthread)  │  │  (gthread)  │         │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │
│         │                │                │                 │
│         └────────────────┼────────────────┘                 │
│                          │                                  │
│                    Unix Socket IPC                          │
│                          │                                  │
│         ┌────────────────┼────────────────┐                 │
│         │                │                │                 │
│  ┌──────▼──────┐  ┌──────▼──────┐  ┌──────▼──────┐         │
│  │ EmailWorker │  │ ImageWorker │  │ DataWorker  │  ...    │
│  │  (2 procs)  │  │  (2 procs)  │  │  (4 procs)  │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
│                                                             │
│                    Dirty Arbiter                            │
└─────────────────────────────────────────────────────────────┘
```

## Task Workers

### EmailWorker
- `send_email(to, subject, body)` - Send single email
- `send_bulk_emails(recipients, subject, body)` - Bulk send with progress streaming
- `stats()` - Worker statistics

### ImageWorker
- `resize(image_data, width, height)` - Resize image
- `generate_thumbnail(image_data, size)` - Generate thumbnail
- `process_batch(images, operation, **params)` - Batch process with streaming

### DataWorker
- `aggregate(data, group_by, agg_field, agg_func)` - Aggregate data
- `etl_pipeline(source_data, transformations)` - ETL with progress streaming
- `cached_query(query_key, ttl)` - Cached query execution

### ScheduledWorker
- `cleanup_old_files(directory, max_age_days)` - File cleanup
- `generate_daily_report()` - Daily report generation
- `sync_external_data(source)` - External data sync

## API Endpoints

### Email
- `POST /api/email/send` - Send single email
- `POST /api/email/send-bulk` - Bulk send (SSE streaming)
- `GET /api/email/stats` - Worker stats

### Image
- `POST /api/image/resize` - Resize image
- `POST /api/image/thumbnail` - Generate thumbnail
- `POST /api/image/process-batch` - Batch process (SSE streaming)
- `GET /api/image/stats` - Worker stats

### Data
- `POST /api/data/aggregate` - Aggregate data
- `POST /api/data/etl` - ETL pipeline (SSE streaming)
- `POST /api/data/query` - Cached query
- `GET /api/data/stats` - Worker stats

### Scheduled
- `POST /api/scheduled/cleanup` - Run cleanup
- `POST /api/scheduled/daily-report` - Generate report
- `POST /api/scheduled/sync` - Sync data
- `GET /api/scheduled/stats` - Worker stats

## Streaming Progress Example

```python
import requests
import json

# Start bulk email with streaming progress
resp = requests.post(
    "http://localhost:8000/api/email/send-bulk",
    json={
        "recipients": ["a@x.com", "b@x.com", "c@x.com"],
        "subject": "Newsletter",
        "body": "Hello!",
    },
    stream=True,
)

for line in resp.iter_lines():
    if line and line.startswith(b"data: "):
        progress = json.loads(line[6:])
        if progress["type"] == "progress":
            print(f"Progress: {progress['percent']}%")
        elif progress["type"] == "complete":
            print(f"Done! Sent: {progress['sent']}, Failed: {progress['failed']}")
```

## Celery Migration Guide

### Before (Celery)

```python
# tasks.py
from celery import Celery

app = Celery('tasks', broker='redis://localhost')

@app.task
def send_email(to, subject, body):
    # Send email
    return {"status": "sent"}

@app.task(bind=True)
def send_bulk(self, recipients, subject, body):
    for i, to in enumerate(recipients):
        send_email(to, subject, body)
        self.update_state(state='PROGRESS', meta={'current': i})
```

```python
# views.py
from tasks import send_email, send_bulk

def send_view(request):
    send_email.delay(to, subject, body)  # Async
    return {"status": "queued"}
```

### After (Dirty Arbiters)

```python
# tasks.py
from gunicorn.dirty.app import DirtyApp

class EmailWorker(DirtyApp):
    workers = 2  # Limit workers

    def init(self):
        self.smtp = connect_smtp()  # Stateful!

    def __call__(self, action, *args, **kwargs):
        return getattr(self, action)(*args, **kwargs)

    def send_email(self, to, subject, body):
        return {"status": "sent"}

    def send_bulk(self, recipients, subject, body):
        for i, to in enumerate(recipients):
            self.send_email(to, subject, body)
            yield {"type": "progress", "current": i}  # Native streaming!
```

```python
# views.py
from gunicorn.dirty import get_dirty_client

def send_view(request):
    client = get_dirty_client()
    result = client.execute("tasks:EmailWorker", "send_email", to, subject, body)
    return result  # Sync result, no polling!
```

## Configuration

```python
# gunicorn_conf.py

# HTTP workers
workers = 4
worker_class = "gthread"
threads = 4

# Task workers (replace Celery)
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
