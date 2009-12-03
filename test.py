
from gunicorn.httpserver import WSGIServer




def simple_app(environ, start_response):
    """Simplest possible application object"""
    status = '200 OK'
    response_headers = [('Content-type','text/plain')]
    start_response(status, response_headers)
    return ['Hello world!\n']

if __name__ == '__main__':
    server = WSGIServer(("127.0.0.1", 8000), 1, simple_app)
    server.run()