#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# design:
# A threaded worker accepts connections in the main loop, accepted
# connections are added to the thread pool as a connection job.
# Keepalive connections are put back in the loop waiting for an event.
# If no event happen after the keep alive timeout, the connection is
# closed.
# pylint: disable=no-else-break

from concurrent import futures
import errno
import os
import queue
import selectors
import socket
import ssl
import sys
import time
from collections import deque
from datetime import datetime
from functools import partial

from . import base
from .. import http
from .. import util
from .. import sock
from ..http import wsgi


class TConn:

    def __init__(self, cfg, sock, client, server):
        self.cfg = cfg
        self.sock = sock
        self.client = client
        self.server = server

        self.timeout = None
        self.parser = None

    def init(self):
        if self.parser is None:
            # wrap the socket if needed
            if self.cfg.is_ssl:
                self.sock = sock.ssl_wrap_socket(self.sock, self.cfg)

            self.parser = http.RequestParser(self.cfg, self.sock, self.client)

    def is_initialized(self):
        return bool(self.parser)

    def set_keepalive_timeout(self):
        self.timeout = time.monotonic() + self.cfg.keepalive

    def close(self):
        util.close(self.sock)


class PollableMethodQueue(object):

    def __init__(self):
        self.fds = []
        self.method_queue = None

    def init(self):
        self.fds = os.pipe()
        self.method_queue = queue.SimpleQueue()

    def close(self):
        for fd in self.fds:
            os.close(fd)

    def get_fd(self):
        return self.fds[0]

    def defer(self, callback, *args):
        self.method_queue.put(partial(callback, *args))
        os.write(self.fds[1], b'0')

    def run_callbacks(self, max_callbacks_at_a_time=10):
        zeroes = os.read(self.fds[0], max_callbacks_at_a_time)
        for _ in range(0, len(zeroes)):
            method = self.method_queue.get()
            method()


