#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
WSGI and Dirty applications for per-app worker allocation testing.

Contains:
- A WSGI app that can make dirty client requests
- A lightweight dirty app (loads on all workers)
- A heavy dirty app (limited to 2 workers via class attribute)
- A config-limited app (limited to 1 worker via config)
"""

import json
import os

from gunicorn.dirty.app import DirtyApp


def application(environ, start_response):
    """
    WSGI application that invokes dirty apps and returns worker info.

    Routes:
    - GET /lightweight/ping - Call LightweightApp.ping()
    - GET /heavy/predict/<data> - Call HeavyApp.predict(data)
    - GET /config_limited/info - Call ConfigLimitedApp.get_info()
    - GET /status - Get overall status
    """
    path = environ.get('PATH_INFO', '/')
    method = environ.get('REQUEST_METHOD', 'GET')

    if method != 'GET':
        start_response('405 Method Not Allowed', [('Content-Type', 'text/plain')])
        return [b'Method not allowed']

    # Import dirty client here to avoid import at module load
    from gunicorn.dirty import get_dirty_client

    try:
        client = get_dirty_client()

        if path == '/status':
            start_response('200 OK', [('Content-Type', 'application/json')])
            return [json.dumps({"status": "ok"}).encode()]

        elif path == '/lightweight/ping':
            result = client.execute("app:LightweightApp", "ping")
            start_response('200 OK', [('Content-Type', 'application/json')])
            return [json.dumps(result).encode()]

        elif path.startswith('/heavy/predict/'):
            data = path.split('/')[-1]
            result = client.execute("app:HeavyApp", "predict", data)
            start_response('200 OK', [('Content-Type', 'application/json')])
            return [json.dumps(result).encode()]

        elif path == '/heavy/get_worker_id':
            result = client.execute("app:HeavyApp", "get_worker_id")
            start_response('200 OK', [('Content-Type', 'application/json')])
            return [json.dumps({"worker_id": result}).encode()]

        elif path == '/config_limited/info':
            result = client.execute("app:ConfigLimitedApp", "get_info")
            start_response('200 OK', [('Content-Type', 'application/json')])
            return [json.dumps(result).encode()]

        elif path == '/config_limited/get_worker_id':
            result = client.execute("app:ConfigLimitedApp", "get_worker_id")
            start_response('200 OK', [('Content-Type', 'application/json')])
            return [json.dumps({"worker_id": result}).encode()]

        elif path == '/lightweight/get_worker_id':
            result = client.execute("app:LightweightApp", "get_worker_id")
            start_response('200 OK', [('Content-Type', 'application/json')])
            return [json.dumps({"worker_id": result}).encode()]

        else:
            start_response('404 Not Found', [('Content-Type', 'text/plain')])
            return [b'Not found']

    except Exception as e:
        start_response('500 Internal Server Error', [('Content-Type', 'application/json')])
        return [json.dumps({"error": str(e), "type": type(e).__name__}).encode()]


class LightweightApp(DirtyApp):
    """
    A lightweight app that should load on ALL dirty workers.

    workers=None (default) means all workers load this app.
    """

    def __init__(self):
        self.initialized = False
        self.worker_id = None
        self.call_count = 0

    def init(self):
        self.initialized = True
        self.worker_id = os.getpid()

    def ping(self):
        """Simple ping action."""
        self.call_count += 1
        return {
            "pong": True,
            "worker_id": self.worker_id,
            "call_count": self.call_count,
        }

    def get_worker_id(self):
        """Return the worker ID that loaded this app."""
        return self.worker_id

    def close(self):
        pass


class HeavyApp(DirtyApp):
    """
    A heavy app that uses the workers class attribute to limit allocation.

    workers=2 means only 2 dirty workers will load this app.
    This simulates a large ML model that shouldn't be replicated everywhere.
    """
    workers = 2  # Only 2 workers should load this app

    def __init__(self):
        self.initialized = False
        self.worker_id = None
        self.model_data = None

    def init(self):
        self.initialized = True
        self.worker_id = os.getpid()
        # Simulate loading a heavy model
        self.model_data = {"loaded": True, "worker": self.worker_id}

    def predict(self, data):
        """Simulate model prediction."""
        return {
            "prediction": f"result_for_{data}",
            "worker_id": self.worker_id,
        }

    def get_worker_id(self):
        """Return the worker ID that loaded this app."""
        return self.worker_id

    def close(self):
        self.model_data = None


class ConfigLimitedApp(DirtyApp):
    """
    An app whose worker limit is specified in config (not class attribute).

    The config will specify this app as "app:ConfigLimitedApp:1" to limit
    it to a single worker.
    """

    def __init__(self):
        self.initialized = False
        self.worker_id = None

    def init(self):
        self.initialized = True
        self.worker_id = os.getpid()

    def get_info(self):
        """Get app info."""
        return {
            "app": "ConfigLimitedApp",
            "worker_id": self.worker_id,
        }

    def get_worker_id(self):
        """Return the worker ID that loaded this app."""
        return self.worker_id

    def close(self):
        pass
