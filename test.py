from gunicorn.httpserver import HTTPServer

if __name__ == '__main__':
    server = HTTPServer(None, 4)
    server.join()