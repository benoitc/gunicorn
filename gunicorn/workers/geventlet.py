# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

from __future__ import with_statement

import errno
import socket

import eventlet
from eventlet.green import os
from eventlet import hubs
from eventlet.greenio import GreenSocket


from gunicorn.workers.async import AsyncWorker

class EventletWorker(AsyncWorker):

    @classmethod
    def setup(cls):
        import eventlet
        if eventlet.version_info < (0,9,7):
            raise RuntimeError("You need eventlet >= 0.9.7")
        eventlet.monkey_patch(os=False)
    
    def init_process(self):
        hubs.use_hub()
        super(EventletWorker, self).init_process()
        
    def timeout_ctx(self):
        return eventlet.Timeout(self.cfg.keepalive, False)

    def acceptor(self, pool):
        try:
            while self.alive:
                try:
                    client, addr = self.socket.accept()
                    pool.spawn_n(self.handle, client, addr)
                except socket.error, e:
                    if e[0] not in (errno.EAGAIN, errno.ECONNABORTED):
                        raise

                if pool.running() > self.worker_connections:
                    continue
                           
                try:
                    hubs.trampoline(self.socket.fileno(), read=True,
                        timeout=self.timeout)
                except eventlet.Timeout:
                    pass
        except eventlet.StopServer:
            pool.waitall()

    def run(self):
        self.socket = GreenSocket(family_or_realsock=self.socket.sock)
        self.socket.setblocking(1)

        pool = eventlet.GreenPool(self.worker_connections)

        acceptor = eventlet.spawn(self.acceptor, pool)

        try:
            while self.alive:
                self.notify()
            
                if self.ppid != os.getppid():
                    self.log.info("Parent changed, shutting down: %s" % self)
                    server.stop()
                    break
                eventlet.sleep(0.1) 
        except KeyboardInterrupt:
            pass

        with eventlet.Timeout(self.timeout, False):
            eventlet.kill(acceptor, eventlet.StopServe)

