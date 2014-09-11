# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import re

class SubDomainApp:
    """WSGI application to delegate requests based on domain name.
"""
    def __init__(self, mapping):
        self.mapping = mapping

    def __call__(self, environ, start_response):
        host = environ.get("HTTP_HOST", "")
        host = host.split(":")[0]  # strip port

        for pattern, app in self.mapping:
            if re.match("^" + pattern + "$", host):
                return app(environ, start_response)
        else:
            start_response("404 Not Found", [])
            return [b""]

def hello(environ, start_response):
    start_response("200 OK", [("Content-Type", "text/plain")])
    return [b"Hello, world\n"]

def bye(environ, start_response):
    start_response("200 OK", [("Content-Type", "text/plain")])
    return [b"Goodbye!\n"]

app = SubDomainApp([
    ("localhost", hello),
    (".*", bye)
])
