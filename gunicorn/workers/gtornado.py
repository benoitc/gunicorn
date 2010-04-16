# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

from tornado.httpserver import HTTPServer
from tornado.ioloop import IOLoop, PeriodicCallback

from gunicorn.workers.base import Worker

class TornadoWorker(Worker):
    
    def watchdog(self):
        self.notify()
            
        if self.ppid != os.getppid():
            self.log.info("Parent changed, shutting down: %s" % self)
            self.ioloop.stop()
    
    def run(self):
        self.socket.setblocking(0)
        self.ioloop = IOLoop.instance()
        PeriodicCallback(self.watchdog, 1000, io_loop=self.ioloop).start()

        server = HTTPServer(self.app, io_loop=self.ioloop)
        server._socket = self.socket
        server.start(num_processes=1)

        self.ioloop.start()
