
from gunicorn.httpserver import WSGIServer




def app(environ, start_response):
    """Simplest possible application object"""
    data = 'Hello, World!\n'
    status = '200 OK'
    response_headers = [
        ('Content-type','text/plain'),
        ('Content-Length', len(data))
    ]
    start_response(status, response_headers)
    return [data]

if __name__ == '__main__':
    server = WSGIServer(("127.0.0.1", 8000), 1, simple_app)
    server.run()