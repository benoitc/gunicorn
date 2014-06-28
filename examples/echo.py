# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.
#
# Example code from Eventlet sources

import os
import pprint
from wsgiref.validate import validator
import sys

from gunicorn import __version__
#@validator
def app(environ, start_response):
    """Simplest possible application object"""

    errors = environ['wsgi.errors']
#    pprint.pprint(('ENVIRON', environ), stream=errors)

    print(environ)
    if environ['REQUEST_METHOD'].upper() != 'POST':
        data = b'Hello, World!\n'
    else:
        data = environ['wsgi.input'].read()


    status = '200 OK'

    response_headers = [
        ('Content-type','text/plain'),
        ('Content-Length', str(len(data))),
        ('X-Gunicorn-Version', __version__),
        ("Test", "test тест"),
    ]
    start_response(status, response_headers)
    return iter([data])
