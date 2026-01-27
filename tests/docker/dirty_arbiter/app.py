#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Simple WSGI and Dirty applications for integration testing.
"""

from gunicorn.dirty.app import DirtyApp


def application(environ, start_response):
    """Simple WSGI application."""
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b'OK']


class TestDirtyApp(DirtyApp):
    """Minimal dirty app for testing process lifecycle."""

    def init(self):
        self.call_count = 0

    def ping(self):
        self.call_count += 1
        return {"pong": True, "calls": self.call_count}

    def echo(self, message):
        return {"message": message}
