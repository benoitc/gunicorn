# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.
#
# Example code from Eventlet sources

import os
from wsgiref.validate import validator


@validator
def app(environ, start_response):
    """Simplest possible application object"""
    status = '200 OK'
    fname = os.path.join(os.path.dirname(__file__), "hello.txt")
    f = open(fname, 'rb')

    response_headers = [
        ('Content-type', 'text/plain'),
    ]
    start_response(status, response_headers)

    return environ['wsgi.file_wrapper'](f)
