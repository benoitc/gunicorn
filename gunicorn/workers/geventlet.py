# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

from __future__ import with_statement

import collections
import errno
import traceback

import eventlet
import eventlet.debug

from eventlet.green import os
from eventlet.green import socket
from eventlet import greenio
from eventlet import greenlet
from eventlet import greenpool
from eventlet import greenthread

from gunicorn import util
from gunicorn import arbiter
from gunicorn.workers.async import AsyncWorker, ALREADY_HANDLED
from gunicorn.http.tee import UnexpectedEOF

eventlet.debug.hub_exceptions(True)

class EventletWorker(AsyncWorker):

    def __init__(self, *args, **kwargs):
        super(EventletWorker, self).__init__(*args, **kwargs)
        if eventlet.version_info < (0,9,7):
            raise RuntimeError("You need eventlet >= 0.9.7")

    def init_process(self):
        eventlet.monkey_patch(all=False, socket=True, select=True)
        self.socket = greenio.GreenSocket(self.socket)
        super(EventletWorker, self).init_process()

    def run(self):
        self.init_process()
        self.socket.setblocking(1)

        pool = greenpool.GreenPool(self.worker_connections)
        acceptor = greenthread.spawn(self.acceptor, pool)
        
        while True:
            self.notify()
            
            if self.ppid != os.getppid():
                self.log.info("Parent changed, shutting down: %s" % self)
                greenthread.kill(acceptor, eventlet.StopServe)
                break
            
            eventlet.sleep(0.1)            

        with evenlet.Timeout(self.timeout, False):
            pool.waitall()

    def acceptor(self, pool):
        server_gt = greenthread.getcurrent()
        while True:
            try:
                conn, addr = self.socket.accept()
                gt = pool.spawn(self.handle, conn, addr)
                gt.link(self.cleanup, conn)
                conn, addr, gt = None, None, None
            except eventlet.StopServe:
                return

    def cleanup(self, thread, conn):
        try:
            try:
                thread.wait()
            finally:
                conn.close()
        except greenlet.GreenletExit:
            pass
        except Exception:
            self.log.exception("Unhandled exception in worker.")

