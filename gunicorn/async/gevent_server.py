# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.


import errno
import os

import gevent
from gevent import socket
from gevent.greenlet import Greenlet
from gevent.pool import Pool


from gunicorn import arbiter
from gunicorn import util
from gunicorn.async.base import KeepaliveWorker

class GEventWorker(KeepaliveWorker):
            
    def init_process(self):
        super(GEventWorker, self).init_process()
        self.pool = Pool(self.worker_connections)
        
    def accept(self):
        try:
            client, addr = self.socket.accept()
            self.pool.spawn(self.handle, client, addr)
        except socket.error, e:
            if e[0] not in (errno.EAGAIN, errno.EWOULDBLOCK):
                raise
                         
class GEventArbiter(arbiter.Arbiter):

    @classmethod
    def setup(cls):
        from gevent import monkey
        monkey.patch_all(thread=True,  ssl=True)
    
    def init_worker(self, worker_age, pid, listener, app, timeout, conf):
        return GEventWorker(worker_age, pid, listener, app, timeout, conf)
