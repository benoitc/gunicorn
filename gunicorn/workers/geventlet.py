# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

from __future__ import with_statement

import errno
import socket
import sys

import eventlet

from eventlet.green import os
from eventlet import greenlet
from eventlet import greenpool
from eventlet import greenthread
from eventlet import hubs
from eventlet.greenio import GreenSocket


from gunicorn.workers.async import AsyncWorker
from gunicorn import util


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

        
    def run(self):
        self.socket = GreenSocket(family_or_realsock=self.socket.sock)
        self.socket.setblocking(1)

        pool = eventlet.GreenPool(self.worker_connections)
        while self.alive:

            self.notify()

            try:
                client, addr = self.socket.accept()
                client.setblocking(1)
                util.close_on_exec(client)
                pool.spawn_n(self.handle, client, addr)
            except socket.error, e:
                if e[0] not in (errno.EAGAIN, errno.ECONNABORTED):
                    raise

            if pool.running() > self.worker_connections:
                continue
           
            if self.ppid != os.getppid():
                self.log.info("Parent changed, shutting down: %s" % self)
                break

            self.notify()
            
            try:
                hubs.trampoline(self.socket.fileno(), read=True,
                    timeout=self.timeout)
            except eventlet.Timeout:
                pass
