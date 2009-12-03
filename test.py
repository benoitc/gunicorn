from gunicorn.httpserver import HTTPServer


def simple_app(environ, start_response):
    """Simplest possible application object"""
    status = '200 OK'
    response_headers = [('Content-type','text/plain')]
    start_response(status, response_headers)
    return ['Hello world!\n']

if __name__ == '__main__':
    server = HTTPServer(simple_app, 4)
    server.run()