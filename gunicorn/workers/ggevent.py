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

VERSION = "gevent/%s gunicorn/%s" % (gevent.__version__, gunicorn.__version__)

BASE_WSGI_ENV = {
    'GATEWAY_INTERFACE': 'CGI/1.1',
    'SERVER_SOFTWARE': VERSION,
    'SCRIPT_NAME': '',
    'wsgi.version': (1, 0),
    'wsgi.multithread': False,
    'wsgi.multiprocess': False,
    'wsgi.run_once': False
}

class GeventWorker(AsyncWorker):
        
    @classmethod  
    def setup(cls):
        from gevent import monkey
        monkey.patch_all()
        
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

    def init_process(self):
        #gevent doesn't reinitialize dns for us after forking
        #here's the workaround
        gevent.core.dns_shutdown(fail_requests=1)
        gevent.core.dns_init()
        super(GeventWorker, self).init_process()

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
            gt.join()
        except greenlet.GreenletExit:
            pass
        except Exception:
            self.log.exception("Unhandled exception in worker.")
        finally:
            gt._conn.close()

class GeventBaseWorker(Worker):
    """\
    This base class is used for the two variants of workers that use
    Gevent's two different WSGI workers. ``gevent_wsgi`` worker uses
    the libevent HTTP parser but does not support streaming response
    bodies or Keep-Alive. The ``gevent_pywsgi`` worker uses an
    alternative Gevent WSGI server that supports streaming and Keep-
    Alive but does not use the libevent HTTP parser.
    """
    server_class = None
    wsgi_handler = None

    def __init__(self, *args, **kwargs):
        super(GeventBaseWorker, self).__init__(*args, **kwargs)
        self.worker_connections = self.cfg.worker_connections
    
    @classmethod
    def setup(cls):
        from gevent import monkey
        monkey.patch_all()
        
    def run(self):
        self.socket.setblocking(1)
        pool = Pool(self.worker_connections)        
        self.server_class.base_env['wsgi.multiprocess'] = (self.cfg.workers > 1)
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


class WSGIHandler(wsgi.WSGIHandler):
    def log_request(self, *args):
        pass

    def prepare_env(self):
        env = super(WSGIHandler, self).prepare_env()
        env['RAW_URI'] = self.request.uri
        return env
        
        
class WSGIServer(wsgi.WSGIServer):
    base_env = BASE_WSGI_ENV        
    
class GeventWSGIWorker(GeventBaseWorker):
    "The libevent HTTP based workers"
    server_class = WSGIServer
    wsgi_handler = WSGIHandler


class PyWSGIHandler(pywsgi.WSGIHandler):
    def log_request(self, *args):
        pass
        
    def get_environ(self):
        env = super(PyWSGIHandler, self).get_environ()
        env['gunicorn.sock'] = self.socket
        env['RAW_URI'] = self.path
        return env

class PyWSGIServer(pywsgi.WSGIServer):
    base_env = BASE_WSGI_ENV

class GeventPyWSGIWorker(GeventBaseWorker):
    "The Gevent StreamServer based workers."
    server_class = PyWSGIServer
    wsgi_handler = PyWSGIHandler
