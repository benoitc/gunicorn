"""
Gunicorn configuration for Dirty Workers Example

Run with:
    cd examples/dirty_example
    gunicorn wsgi_app:app -c gunicorn_conf.py
"""

# Basic settings
bind = "127.0.0.1:8000"
workers = 2
worker_class = "sync"
timeout = 30

# Dirty arbiter settings
dirty_apps = [
    "examples.dirty_example.dirty_app:MLApp",
    "examples.dirty_example.dirty_app:ComputeApp",
]
dirty_workers = 2
dirty_timeout = 300
dirty_graceful_timeout = 30

# Logging
loglevel = "info"
accesslog = "-"
errorlog = "-"


# Hooks for demonstration
def on_starting(server):
    print("=== Gunicorn starting ===")


def when_ready(server):
    print("=== Gunicorn ready ===")
    print(f"HTTP workers: {server.num_workers}")
    print(f"Dirty workers: {server.cfg.dirty_workers}")
    print(f"Dirty apps: {server.cfg.dirty_apps}")


def on_dirty_starting(arbiter):
    print("=== Dirty arbiter starting ===")


def dirty_post_fork(arbiter, worker):
    print(f"=== Dirty worker {worker.pid} forked ===")


def dirty_worker_init(worker):
    print(f"=== Dirty worker {worker.pid} initialized apps ===")


def dirty_worker_exit(arbiter, worker):
    print(f"=== Dirty worker {worker.pid} exiting ===")
