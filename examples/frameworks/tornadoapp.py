# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.
#
# Run with:
#
#   $ gunicorn -k tornado tornadoapp:app
#

from datetime import timedelta

from tornado.web import Application, RequestHandler, asynchronous
from tornado.ioloop import IOLoop

class MainHandler(RequestHandler):
    def get(self):
        self.write("Hello, world")

class LongPollHandler(RequestHandler):
    @asynchronous
    def get(self):
        lines = ['line 1\n', 'line 2\n']

        def send():
            try:
                self.write(lines.pop(0))
                self.flush()
            except:
                self.finish()
            else:
                IOLoop.instance().add_timeout(timedelta(0, 20), send)
        send()

app = Application([
    (r"/", MainHandler),
    (r"/longpoll", LongPollHandler)
])
