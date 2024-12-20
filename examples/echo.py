#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.
#
# Example code from Eventlet sources

from gunicorn import __version__


def app(environ, start_response):
    """Simplest possible application object"""

    if environ['REQUEST_METHOD'].upper() != 'POST':
        data = b'Hello, World!\n'
    else:
        data = environ['wsgi.input'].read()

    status = '200 OK'

    response_headers = [
        ('Content-type', 'text/plain'),
        ('Content-Length', str(len(data))),
        ('X-Gunicorn-Version', __version__)
    ]
    start_response(status, response_headers)
    return iter([data])
