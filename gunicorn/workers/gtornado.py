# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import os
import sys

try:
    import tornado.web
except ImportError:
    raise RuntimeError("You need tornado installed to use this worker.")
import tornado.httpserver
from tornado.ioloop import IOLoop, PeriodicCallback
from tornado.wsgi import WSGIContainer
from gunicorn.workers.base import Worker
from gunicorn import __version__ as gversion


class TornadoWorker(Worker):

    @classmethod
    def setup(cls):
        web = sys.modules.pop("tornado.web")
        old_clear = web.RequestHandler.clear

        def clear(self):
            old_clear(self)
            self._headers["Server"] += " (Gunicorn/%s)" % gversion
        web.RequestHandler.clear = clear
        sys.modules["tornado.web"] = web

    def handle_quit(self, sig, frame):
        super(TornadoWorker, self).handle_quit(sig, frame)
        self.ioloop.stop()

    def handle_request(self):
        self.nr += 1
        if self.alive and self.nr >= self.max_requests:
            self.alive = False
            self.log.info("Autorestarting worker after current request.")
            self.ioloop.stop()

    def watchdog(self):
        if self.alive:
            self.notify()

        if self.ppid != os.getppid():
            self.log.info("Parent changed, shutting down: %s", self)
            self.ioloop.stop()

    def run(self):
        self.socket.setblocking(0)
        self.ioloop = IOLoop.instance()
        self.alive = True
        PeriodicCallback(self.watchdog, 1000, io_loop=self.ioloop).start()

        # Assume the app is a WSGI callable if its not an
        # instance of tornardo.web.Application
        app = self.wsgi
        if not isinstance(app, tornado.web.Application):
            app = WSGIContainer(app)

        # Monkey-patching HTTPConnection.finish to count the
        # number of requests being handled by Tornado. This
        # will help gunicorn shutdown the worker if max_requests
        # is exceeded.
        httpserver = sys.modules["tornado.httpserver"]
        old_connection_finish = httpserver.HTTPConnection.finish

        def finish(other):
            self.handle_request()
            old_connection_finish(other)
        httpserver.HTTPConnection.finish = finish
        sys.modules["tornado.httpserver"] = httpserver

        server = tornado.httpserver.HTTPServer(app, io_loop=self.ioloop)
        if hasattr(server, "add_socket"):  # tornado > 2.0
            server.add_socket(self.socket)
        elif hasattr(server, "_sockets"):  # tornado 2.0
            server._sockets[self.socket.fileno()] = self.socket
        else:  # tornado 1.2 or earlier
            server._socket = self.socket

        server.no_keep_alive = self.cfg.keepalive <= 0
        server.xheaders = bool(self.cfg.x_forwarded_for_header)

        server.start(num_processes=1)

        self.ioloop.start()
