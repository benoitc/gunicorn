# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.
#
# Run with:
#
#   $ gunicorn -k tornado tornadoapp:app
#

import tornado.ioloop
import tornado.web
from tornado import gen

class MainHandler(tornado.web.RequestHandler):
    @gen.coroutine
    def get(self):
        # Your asynchronous code here
        yield gen.sleep(1)  # Example of an asynchronous operation
        self.write("Hello, World!")

def make_app():
    return tornado.web.Application([
        (r"/", MainHandler),
    ])

if __name__ == "__main__":
    app = make_app()
    app.listen(8888)
    tornado.ioloop.IOLoop.current().start()
