"""Test WSGI application for HTTP/2 Docker integration tests."""

import json


def app(environ, start_response):
    """Simple WSGI app for testing HTTP/2 functionality."""
    path = environ.get('PATH_INFO', '/')
    method = environ.get('REQUEST_METHOD', 'GET')

    if path == '/':
        body = b'Hello HTTP/2!'
        status = '200 OK'
        content_type = 'text/plain'

    elif path == '/health':
        body = b'OK'
        status = '200 OK'
        content_type = 'text/plain'

    elif path == '/echo':
        # Echo back the request body
        content_length = int(environ.get('CONTENT_LENGTH', 0) or 0)
        body = environ['wsgi.input'].read(content_length)
        status = '200 OK'
        content_type = 'application/octet-stream'

    elif path == '/headers':
        # Return all HTTP headers as JSON
        headers = {}
        for key, value in environ.items():
            if key.startswith('HTTP_'):
                headers[key] = value
        # Also include some important non-HTTP_ headers
        for key in ['CONTENT_TYPE', 'CONTENT_LENGTH', 'REQUEST_METHOD',
                    'PATH_INFO', 'QUERY_STRING', 'SERVER_PROTOCOL']:
            if key in environ:
                headers[key] = str(environ[key])
        body = json.dumps(headers, indent=2).encode('utf-8')
        status = '200 OK'
        content_type = 'application/json'

    elif path == '/version':
        # Return HTTP version info
        server_protocol = environ.get('SERVER_PROTOCOL', 'HTTP/1.1')
        body = server_protocol.encode('utf-8')
        status = '200 OK'
        content_type = 'text/plain'

    elif path == '/large':
        # Return a large response (1MB) for testing streaming
        body = b'X' * (1024 * 1024)
        status = '200 OK'
        content_type = 'application/octet-stream'

    elif path == '/stream':
        # Return a streaming response
        def generate():
            for i in range(10):
                yield f'chunk-{i}\n'.encode('utf-8')

        start_response('200 OK', [
            ('Content-Type', 'text/plain'),
            ('Transfer-Encoding', 'chunked')
        ])
        return generate()

    elif path == '/status':
        # Return a specific status code based on query string
        query = environ.get('QUERY_STRING', '')
        try:
            code = int(query.split('=')[1]) if '=' in query else 200
        except (ValueError, IndexError):
            code = 200
        status_messages = {
            200: 'OK',
            201: 'Created',
            204: 'No Content',
            400: 'Bad Request',
            404: 'Not Found',
            500: 'Internal Server Error',
        }
        status = f'{code} {status_messages.get(code, "Unknown")}'
        body = f'Status: {code}'.encode('utf-8')
        content_type = 'text/plain'

    elif path == '/delay':
        # Simulate a slow response
        import time
        query = environ.get('QUERY_STRING', '')
        try:
            delay = float(query.split('=')[1]) if '=' in query else 1.0
            delay = min(delay, 5.0)  # Cap at 5 seconds
        except (ValueError, IndexError):
            delay = 1.0
        time.sleep(delay)
        body = f'Delayed {delay}s'.encode('utf-8')
        status = '200 OK'
        content_type = 'text/plain'

    elif path == '/method':
        # Return the request method
        body = method.encode('utf-8')
        status = '200 OK'
        content_type = 'text/plain'

    else:
        body = b'Not Found'
        status = '404 Not Found'
        content_type = 'text/plain'

    response_headers = [
        ('Content-Type', content_type),
        ('Content-Length', str(len(body))),
        ('X-Request-Path', path),
        ('X-Request-Method', method),
    ]

    start_response(status, response_headers)
    return [body]


# For running directly with python
if __name__ == '__main__':
    from wsgiref.simple_server import make_server
    server = make_server('localhost', 8000, app)
    print('Serving on http://localhost:8000')
    server.serve_forever()
