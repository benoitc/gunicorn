#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# Simple WSGI app for benchmarking

def application(environ, start_response):
    """Basic hello world response."""
    path = environ.get('PATH_INFO', '/')

    if path == '/large':
        body = b'X' * 65536  # 64KB
    else:
        body = b'Hello, World!'

    status = '200 OK'
    headers = [
        ('Content-Type', 'text/plain'),
        ('Content-Length', str(len(body))),
    ]
    start_response(status, headers)
    return [body]
