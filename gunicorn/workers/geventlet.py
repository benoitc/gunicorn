# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

from __future__ import with_statement

import eventlet
import eventlet.debug

from eventlet.green import os
from eventlet import greenlet
from eventlet import greenpool
from eventlet import greenthread
from eventlet import hubs

from gunicorn.workers.async import AsyncWorker

eventlet.debug.hub_exceptions(True)

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
        self.socket.setblocking(1)

        pool = greenpool.GreenPool(self.worker_connections)
        acceptor = greenthread.spawn(self.acceptor, pool)
        
        try:
            while self.alive:
                self.notify()
                
                if self.ppid != os.getppid():
                    self.log.info("Parent changed, shutting down: %s" % self)
                    break
            
                eventlet.sleep(0.1)            
        except KeyboardInterrupt:
            pass

        # we stopped
        greenthread.kill(acceptor, eventlet.StopServe)
        with eventlet.Timeout(self.timeout, False):
            if pool.waiting():
                pool.waitall()
       
        
    def acceptor(self, pool):
        while self.alive:
            try:
                try:
                    conn, addr = self.socket.accept()
                except socket.error, e:
                    if err[0] == errno.EAGAIN:
                        sys.exc_clear()
                        return
                    raise
                pool.spawn_n(self.handle, conn, addr)
            except:
                self.log.exception("Unexpected error in acceptor. Sepuku.")
                os._exit(4)

