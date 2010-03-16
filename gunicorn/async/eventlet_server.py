# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import errno

import collections
import eventlet
from eventlet.green import os
from eventlet.green import socket
from eventlet import greenio
from eventlet.hubs import trampoline

from gunicorn import util
from gunicorn import arbiter
from gunicorn.async.base import KeepaliveWorker

__original_GreenPipe__ = greenio.GreenPipe

class _GreenPipe(__original_GreenPipe__):

    def tell(self):
        return self.fd.tell()

    def seek(self, offset, whence=0):
        fd = self.fd
        self.read()
        fd.seek(offset, whence)

_eventlet_patched = None
def patch_eventlet():
    global _eventlet_patched
    if _eventlet_patched:
        return
    greenio.GreenPipe = _GreenPipe
    _eventlet_patched = True
        
class EventletWorker(KeepaliveWorker):

    def init_process(self):
        super(EventletWorker, self).init_process()
        self.pool = eventlet.GreenPool(self.worker_connections)
  
    def accept(self):
        try:
            client, addr = self.socket.accept()
            self.pool.spawn_n(self.handle, client, addr)
        except socket.error, e:
            if e[0] in (errno.EWOULDBLOCK, errno.EAGAIN):
                return
            raise


class EventletArbiter(arbiter.Arbiter):

    @classmethod
    def setup(cls):
        import eventlet
        if eventlet.version_info < (0,9,7):
            raise RuntimeError("You need eventlet >= 0.9.7")
        patch_eventlet()
        eventlet.monkey_patch(all=True)
        
    def init_worker(self, worker_age, pid, listener, app, timeout, conf):
        return EventletWorker(worker_age, pid, listener, app, timeout, conf)
