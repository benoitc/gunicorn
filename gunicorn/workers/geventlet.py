# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from functools import partial
import os

try:
    import eventlet
except ImportError:
    raise RuntimeError("You need eventlet installed to use this worker.")
from eventlet import hubs
from eventlet.greenio import GreenSocket
from eventlet.hubs import trampoline

from gunicorn.http.wsgi import sendfile as o_sendfile
from gunicorn.workers.async import AsyncWorker

def _eventlet_sendfile(fdout, fdin, offset, nbytes):
    while True:
        try:
            return o_sendfile(fdout, fdin, offset, nbytes)
        except OSError as e:
            if e.args[0] == errno.EAGAIN:
                trampoline(fdout, write=True)
            else:
                raise

def patch_sendfile():
    from gunicorn.http import wsgi

    if o_sendfile is not None:
        setattr(wsgi, "sendfile", _eventlet_sendfile)

class EventletWorker(AsyncWorker):

    @classmethod
    def setup(cls):
        import eventlet
        if eventlet.version_info < (0, 9, 7):
            raise RuntimeError("You need eventlet >= 0.9.7")
        eventlet.monkey_patch(os=False)
        patch_sendfile()

    def init_process(self):
        hubs.use_hub()
        super(EventletWorker, self).init_process()

    def timeout_ctx(self):
        return eventlet.Timeout(self.cfg.keepalive or None, False)

    def handle(self, listener, client, addr):
        if self.cfg.is_ssl:
            client = eventlet.wrap_ssl(client, server_side=True,
                    do_handshake_on_connect=False,
                    **self.cfg.ssl_options)

        super(EventletWorker, self).handle(listener, client, addr)

        if not self.alive:
            raise eventlet.StopServe()

    def run(self):
        acceptors = []
        for sock in self.sockets:
            sock.setblocking(1)
            hfun = partial(self.handle, sock)
            acceptor = eventlet.spawn(eventlet.serve, sock, hfun,
                    self.worker_connections)

            acceptors.append(acceptor)
            eventlet.sleep(0.0)

        while self.alive:
            self.notify()
            eventlet.sleep(1.0)

        self.notify()
        try:
            with eventlet.Timeout(self.cfg.graceful_timeout) as t:
                [a.wait() for a in acceptors]
        except eventlet.Timeout as te:
            if te != t:
                raise
            [a.kill() for a in acceptors]
