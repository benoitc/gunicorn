#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Test app with multiple dirty tasks for TTIN/TTOU testing."""

import json
import time

from gunicorn.dirty import DirtyApp, get_dirty_client


# Unlimited workers - runs on all dirty workers
class UnlimitedTask(DirtyApp):
    """Task that runs on all dirty workers."""

    def setup(self):
        pass

    def process(self, data):
        return {"task": "unlimited", "data": data}


# Limited to 2 workers
class LimitedTask(DirtyApp):
    """Task limited to 2 workers."""

    workers = 2

    def setup(self):
        pass

    def process(self, data):
        delay = data.get("delay", 0)
        if delay:
            time.sleep(delay)
        return {"task": "limited", "data": data}


def app(environ, start_response):
    """Simple WSGI app for testing."""
    path = environ.get('PATH_INFO', '/')

    if path == '/health':
        start_response('200 OK', [('Content-Type', 'text/plain')])
        return [b'OK']

    if path == '/unlimited':
        try:
            client = get_dirty_client()
            result = client.execute('app:UnlimitedTask', {'test': 'data'})
            start_response('200 OK', [('Content-Type', 'application/json')])
            return [json.dumps(result).encode()]
        except Exception as e:
            start_response('500 Internal Server Error',
                           [('Content-Type', 'text/plain')])
            return [str(e).encode()]

    if path == '/limited':
        try:
            client = get_dirty_client()
            result = client.execute('app:LimitedTask', {'test': 'data'})
            start_response('200 OK', [('Content-Type', 'application/json')])
            return [json.dumps(result).encode()]
        except Exception as e:
            start_response('500 Internal Server Error',
                           [('Content-Type', 'text/plain')])
            return [str(e).encode()]

    start_response('404 Not Found', [('Content-Type', 'text/plain')])
    return [b'Not Found']
