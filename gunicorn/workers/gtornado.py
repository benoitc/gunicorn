# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import os
import sys

import tornado.web
from tornado.httpserver import HTTPServer
from tornado.ioloop import IOLoop, PeriodicCallback
from tornado.wsgi import WSGIContainer


from gunicorn.workers.base import Worker
from gunicorn import __version__ as gversion


def patch_request_handler():
    web = sys.modules.pop("tornado.web")

    old_clear = web.RequestHandler.clear

    def clear(self):
        old_clear(self)
        self._headers["Server"] += " (Gunicorn/%s)" % gversion
         
    web.RequestHandler.clear = clear
    sys.modules["tornado.web"] = web
    

class TornadoWorker(Worker):
    
    @classmethod
    def setup(cls):
        patch_request_handler()
        
    def watchdog(self):
        self.notify()
            
        if self.ppid != os.getppid():
            self.log.info("Parent changed, shutting down: %s" % self)
            self.ioloop.stop()
    
    def run(self):
        self.socket.setblocking(0)
        self.ioloop = IOLoop.instance()
        PeriodicCallback(self.watchdog, 1000, io_loop=self.ioloop).start()

        # Assume the app is a WSGI callable if its not an
        # instance of tornardo.web.Application
        if not isinstance(self.app, tornado.web.Application):
            self.app = WSGIContainer(self.app)

        server = HTTPServer(self.app, io_loop=self.ioloop)
        server._socket = self.socket
        server.start(num_processes=1)

        self.ioloop.start()
