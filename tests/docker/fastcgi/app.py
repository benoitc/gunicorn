"""
Test WSGI application for FastCGI protocol integration tests.

This application provides various endpoints to test different aspects
of the FastCGI binary protocol when proxied through nginx.
"""

import json


def application(environ, start_response):
    """Main WSGI application entry point."""
    path = environ.get('PATH_INFO', '/')
    method = environ.get('REQUEST_METHOD', 'GET')

    # Route to appropriate handler
    if path == '/':
        return handle_root(environ, start_response)
    elif path == '/echo':
        return handle_echo(environ, start_response)
    elif path == '/headers':
        return handle_headers(environ, start_response)
    elif path == '/environ':
        return handle_environ(environ, start_response)
    elif path.startswith('/error/'):
        return handle_error(environ, start_response, path)
    elif path == '/large':
        return handle_large(environ, start_response)
    elif path == '/json':
        return handle_json(environ, start_response)
    elif path == '/query':
        return handle_query(environ, start_response)
    else:
        return handle_not_found(environ, start_response)


def handle_root(environ, start_response):
    """Basic root endpoint."""
    status = '200 OK'
    headers = [('Content-Type', 'text/plain')]
    start_response(status, headers)
    return [b'Hello from gunicorn FastCGI!\n']


def handle_echo(environ, start_response):
    """Echo back the request body."""
    try:
        content_length = int(environ.get('CONTENT_LENGTH', 0))
    except (ValueError, TypeError):
        content_length = 0

    body = b''
    if content_length > 0:
        body = environ['wsgi.input'].read(content_length)

    status = '200 OK'
    headers = [
        ('Content-Type', 'application/octet-stream'),
        ('Content-Length', str(len(body)))
    ]
    start_response(status, headers)
    return [body]


def handle_headers(environ, start_response):
    """Return received HTTP headers as JSON."""
    headers_dict = {}
    for key, value in environ.items():
        if key.startswith('HTTP_'):
            # Convert HTTP_X_CUSTOM_HEADER to X-Custom-Header
            header_name = key[5:].replace('_', '-').title()
            headers_dict[header_name] = value

    # Also include some special headers
    if 'CONTENT_TYPE' in environ:
        headers_dict['Content-Type'] = environ['CONTENT_TYPE']
    if 'CONTENT_LENGTH' in environ:
        headers_dict['Content-Length'] = environ['CONTENT_LENGTH']

    body = json.dumps(headers_dict, indent=2).encode('utf-8')
    status = '200 OK'
    headers = [
        ('Content-Type', 'application/json'),
        ('Content-Length', str(len(body)))
    ]
    start_response(status, headers)
    return [body]


def handle_environ(environ, start_response):
    """Return WSGI environ variables as JSON."""
    # Filter to serializable values
    safe_environ = {}
    skip_keys = {'wsgi.input', 'wsgi.errors', 'wsgi.file_wrapper'}

    for key, value in environ.items():
        if key in skip_keys:
            continue
        try:
            # Test if value is JSON serializable
            json.dumps(value)
            safe_environ[key] = value
        except (TypeError, ValueError):
            safe_environ[key] = str(value)

    body = json.dumps(safe_environ, indent=2).encode('utf-8')
    status = '200 OK'
    headers = [
        ('Content-Type', 'application/json'),
        ('Content-Length', str(len(body)))
    ]
    start_response(status, headers)
    return [body]


def handle_error(environ, start_response, path):
    """Return specified HTTP error code."""
    try:
        code = int(path.split('/')[-1])
    except ValueError:
        code = 500

    status_messages = {
        400: 'Bad Request',
        401: 'Unauthorized',
        403: 'Forbidden',
        404: 'Not Found',
        500: 'Internal Server Error',
        502: 'Bad Gateway',
        503: 'Service Unavailable',
    }

    message = status_messages.get(code, 'Error')
    status = f'{code} {message}'
    body = json.dumps({'error': message, 'code': code}).encode('utf-8')

    headers = [
        ('Content-Type', 'application/json'),
        ('Content-Length', str(len(body)))
    ]
    start_response(status, headers)
    return [body]


def handle_large(environ, start_response):
    """Return a 1MB response body for testing large responses."""
    # Generate 1MB of data (1024 * 1024 bytes)
    chunk_size = 1024
    num_chunks = 1024
    chunk = b'X' * chunk_size

    status = '200 OK'
    headers = [
        ('Content-Type', 'application/octet-stream'),
        ('Content-Length', str(chunk_size * num_chunks))
    ]
    start_response(status, headers)

    # Return as generator for streaming
    def generate():
        for _ in range(num_chunks):
            yield chunk

    return generate()


def handle_json(environ, start_response):
    """Handle JSON POST requests."""
    try:
        content_length = int(environ.get('CONTENT_LENGTH', 0))
    except (ValueError, TypeError):
        content_length = 0

    if content_length > 0:
        body = environ['wsgi.input'].read(content_length)
        try:
            data = json.loads(body.decode('utf-8'))
            response = {'received': data, 'status': 'ok'}
        except json.JSONDecodeError:
            response = {'error': 'Invalid JSON', 'status': 'error'}
    else:
        response = {'error': 'No body', 'status': 'error'}

    body = json.dumps(response).encode('utf-8')
    status = '200 OK'
    headers = [
        ('Content-Type', 'application/json'),
        ('Content-Length', str(len(body)))
    ]
    start_response(status, headers)
    return [body]


def handle_query(environ, start_response):
    """Return query string parameters as JSON."""
    from urllib.parse import parse_qs
    query_string = environ.get('QUERY_STRING', '')
    params = parse_qs(query_string)

    # Convert lists to single values where appropriate
    simple_params = {k: v[0] if len(v) == 1 else v for k, v in params.items()}

    body = json.dumps(simple_params).encode('utf-8')
    status = '200 OK'
    headers = [
        ('Content-Type', 'application/json'),
        ('Content-Length', str(len(body)))
    ]
    start_response(status, headers)
    return [body]


def handle_not_found(environ, start_response):
    """Handle 404 for unknown paths."""
    body = json.dumps({'error': 'Not Found', 'path': environ.get('PATH_INFO')}).encode('utf-8')
    status = '404 Not Found'
    headers = [
        ('Content-Type', 'application/json'),
        ('Content-Length', str(len(body)))
    ]
    start_response(status, headers)
    return [body]
