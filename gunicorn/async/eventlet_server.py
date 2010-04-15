# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

from __future__ import with_statement

import errno

import collections
import eventlet
from eventlet.green import os
from eventlet.green import socket
from eventlet import greenio
from eventlet.hubs import trampoline
from eventlet.timeout import Timeout

from gunicorn import util
from gunicorn import arbiter
from gunicorn.async.base import KeepaliveWorker

        
class EventletWorker(KeepaliveWorker):

    def init_process(self):
        super(EventletWorker, self).init_process()
        self.pool = eventlet.GreenPool(self.worker_connections)
  
    def accept(self):
        with Timeout(0.1, False):
            try:
                client, addr = self.socket.accept()
                self.pool.spawn_n(self.handle, client, addr)
            except socket.error, e:
                if e[0] in (errno.EWOULDBLOCK, errno.EAGAIN, errno.ECONNABORTED):
                    return
                raise


class EventletArbiter(arbiter.Arbiter):

    @classmethod
    def setup(cls):
        import eventlet
        if eventlet.version_info < (0,9,7):
            raise RuntimeError("You need eventlet >= 0.9.7")
        eventlet.monkey_patch(all=False, socket=True, select=True, thread=True)
        
    def init_worker(self, worker_age, pid, listener, app, timeout, conf):
        return EventletWorker(worker_age, pid, listener, app, timeout, conf)
