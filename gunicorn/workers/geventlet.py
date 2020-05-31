# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from functools import partial
import errno
import os
import sys

try:
    import eventlet
except ImportError:
    raise RuntimeError("eventlet worker requires eventlet 0.24.1 or higher")
else:
    from pkg_resources import parse_version
    if parse_version(eventlet.__version__) < parse_version('0.24.1'):
        raise RuntimeError("eventlet worker requires eventlet 0.24.1 or higher")

from eventlet import hubs, greenthread
from eventlet.greenio import GreenSocket
from eventlet.hubs import trampoline
from eventlet.wsgi import ALREADY_HANDLED as EVENTLET_ALREADY_HANDLED
import greenlet

from gunicorn.workers.base_async import AsyncWorker


def _eventlet_sendfile(fdout, fdin, offset, nbytes):
    while True:
        try:
            return os.sendfile(fdout, fdin, offset, nbytes)
        except OSError as e:
            if e.args[0] == errno.EAGAIN:
                trampoline(fdout, write=True)
            else:
                raise


def _eventlet_serve(sock, handle, concurrency):
    """
    Serve requests forever.

    This code is nearly identical to ``eventlet.convenience.serve`` except
    that it attempts to join the pool at the end, which allows for gunicorn
    graceful shutdowns.
    """
    pool = eventlet.greenpool.GreenPool(concurrency)
    server_gt = eventlet.greenthread.getcurrent()

    while True:
        try:
            conn, addr = sock.accept()
            gt = pool.spawn(handle, conn, addr)
            gt.link(_eventlet_stop, server_gt, conn)
            conn, addr, gt = None, None, None
        except eventlet.StopServe:
            sock.close()
            pool.waitall()
            return


def _eventlet_stop(client, server, conn):
    """
    Stop a greenlet handling a request and close its connection.

    This code is lifted from eventlet so as not to depend on undocumented
    functions in the library.
    """
    try:
        try:
            client.wait()
        finally:
            conn.close()
    except greenlet.GreenletExit:
        pass
    except Exception:
        greenthread.kill(server, *sys.exc_info())


def patch_sendfile():
    setattr(os, "sendfile", _eventlet_sendfile)


class EventletWorker(AsyncWorker):

    def patch(self):
        hubs.use_hub()
        eventlet.monkey_patch()
        patch_sendfile()

    def is_already_handled(self, respiter):
        if respiter == EVENTLET_ALREADY_HANDLED:
            raise StopIteration()
        return super().is_already_handled(respiter)

    def init_process(self):
        self.patch()
        super().init_process()

    def handle_quit(self, sig, frame):
        eventlet.spawn(super().handle_quit, sig, frame)

    def handle_usr1(self, sig, frame):
        eventlet.spawn(super().handle_usr1, sig, frame)

    def timeout_ctx(self):
        return eventlet.Timeout(self.cfg.keepalive or None, False)

    def handle(self, listener, client, addr):
        if self.cfg.is_ssl:
            client = eventlet.wrap_ssl(client, server_side=True,
                                       **self.cfg.ssl_options)

        super().handle(listener, client, addr)

    def run(self):
        acceptors = []
        for sock in self.sockets:
            gsock = GreenSocket(sock)
            gsock.setblocking(1)
            hfun = partial(self.handle, gsock)
            acceptor = eventlet.spawn(_eventlet_serve, gsock, hfun,
                                      self.worker_connections)

            acceptors.append(acceptor)
            eventlet.sleep(0.0)

        while self.alive:
            self.notify()
            eventlet.sleep(1.0)

        self.notify()
        try:
            with eventlet.Timeout(self.cfg.graceful_timeout) as t:
                for a in acceptors:
                    a.kill(eventlet.StopServe())
                for a in acceptors:
                    a.wait()
        except eventlet.Timeout as te:
            if te != t:
                raise
            for a in acceptors:
                a.kill()
