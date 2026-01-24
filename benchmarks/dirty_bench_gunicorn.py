#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Gunicorn configuration for dirty pool integration benchmarks.

Usage:
    gunicorn -c benchmarks/dirty_bench_gunicorn.py \
        benchmarks.dirty_bench_wsgi:app
"""

# Bind address
bind = "127.0.0.1:8000"

# HTTP worker configuration
workers = 4
worker_class = "gthread"
threads = 4
worker_connections = 1000

# Dirty pool configuration
dirty_apps = ["benchmarks.dirty_bench_app:BenchmarkApp"]
dirty_workers = 4
dirty_threads = 1
dirty_timeout = 300
dirty_graceful_timeout = 30

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"

# Timeouts
timeout = 120
graceful_timeout = 30
keepalive = 2


# Lifecycle hooks

def on_dirty_starting(arbiter):
    """Called when dirty arbiter is starting."""
    print(f"[dirty] Arbiter starting (pid: {arbiter.pid})")


def dirty_post_fork(arbiter, worker):
    """Called after dirty worker fork."""
    print(f"[dirty] Worker {worker.pid} forked")


def dirty_worker_init(worker):
    """Called after dirty worker apps are initialized."""
    print(f"[dirty] Worker {worker.pid} initialized with apps: "
          f"{list(worker.apps.keys())}")


def dirty_worker_exit(arbiter, worker):
    """Called when dirty worker exits."""
    print(f"[dirty] Worker {worker.pid} exiting")
