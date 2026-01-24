#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
WSGI app for integration benchmarking of the dirty pool.

This simple WSGI application calls the dirty pool and returns results.
Use with gunicorn for end-to-end benchmarking that includes HTTP overhead.

Example:
    gunicorn benchmarks.dirty_bench_wsgi:app \
        --workers 4 \
        --dirty-app benchmarks.dirty_bench_app:BenchmarkApp \
        --dirty-workers 2 \
        --bind 127.0.0.1:8000
"""

import json
from urllib.parse import parse_qs

from gunicorn.dirty import get_dirty_client


# Default benchmark app path
BENCHMARK_APP = "benchmarks.dirty_bench_app:BenchmarkApp"


def app(environ, start_response):
    """
    WSGI application that calls dirty pool tasks.

    Query parameters:
        action: Task action to call (default: sleep_task)
        duration: Duration in ms for sleep/cpu tasks (default: 10)
        sleep: Sleep duration for mixed_task (default: 50)
        cpu: CPU duration for mixed_task (default: 50)
        size: Payload size in bytes for payload_task (default: 100)
        intensity: CPU intensity for cpu/mixed tasks (default: 1.0)
        app: Dirty app path (default: benchmarks.dirty_bench_app:BenchmarkApp)

    Endpoints:
        /              - Default sleep_task
        /sleep         - sleep_task with ?duration=N
        /cpu           - cpu_task with ?duration=N&intensity=N
        /mixed         - mixed_task with ?sleep=N&cpu=N
        /payload       - payload_task with ?size=N
        /echo          - echo_task (POST body echoed)
        /stats         - Get accumulated stats
        /health        - Health check
    """
    path = environ.get('PATH_INFO', '/')
    method = environ.get('REQUEST_METHOD', 'GET')
    query = parse_qs(environ.get('QUERY_STRING', ''))

    # Helper to get query params with defaults
    def get_param(name, default, type_fn=int):
        values = query.get(name, [])
        if values:
            try:
                return type_fn(values[0])
            except (ValueError, TypeError):
                return default
        return default

    # Get app path from query or use default
    app_path = query.get('app', [BENCHMARK_APP])[0]

    try:
        client = get_dirty_client()

        # Route based on path
        if path in ('/', '/sleep'):
            duration = get_param('duration', 10)
            result = client.execute(app_path, "sleep_task", duration)

        elif path == '/cpu':
            duration = get_param('duration', 100)
            intensity = get_param('intensity', 1.0, float)
            result = client.execute(app_path, "cpu_task", duration, intensity)

        elif path == '/mixed':
            sleep_ms = get_param('sleep', 50)
            cpu_ms = get_param('cpu', 50)
            intensity = get_param('intensity', 1.0, float)
            result = client.execute(app_path, "mixed_task", sleep_ms, cpu_ms,
                                    intensity)

        elif path == '/payload':
            size = get_param('size', 100)
            duration = get_param('duration', 0)
            result = client.execute(app_path, "payload_task", size, duration)

        elif path == '/echo':
            # Read request body for echo
            try:
                content_length = int(environ.get('CONTENT_LENGTH', 0))
            except (ValueError, TypeError):
                content_length = 0

            if content_length > 0:
                body = environ['wsgi.input'].read(content_length)
                try:
                    payload = json.loads(body.decode('utf-8'))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    payload = body.decode('utf-8', errors='replace')
            else:
                payload = ""

            result = client.execute(app_path, "echo_task", payload)

        elif path == '/stats':
            result = client.execute(app_path, "stats")

        elif path == '/reset':
            result = client.execute(app_path, "reset_stats")

        elif path == '/health':
            result = client.execute(app_path, "health")

        else:
            # Unknown path - return 404
            status = '404 Not Found'
            body = json.dumps({"error": f"Unknown path: {path}"}).encode()
            headers = [
                ('Content-Type', 'application/json'),
                ('Content-Length', str(len(body))),
            ]
            start_response(status, headers)
            return [body]

        # Success response
        status = '200 OK'
        body = json.dumps(result).encode()
        headers = [
            ('Content-Type', 'application/json'),
            ('Content-Length', str(len(body))),
        ]
        start_response(status, headers)
        return [body]

    except Exception as e:
        # Error response
        status = '500 Internal Server Error'
        error_msg = {"error": str(e), "type": type(e).__name__}
        body = json.dumps(error_msg).encode()
        headers = [
            ('Content-Type', 'application/json'),
            ('Content-Length', str(len(body))),
        ]
        start_response(status, headers)
        return [body]


# Gunicorn configuration for integration testing
# These can be overridden on the command line

# Example gunicorn invocation:
# gunicorn benchmarks.dirty_bench_wsgi:app \
#     -c benchmarks/dirty_bench_gunicorn.py \
#     --dirty-app benchmarks.dirty_bench_app:BenchmarkApp \
#     --dirty-workers 2


def post_fork(server, worker):
    """Hook called after worker fork."""
    pass
