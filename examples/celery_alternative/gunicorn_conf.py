"""
Gunicorn Configuration - Celery Replacement Example

This configuration sets up:
1. ASGI workers to handle web requests with async I/O (using uvloop)
2. Dirty workers to handle background tasks (replacing Celery workers)

Why ASGI + Dirty Arbiters?
- ASGI: Non-blocking HTTP handling - one worker handles many concurrent requests
- Dirty: Stateful background workers - keep models/connections loaded in memory

Comparison with Celery deployment:
- Celery: gunicorn app:app + celery -A tasks worker + redis-server
- Dirty: gunicorn -c gunicorn_conf.py app:app (single command, no broker!)
"""

import multiprocessing
import os

# =============================================================================
# Basic Settings
# =============================================================================

# Bind to all interfaces on port 8000
bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:8000")

# HTTP workers - handle incoming web requests
# With ASGI, fewer workers needed since each handles many concurrent requests
workers = int(os.environ.get("GUNICORN_WORKERS", min(4, multiprocessing.cpu_count() + 1)))

# Use gunicorn's native ASGI worker for async support
# This enables: await client.execute_async() without blocking
worker_class = "asgi"

# Use uvloop for better async performance
asgi_loop = "uvloop"

# Maximum concurrent connections per worker
worker_connections = 1000

# =============================================================================
# Dirty Arbiter Settings (Celery Worker Replacement)
# =============================================================================

# Task workers - these replace Celery workers
# Each dirty app can specify its own worker count via the `workers` class attribute
dirty_apps = [
    # Email tasks - 2 workers (I/O bound)
    "examples.celery_alternative.tasks:EmailWorker",
    # Image processing - 2 workers (CPU/memory intensive)
    "examples.celery_alternative.tasks:ImageWorker",
    # Data processing - 4 workers (parallelizable)
    "examples.celery_alternative.tasks:DataWorker",
    # Scheduled tasks - 1 worker
    "examples.celery_alternative.tasks:ScheduledWorker",
]

# Total dirty workers (distributed among apps based on their `workers` attribute)
# If not set, uses sum of all app worker counts
dirty_workers = int(os.environ.get("DIRTY_WORKERS", 9))  # 2+2+4+1 = 9

# Task timeout in seconds (like Celery's task_time_limit)
dirty_timeout = int(os.environ.get("DIRTY_TIMEOUT", 300))

# Threads per dirty worker (for concurrent task execution)
dirty_threads = int(os.environ.get("DIRTY_THREADS", 1))

# Graceful shutdown timeout
dirty_graceful_timeout = int(os.environ.get("DIRTY_GRACEFUL_TIMEOUT", 30))

# =============================================================================
# Timeouts & Limits
# =============================================================================

# Worker timeout (seconds)
timeout = 120

# Keep-alive connections
keepalive = 5

# Maximum requests per worker before recycling
max_requests = 1000
max_requests_jitter = 50

# =============================================================================
# Logging
# =============================================================================

# Log level
loglevel = os.environ.get("LOG_LEVEL", "info")

# Access log format
accesslog = "-"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Error log
errorlog = "-"

# =============================================================================
# Lifecycle Hooks
# =============================================================================

def on_starting(server):
    """Called just before the master process is initialized."""
    print("=" * 60)
    print("Starting Gunicorn with Dirty Arbiters (Celery Replacement)")
    print("Using ASGI workers with uvloop for non-blocking HTTP handling")
    print("=" * 60)


def on_dirty_starting(arbiter):
    """Called when the dirty arbiter is starting."""
    print(f"[Dirty] Starting dirty arbiter")
    print(f"[Dirty] Registered apps: {list(arbiter.cfg.dirty_apps)}")


def dirty_post_fork(arbiter, worker):
    """Called after a dirty worker is forked."""
    print(f"[Dirty] Worker {worker.pid} started")


def dirty_worker_init(worker):
    """Called when a dirty worker initializes its apps."""
    print(f"[Dirty] Worker {worker.pid} initialized apps: {list(worker.apps.keys())}")


def dirty_worker_exit(arbiter, worker):
    """Called when a dirty worker exits."""
    print(f"[Dirty] Worker {worker.pid} exiting")


def worker_int(worker):
    """Called when a worker receives SIGINT."""
    print(f"[HTTP] Worker {worker.pid} interrupted")


def worker_exit(server, worker):
    """Called when a worker exits."""
    print(f"[HTTP] Worker {worker.pid} exited")


# =============================================================================
# Development vs Production
# =============================================================================

# Reload on code changes (development only)
reload = os.environ.get("GUNICORN_RELOAD", "false").lower() == "true"

# Preload app for faster worker startup (production)
preload_app = os.environ.get("GUNICORN_PRELOAD", "false").lower() == "true"
