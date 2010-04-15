# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

from __future__ import with_statement

import errno
import os

import gevent
from gevent import monkey
from gevent import socket
from gevent.greenlet import Greenlet
from gevent.pool import Pool

from gunicorn import util
from gunicorn.workers.async import AsyncWorker

class GEventWorker(KeepaliveWorker):
    
    def init_process(self):
        monkey.patch_all()
        super(GEventWorker, self).init_process()
        
    def run(self):
        raise NotImplementedError()

    def accept(self):
        try:
            client, addr = self.socket.accept()
            self.pool.spawn(self.handle, client, addr)
        except socket.error, e:
            if e[0] in (errno.EAGAIN, errno.EWOULDBLOCK, errno.ECONNABORTED):
                return
            raise
