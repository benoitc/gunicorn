# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.
#
# Example code from Eventlet sources

from wsgiref.validate import validator
import sys

from gunicorn import __version__
#@validator
def app(environ, start_response):
    """Simplest possible application object"""
    data = 'Hello, World!\n'
    status = '200 OK'
#    print("print to stdout in test app")
#    sys.stderr.write("stderr, print to stderr in test app\n")
    response_headers = [
        ('Content-type','text/plain'),
        ('Content-Length', str(len(data))),
        ('X-Gunicorn-Version', __version__)
    ]
    start_response(status, response_headers)
    return iter([data])
