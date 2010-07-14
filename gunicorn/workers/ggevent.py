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
from gevent import pywsgi, wsgi

import gunicorn
from gunicorn.workers.async import AsyncWorker
from gunicorn.workers.base import Worker

BASE_WSGI_ENV = {'GATEWAY_INTERFACE': 'CGI/1.1',
            'SERVER_SOFTWARE': 'gevent/%s gunicorn/%s' % (gevent.__version__,
                                                        gunicorn.__version__),
            'SCRIPT_NAME': '',
            'wsgi.version': (1, 0),
            'wsgi.multithread': False,
            'wsgi.multiprocess': False,
            'wsgi.run_once': False}

class GEventWorker(AsyncWorker):
        
    @classmethod  
    def setup(cls):
        from gevent import monkey
        monkey.patch_all(dns=False)
        
    def timeout_ctx(self):
        return gevent.Timeout(self.cfg.keepalive, False)
        
    def run(self):
        self.socket.setblocking(1)

        pool = Pool(self.worker_connections)
        acceptor = gevent.spawn(self.acceptor, pool)
        
        try:
            while self.alive:
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
            except:
                self.log.exception("Unexpected error in acceptor. Sepuku.")
                os._exit(4)
          
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
            

class WSGIHandler(wsgi.WSGIHandler):
    def log_request(self, *args):
        pass
        
class PyWSGIHandler(pywsgi.WSGIHandler):
    def log_request(self, *args):
        pass
        
class PyWSGIServer(pywsgi.WSGIServer):
    base_env = BASE_WSGI_ENV

class WSGIServer(wsgi.WSGIServer):
    base_env = BASE_WSGI_ENV        
    
class GEventWSGIWorker(Worker):
    server_class = WSGIServer
    wsgi_handler = WSGIHandler
    
    def __init__(self, *args, **kwargs):
        super(GEventWSGIWorker, self).__init__(*args, **kwargs)
        self.worker_connections = self.cfg.worker_connections
    
    @classmethod
    def setup(cls):
        from gevent import monkey
        monkey.patch_all(dns=False)
        
    def run(self):
        self.socket.setblocking(1)
        pool = Pool(self.worker_connections)
        
        server = self.server_class(self.socket, application=self.wsgi, 
                        spawn=pool, handler_class=self.wsgi_handler)
        
        server.start()
        
        try:
            while self.alive:
                self.notify()
            
                if self.ppid != os.getppid():
                    self.log.info("Parent changed, shutting down: %s" % self)
                    server.stop()
                    break
                gevent.sleep(0.1) 
            self.pool.join(timeout=self.timeout)
        except KeyboardInterrupt:
            pass

class GEventPyWSGIWorker(GEventWSGIWorker):
    server_class = PyWSGIServer
    wsgi_handler = PyWSGIHandler
