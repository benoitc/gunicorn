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

        pool = greenpool.GreenPool(self.worker_connections)
        acceptor = eventlet.spawn(self.acceptor, pool)

        try:
            while self.alive:
                self.notify()
                
                if self.ppid != os.getppid():
                    self.log.info("Parent changed, shutting down: %s" % self)
                    break
            
                eventlet.sleep(self.timeout)            
        except KeyboardInterrupt:
            pass

        # we stopped
        with eventlet.Timeout(self.timeout, False):
            eventlet.kill(acceptor, eventlet.StopServe)

       
        
    def acceptor(self, pool):
        acceptor_gt = greenthread.getcurrent()
        while self.alive:

            # pool is full ?
            if pool.running() > self.worker_connections:
                continue

            try:
                try:
                    conn, addr = self.socket.accept()
                except socket.error, e:
                    if e[0] == errno.EAGAIN:
                        sys.exc_clear()
                        return
                    raise

                gt = pool.spawn(self.handle, conn, addr)
                gt.link(self._stop_acceptor, acceptor_gt, conn)
                conn, addr, gt = None, None, None
            except socket.error, e:
                if e[0] not in (errno.EBADF, errno.EINVAL, errno.ENOTSOCK):
                    self.alive = False
                    break
            except eventlet.StopServe:
                if pool.waiting():
                    pool.waitall()
                break
            except:
                self.log.exception("Unexpected error in acceptor. Sepuku.")
                os._exit(4)

    def _stop_acceptor(self, t, acceptor_gt, conn):
        try:
            try:
                t.wait()
            finally:
                util.close(conn)
        except greenlet.GreenletExit:
            pass
        except Exception:
            greenthread.kill(acceptor_gt, *sys.exc_info())
        

