# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.
#
# Simple example of readline, reading from a stream then echoing the response
#
# Usage:
#
# Launch a server with the app in a terminal
#
#     $ gunicorn -w3 readline:app
#
# Then in another terminal launch the following command:
#
#     $ curl -XPOST -d'test\r\ntest2\r\n' -H"Transfer-Encoding: Chunked" http://localhost:8000



from gunicorn import __version__


def app(environ, start_response):
    """Simplest possible application object"""
    status = '200 OK'

    response_headers = [
        ('Content-type', 'text/plain'),
        ('Transfer-Encoding', "chunked"),
        ('X-Gunicorn-Version', __version__),
        #("Test", "test тест"),
    ]
    start_response(status, response_headers)

    body = environ['wsgi.input']

    lines = []
    while True:
        line = body.readline()
        if line == b"":
            break
        print(line)
        lines.append(line)

    return iter(lines)