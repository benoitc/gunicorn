# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.
#
# Run this application with:
#
#   $ gunicorn multiapp:app
#
# And then visit:
#
#   http://127.0.0.1:8000/app1url
#   http://127.0.0.1:8000/app2url
#   http://127.0.0.1:8000/this_is_a_404
#

try:
    from routes import Mapper
except ImportError:
    print("This example requires Routes to be installed")

# Obviously you'd import your app callables
# from different places...
from test import app as app1
from test import app as app2


class Application(object):
    def __init__(self):
        self.map = Mapper()
        self.map.connect('app1', '/app1url', app=app1)
        self.map.connect('app2', '/app2url', app=app2)

    def __call__(self, environ, start_response):
        match = self.map.routematch(environ=environ)
        if not match:
            return self.error404(environ, start_response)
        return match[0]['app'](environ, start_response)

    def error404(self, environ, start_response):
        html = b"""\
        <html>
          <head>
            <title>404 - Not Found</title>
          </head>
          <body>
            <h1>404 - Not Found</h1>
          </body>
        </html>
        """
        headers = [
            ('Content-Type', 'text/html'),
            ('Content-Length', str(len(html)))
        ]
        start_response('404 Not Found', headers)
        return [html]

app = Application()
