"""
Example WSGI Application that uses Dirty Workers

This demonstrates how HTTP workers can call dirty workers
for heavy operations like ML inference.

Run with:
    cd examples/dirty_example
    gunicorn wsgi_app:app -c gunicorn_conf.py
"""

import json
import os
from urllib.parse import parse_qs


def get_dirty_client():
    """Get the dirty client, with fallback for when dirty workers aren't enabled."""
    try:
        from gunicorn.dirty import get_dirty_client as _get_dirty_client
        return _get_dirty_client()
    except Exception as e:
        return None


def app(environ, start_response):
    """WSGI application that demonstrates dirty worker integration."""
    path = environ.get('PATH_INFO', '/')
    method = environ.get('REQUEST_METHOD', 'GET')

    # Parse query string
    query = parse_qs(environ.get('QUERY_STRING', ''))

    # Get dirty client
    client = get_dirty_client()

    try:
        if path == '/':
            result = {
                "message": "Dirty Workers Demo",
                "dirty_enabled": client is not None,
                "pid": os.getpid(),
                "endpoints": {
                    "/models": "List loaded models",
                    "/load?name=MODEL": "Load a model",
                    "/inference?model=NAME&data=INPUT": "Run inference",
                    "/unload?name=MODEL": "Unload a model",
                    "/fibonacci?n=NUMBER": "Compute fibonacci",
                    "/prime?n=NUMBER": "Check if prime",
                    "/stats": "Get dirty worker stats",
                }
            }

        elif path == '/models':
            if client is None:
                result = {"error": "Dirty workers not enabled"}
            else:
                result = client.execute(
                    "examples.dirty_example.dirty_app:MLApp",
                    "list_models"
                )

        elif path == '/load':
            name = query.get('name', ['model1'])[0]
            if client is None:
                result = {"error": "Dirty workers not enabled"}
            else:
                result = client.execute(
                    "examples.dirty_example.dirty_app:MLApp",
                    "load_model",
                    name
                )

        elif path == '/inference':
            model = query.get('model', ['default'])[0]
            data = query.get('data', ['test input'])[0]
            if client is None:
                result = {"error": "Dirty workers not enabled"}
            else:
                result = client.execute(
                    "examples.dirty_example.dirty_app:MLApp",
                    "inference",
                    model,
                    data
                )

        elif path == '/unload':
            name = query.get('name', ['model1'])[0]
            if client is None:
                result = {"error": "Dirty workers not enabled"}
            else:
                result = client.execute(
                    "examples.dirty_example.dirty_app:MLApp",
                    "unload_model",
                    name
                )

        elif path == '/fibonacci':
            n = int(query.get('n', ['10'])[0])
            if client is None:
                result = {"error": "Dirty workers not enabled"}
            else:
                result = client.execute(
                    "examples.dirty_example.dirty_app:ComputeApp",
                    "fibonacci",
                    n
                )

        elif path == '/prime':
            n = int(query.get('n', ['17'])[0])
            if client is None:
                result = {"error": "Dirty workers not enabled"}
            else:
                result = client.execute(
                    "examples.dirty_example.dirty_app:ComputeApp",
                    "prime_check",
                    n
                )

        elif path == '/stats':
            if client is None:
                result = {"error": "Dirty workers not enabled"}
            else:
                ml_stats = client.execute(
                    "examples.dirty_example.dirty_app:MLApp",
                    "list_models"
                )
                compute_stats = client.execute(
                    "examples.dirty_example.dirty_app:ComputeApp",
                    "stats"
                )
                result = {
                    "ml_app": ml_stats,
                    "compute_app": compute_stats,
                    "http_worker_pid": os.getpid(),
                }

        else:
            start_response('404 Not Found', [('Content-Type', 'application/json')])
            return [json.dumps({"error": "Not found"}).encode()]

        # Success response
        start_response('200 OK', [('Content-Type', 'application/json')])
        return [json.dumps(result, indent=2).encode()]

    except Exception as e:
        start_response('500 Internal Server Error', [('Content-Type', 'application/json')])
        return [json.dumps({
            "error": str(e),
            "type": type(e).__name__
        }).encode()]
