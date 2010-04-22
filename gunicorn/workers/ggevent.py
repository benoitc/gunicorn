# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

from __future__ import with_statement

import os

import gevent
from gevent import monkey
monkey.noisy = False
from gevent import greenlet
from gevent.pool import Pool

from gunicorn.workers.async import AsyncWorker

class GEventWorker(AsyncWorker):
        
    @classmethod  
    def setup(cls):
        from gevent import monkey
        monkey.patch_all()
        
    def keepalive_request(self, client, addr):
        req = None
        with gevent.Timeout(self.cfg.keepalive, False):
            req = super(GEventWorker, self).keepalive_request(client, addr)
        return req
        
    def run(self):
        self.socket.setblocking(1)

        pool = Pool(self.worker_connections)
        acceptor = gevent.spawn(self.acceptor, pool)
        
        try:
            while True:
                self.notify()
            
                if self.ppid != os.getppid():
                    self.log.info("Parent changed, shutting down: %s" % self)
                    gevent.kill(acceptor)
                    break
                gevent.sleep(0.1)            

            pool.join(timeout=self.timeout)
        except KeyboardInterrupt:
            pass

    def acceptor(self, pool):
        gevent.getcurrent()
        while self.alive:
            try:
                conn, addr = self.socket.accept()
                gt = pool.spawn(self.handle, conn, addr)
                gt._conn = conn
                gt.link(self.cleanup)
                conn, addr, gt = None, None, None
            except greenlet.GreenletExit:
                return
          
    def cleanup(self, gt):
        try:
            try:
                gt.join()
            finally:
                gt._conn.close()
        except greenlet.GreenletExit:
            pass
        except Exception:
            self.log.exception("Unhandled exception in worker.")
