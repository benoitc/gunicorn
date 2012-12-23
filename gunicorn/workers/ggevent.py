# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from __future__ import with_statement

import os
import sys
from datetime import datetime
from functools import partial
import time

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
        servers = []
        ssl_args = {}

        if self.cfg.is_ssl:
            ssl_args = dict(server_side=True,
                    do_handshake_on_connect=False, **self.cfg.ssl_options)

        for s in self.sockets:
            s.setblocking(1)
            pool = Pool(self.worker_connections)
            if self.server_class is not None:
                server = self.server_class(
                    s, application=self.wsgi, spawn=pool, log=self.log,
                    handler_class=self.wsgi_handler, **ssl_args)
            else:
                hfun = partial(self.handle, s)
                server = StreamServer(s, handle=hfun, spawn=pool, **ssl_args)

            server.start()
            servers.append(server)

        pid = os.getpid()
        try:
            while self.alive:
                self.notify()

                if pid == os.getpid() and self.ppid != os.getppid():
                    self.log.info("Parent changed, shutting down: %s", self)
                    break

                gevent.sleep(1.0)

        except KeyboardInterrupt:
            pass

        try:
            # Stop accepting requests
            [server.stop_accepting() for server in servers]

            # Handle current requests until graceful_timeout
            ts = time.time()
            while time.time() - ts <= self.cfg.graceful_timeout:
                accepting = 0
                for server in servers:
                    if server.pool.free_count() != server.pool.size:
                        accepting += 1

                # if no server is accepting a connection, we can exit
                if not accepting:
                    return

                self.notify()
                gevent.sleep(1.0)

            # Force kill all active the handlers
            self.log.warning("Worker graceful timeout (pid:%s)" % self.pid)
            server.stop(timeout=1)
        except:
            pass

    def handle_request(self, *args):
        try:
            super(GeventWorker, self).handle_request(*args)
        except gevent.GreenletExit:
            pass

    if gevent.version_info[0] == 0:

        def init_process(self):
            #gevent 0.13 and older doesn't reinitialize dns for us after forking
            #here's the workaround
            import gevent.core
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
