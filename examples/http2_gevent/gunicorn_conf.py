#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Gunicorn configuration for HTTP/2 with gevent worker.

This configuration demonstrates:
- HTTP/2 protocol support with ALPN
- Gevent async worker for high concurrency
- SSL/TLS configuration
- HTTP/2 specific tuning options
"""

import os
import multiprocessing

# Server socket
bind = os.environ.get('GUNICORN_BIND', '0.0.0.0:8443')

# Worker configuration
worker_class = 'gevent'
workers = int(os.environ.get('GUNICORN_WORKERS', multiprocessing.cpu_count() * 2 + 1))
worker_connections = 1000  # Max simultaneous clients per worker

# HTTP protocols - enable HTTP/2 with HTTP/1.1 fallback
http_protocols = "h2,h1"

# SSL/TLS configuration (required for HTTP/2)
# Default paths work in Docker; override with env vars for local testing
_default_cert = '/certs/server.crt' if os.path.exists('/certs/server.crt') else 'certs/server.crt'
_default_key = '/certs/server.key' if os.path.exists('/certs/server.key') else 'certs/server.key'
certfile = os.environ.get('GUNICORN_CERTFILE', _default_cert)
keyfile = os.environ.get('GUNICORN_KEYFILE', _default_key)

# HTTP/2 specific settings
http2_max_concurrent_streams = 128  # Max streams per connection
http2_initial_window_size = 262144  # 256KB initial flow control window
http2_max_frame_size = 16384  # Default frame size (16KB)
http2_max_header_list_size = 65536  # Max header size

# Timeouts
timeout = 30  # Worker timeout
graceful_timeout = 30  # Graceful shutdown timeout
keepalive = 5  # Keep-alive connections

# Logging
loglevel = os.environ.get('GUNICORN_LOG_LEVEL', 'info')
accesslog = '-'  # Log to stdout
errorlog = '-'  # Log to stderr
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(L)s'

# Process naming
proc_name = 'gunicorn-http2-gevent'

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None


def on_starting(server):
    """Called just before the master process is initialized."""
    server.log.info("Starting HTTP/2 server with gevent worker...")
    server.log.info(f"Workers: {workers}, Connections per worker: {worker_connections}")
    server.log.info(f"HTTP/2 max streams: {http2_max_concurrent_streams}")


def when_ready(server):
    """Called just after the server is started."""
    server.log.info("HTTP/2 server is ready to accept connections")


def worker_int(worker):
    """Called when a worker receives SIGINT or SIGQUIT."""
    worker.log.info("Worker received interrupt signal")


def worker_abort(worker):
    """Called when a worker receives SIGABRT."""
    worker.log.warning("Worker aborted")
