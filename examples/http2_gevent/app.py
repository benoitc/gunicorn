"""
Example WSGI application demonstrating HTTP/2 with gevent worker.

This application showcases various HTTP/2 features including:
- Basic request/response handling
- Large file transfers (streaming)
- Concurrent requests (multiplexing)
- Server push simulation
"""

import json
import time


def app(environ, start_response):
    """WSGI application for HTTP/2 demonstration."""
    path = environ.get('PATH_INFO', '/')
    method = environ.get('REQUEST_METHOD', 'GET')

    # Root endpoint
    if path == '/':
        body = b'Hello from HTTP/2 with Gevent!'
        status = '200 OK'
        content_type = 'text/plain; charset=utf-8'

    # Health check
    elif path == '/health':
        body = b'OK'
        status = '200 OK'
        content_type = 'text/plain'

    # Echo endpoint - returns the request body
    elif path == '/echo':
        content_length = int(environ.get('CONTENT_LENGTH', 0) or 0)
        body = environ['wsgi.input'].read(content_length)
        status = '200 OK'
        content_type = 'application/octet-stream'

    # JSON endpoint - returns request info as JSON
    elif path == '/info':
        info = {
            'method': method,
            'path': path,
            'protocol': environ.get('SERVER_PROTOCOL', 'unknown'),
            'http_version': environ.get('HTTP_VERSION', '1.1'),
            'server': 'gunicorn with gevent + HTTP/2',
            'headers': {
                k: v for k, v in environ.items()
                if k.startswith('HTTP_')
            }
        }
        body = json.dumps(info, indent=2).encode('utf-8')
        status = '200 OK'
        content_type = 'application/json'

    # Large response for testing streaming/flow control
    elif path == '/large':
        # Return 1MB of data
        size = 1024 * 1024
        body = b'X' * size
        status = '200 OK'
        content_type = 'application/octet-stream'

    # Streaming response using generator
    elif path == '/stream':
        def generate():
            for i in range(10):
                yield f'data: chunk {i}\n\n'.encode('utf-8')
                # Small delay to simulate streaming
                time.sleep(0.1)

        start_response('200 OK', [
            ('Content-Type', 'text/event-stream'),
            ('Cache-Control', 'no-cache'),
        ])
        return generate()

    # Concurrent test endpoint with configurable delay
    elif path.startswith('/delay'):
        query = environ.get('QUERY_STRING', '')
        try:
            delay = float(query.split('=')[1]) if '=' in query else 0.5
            delay = min(delay, 5.0)  # Cap at 5 seconds
        except (ValueError, IndexError):
            delay = 0.5

        # Use gevent sleep for cooperative yielding
        try:
            import gevent
            gevent.sleep(delay)
        except ImportError:
            time.sleep(delay)

        body = f'Delayed response after {delay}s'.encode('utf-8')
        status = '200 OK'
        content_type = 'text/plain'

    # HTTP/2 priority information (if available)
    elif path == '/priority':
        priority_info = {
            'weight': environ.get('HTTP2_PRIORITY_WEIGHT', 'N/A'),
            'depends_on': environ.get('HTTP2_PRIORITY_DEPENDS_ON', 'N/A'),
            'exclusive': environ.get('HTTP2_PRIORITY_EXCLUSIVE', 'N/A'),
        }
        body = json.dumps(priority_info, indent=2).encode('utf-8')
        status = '200 OK'
        content_type = 'application/json'

    # 404 for unknown paths
    else:
        body = b'Not Found'
        status = '404 Not Found'
        content_type = 'text/plain'

    response_headers = [
        ('Content-Type', content_type),
        ('Content-Length', str(len(body))),
        ('X-Worker-Type', 'gevent'),
    ]

    start_response(status, response_headers)
    return [body]


# Allow running directly for testing
if __name__ == '__main__':
    from wsgiref.simple_server import make_server
    server = make_server('localhost', 8000, app)
    print('Test server running on http://localhost:8000')
    server.serve_forever()
