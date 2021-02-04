# -*- coding: utf-8 -
#
# An example of how to pass information from the command line to
# a WSGI app. Only applies to the native WSGI workers used by
# Gunicorn sync (default) workers.
#
#   $ gunicorn 'alt_spec:load(arg)'
#
# Single quoting is generally necessary for shell escape semantics.
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

def load(arg):
    def app(environ, start_response):
        data = b'Hello, %s!\n' % arg
        status = '200 OK'
        response_headers = [
            ('Content-type', 'text/plain'),
            ('Content-Length', str(len(data)))
        ]
        start_response(status, response_headers)
        return iter([data])
    return app
