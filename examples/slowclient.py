# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import sys
import time


def app(environ, start_response):
    """Application which cooperatively pauses 10 seconds before responding"""
    data = b'Hello, World!\n'
    status = '200 OK'
    response_headers = [
        ('Content-type', 'text/plain'),
        ('Content-Length', str(len(data))),
    ]
    sys.stdout.write('request received, pausing 10 seconds')
    sys.stdout.flush()
    time.sleep(10)
    start_response(status, response_headers)
    return iter([data])
