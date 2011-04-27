# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

from __future__ import with_statement

import os
import sys

# workaround on osx, disable kqueue
if sys.platform == "darwin":
    os.environ['EVENT_NOKQUEUE'] = "1"

try:
    import gevent
except ImportError:
    raise RuntimeError("You need gevent installed to use this worker.")
from gevent.pool import Pool
from gevent.server import StreamServer
from gevent import pywsgi

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


class GGeventServer(StreamServer):
    def __init__(self, listener, handle, spawn='default', worker=None):
        StreamServer.__init__(self, listener, spawn=spawn)
        self.handle_func = handle
        self.worker = worker

    def stop(self, timeout=None):
        super(GGeventServer, self).stop(timeout=timeout)

    def handle(self, sock, addr):
        self.handle_func(sock, addr)

class GeventWorker(AsyncWorker):

    @classmethod  
    def setup(cls):
        from gevent import monkey
        monkey.noisy = False
        monkey.patch_all()
        
        
    def timeout_ctx(self):
        return gevent.Timeout(self.cfg.keepalive, False)

    def run(self):
        self.socket.setblocking(1)

        pool = Pool(self.worker_connections)
        server = GGeventServer(self.socket, self.handle, spawn=pool,
                worker=self)

        server.start()
        try:
            while self.alive:
                self.notify()
                if self.ppid != os.getppid():
                    self.log.info("Parent changed, shutting down: %s", self)
                    break
        
                gevent.sleep(1.0)
                
        except KeyboardInterrupt:
            pass

        try:
            # Try to stop connections until timeout
            self.notify()
            server.stop(timeout=self.timeout)
        except:
            pass

    def handle_request(self, *args):
        try:
            super(GeventWorker, self).handle_request(*args)
        except gevent.GreenletExit:
            pass

    if hasattr(gevent.core, 'dns_shutdown'):

        def init_process(self):
            #gevent 0.13 and older doesn't reinitialize dns for us after forking
            #here's the workaround
            gevent.core.dns_shutdown(fail_requests=1)
            gevent.core.dns_init()
            super(GeventWorker, self).init_process()


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
        monkey.noisy = False
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
                    self.log.info("Parent changed, shutting down: %s", self)
                    break
                
                gevent.sleep(1.0) 

        except KeyboardInterrupt:
            pass

        # try to stop the connections
        try:
            self.notify()
            server.stop(timeout=self.timeout)
        except:
            pass

    if hasattr(gevent.core, 'dns_shutdown'):

        def init_process(self):
            #gevent 0.13 and older doesn't reinitialize dns for us after forking
            #here's the workaround
            gevent.core.dns_shutdown(fail_requests=1)
            gevent.core.dns_init()
            super(GeventBaseWorker, self).init_process()


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