class ThreadWorker(base.Worker):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.worker_connections = self.cfg.worker_connections
        self.max_keepalived = self.cfg.worker_connections - self.cfg.threads
        self.thread_pool = None
        self.poller = None
        self.keepalived_conns = deque()
        self.nr_conns = 0
        self.method_queue = PollableMethodQueue()

    @classmethod
    def check_config(cls, cfg, log):
        max_keepalived = cfg.worker_connections - cfg.threads

        if max_keepalived <= 0 and cfg.keepalive:
            log.warning("No keepalived connections can be handled. " +
                        "Check the number of worker connections and threads.")

    def init_process(self):
        self.thread_pool = self.get_thread_pool()
        self.poller = selectors.DefaultSelector()
        self.method_queue.init()
        super().init_process()

    def get_thread_pool(self):
        """Override this method to customize how the thread pool is created"""
        return futures.ThreadPoolExecutor(max_workers=self.cfg.threads)

    def handle_exit(self, sig, frame):
        if self.alive:
            self.alive = False
            self.method_queue.defer(lambda: None)  # To wake up poller.select()

    def handle_quit(self, sig, frame):
        self.thread_pool.shutdown(False)
        super().handle_quit(sig, frame)

    def set_accept_enabled(self, enabled):
        for sock in self.sockets:
            if enabled:
                self.poller.register(sock, selectors.EVENT_READ, self.accept)
            else:
                self.poller.unregister(sock)

    def accept(self, listener):
        try:
            sock, client = listener.accept()
            self.nr_conns += 1
            sock.setblocking(True)  # Explicitly set behavior since it differs per OS
            conn = TConn(self.cfg, sock, client, listener.getsockname())

            self.poller.register(conn.sock, selectors.EVENT_READ,
                                 partial(self.on_client_socket_readable, conn))
        except OSError as e:
            if e.errno not in (errno.EAGAIN, errno.ECONNABORTED,
                               errno.EWOULDBLOCK):
                raise

    def on_client_socket_readable(self, conn, client):
        self.poller.unregister(client)

        if conn.is_initialized():
            self.keepalived_conns.remove(conn)
        conn.init()

        fs = self.thread_pool.submit(self.handle, conn)
        fs.add_done_callback(
            lambda fut: self.method_queue.defer(self.finish_request, conn, fut))

    def murder_keepalived(self):
        now = time.monotonic()
        while self.keepalived_conns:
            delta = self.keepalived_conns[0].timeout - now
            if delta > 0:
                break

            conn = self.keepalived_conns.popleft()
            self.poller.unregister(conn.sock)
            self.nr_conns -= 1
            conn.close()

    def is_parent_alive(self):
        # If our parent changed then we shut down.
        if self.ppid != os.getppid():
            self.log.info("Parent changed, shutting down: %s", self)
            return False
        return True

    def wait_for_and_dispatch_events(self, timeout):
        for key, _ in self.poller.select(timeout):
            callback = key.data
            callback(key.fileobj)

    def run(self):
        self.set_accept_enabled(True)
        self.poller.register(self.method_queue.get_fd(),
                             selectors.EVENT_READ,
                             self.method_queue.run_callbacks)

        while self.alive:
            # notify the arbiter we are alive
            self.notify()

            new_connections_accepted = self.nr_conns < self.worker_connections
            self.wait_for_and_dispatch_events(timeout=1)

            if not self.is_parent_alive():
                break

            # handle keepalive timeouts
            self.murder_keepalived()

            new_connections_still_accepted = self.nr_conns < self.worker_connections
            if new_connections_accepted != new_connections_still_accepted:
                self.set_accept_enabled(new_connections_still_accepted)

        # Don't accept any new connections, as we're about to shut down
        if self.nr_conns < self.worker_connections:
            self.set_accept_enabled(False)

        # ... but try handle all already accepted connections within the grace period
        graceful_timeout = time.monotonic() + self.cfg.graceful_timeout
        while self.nr_conns > 0:
            time_remaining = max(graceful_timeout - time.monotonic(), 0)
            if time_remaining == 0:
                break
            self.wait_for_and_dispatch_events(timeout=time_remaining)

        self.thread_pool.shutdown(wait=False)
        self.poller.close()
        self.method_queue.close()

        for s in self.sockets:
            s.close()

    def finish_request(self, conn, fs):
        try:
            keepalive = not fs.cancelled() and fs.result()
            if keepalive and self.alive:
                conn.set_keepalive_timeout()
                self.keepalived_conns.append(conn)
                self.poller.register(conn.sock, selectors.EVENT_READ,
                                     partial(self.on_client_socket_readable, conn))
            else:
                self.nr_conns -= 1
                conn.close()
        except Exception:
            self.nr_conns -= 1
            conn.close()

    def handle(self, conn):
        req = None
        try:
            req = next(conn.parser)
            if not req:
                return False

            # handle the request
            return self.handle_request(req, conn)
        except http.errors.NoMoreData as e:
            self.log.debug("Ignored premature client disconnection. %s", e)

        except StopIteration as e:
            self.log.debug("Closing connection. %s", e)
        except ssl.SSLError as e:
            if e.args[0] == ssl.SSL_ERROR_EOF:
                self.log.debug("ssl connection closed")
                conn.sock.close()
            else:
                self.log.debug("Error processing SSL request.")
                self.handle_error(req, conn.sock, conn.client, e)

        except OSError as e:
            if e.errno not in (errno.EPIPE, errno.ECONNRESET, errno.ENOTCONN):
                self.log.exception("Socket error processing request.")
            else:
                if e.errno == errno.ECONNRESET:
                    self.log.debug("Ignoring connection reset")
                elif e.errno == errno.ENOTCONN:
                    self.log.debug("Ignoring socket not connected")
                else:
                    self.log.debug("Ignoring connection epipe")
        except Exception as e:
            self.handle_error(req, conn.sock, conn.client, e)

        return False

    def handle_request(self, req, conn):
        environ = {}
        resp = None
        try:
            self.cfg.pre_request(self, req)
            request_start = datetime.now()
            resp, environ = wsgi.create(req, conn.sock, conn.client,
                                        conn.server, self.cfg)
            environ["wsgi.multithread"] = True
            self.nr += 1
            if self.nr >= self.max_requests:
                if self.alive:
                    self.log.info("Autorestarting worker after current request.")
                    self.alive = False
                resp.force_close()

            if not self.alive or not self.cfg.keepalive:
                resp.force_close()
            elif len(self.keepalived_conns) >= self.max_keepalived:
                resp.force_close()

            respiter = self.wsgi(environ, resp.start_response)
            try:
                if isinstance(respiter, environ['wsgi.file_wrapper']):
                    resp.write_file(respiter)
                else:
                    for item in respiter:
                        resp.write(item)

                resp.close()
            finally:
                request_time = datetime.now() - request_start
                self.log.access(resp, req, environ, request_time)
                if hasattr(respiter, "close"):
                    respiter.close()

            if resp.should_close():
                self.log.debug("Closing connection.")
                return False
        except OSError:
            # pass to next try-except level
            util.reraise(*sys.exc_info())
        except Exception:
            if resp and resp.headers_sent:
                # If the requests have already been sent, we should close the
                # connection to indicate the error.
                self.log.exception("Error handling request")
                try:
                    conn.sock.shutdown(socket.SHUT_RDWR)
                    conn.sock.close()
                except OSError:
                    pass
                raise StopIteration()
            raise
        finally:
            try:
                self.cfg.post_request(self, req, environ, resp)
            except Exception:
                self.log.exception("Exception in post_request hook")

        return True
