# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from __future__ import with_statement

import os
import sys
from datetime import datetime

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

    server_class = None
    wsgi_handler = None

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
        if self.server_class is not None:
            server = self.server_class(
                self.socket, application=self.wsgi, spawn=pool, log=self.log,
                handler_class=self.wsgi_handler)
        else:
            server = StreamServer(self.socket, handle=self.handle, spawn=pool)

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


class GeventResponse(object):

    status = None
    headers = None
    response_length = None


    def __init__(self, status, headers, clength):
        self.status = status
        self.headers = headers
        self.response_length = clength

class PyWSGIHandler(pywsgi.WSGIHandler):

    def log_request(self):
        start = datetime.fromtimestamp(self.time_start)
        finish = datetime.fromtimestamp(self.time_finish)
        response_time = finish - start
        resp = GeventResponse(self.status, self.response_headers,
                self.response_length)
        req_headers = [h.split(":", 1) for h in self.headers.headers]
        self.server.log.access(resp, req_headers, self.environ, response_time)

    def get_environ(self):
        env = super(PyWSGIHandler, self).get_environ()
        env['gunicorn.sock'] = self.socket
        env['RAW_URI'] = self.path
        return env

class PyWSGIServer(pywsgi.WSGIServer):
    base_env = BASE_WSGI_ENV

class GeventPyWSGIWorker(GeventWorker):
    "The Gevent StreamServer based workers."
    server_class = PyWSGIServer
    wsgi_handler = PyWSGIHandler
