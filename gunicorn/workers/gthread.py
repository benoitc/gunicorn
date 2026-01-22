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
        self.initialized = False

        # set the socket to non blocking
        self.sock.setblocking(False)

    def init(self):
        # Guard against double initialization
        if self.initialized:
            return
        self.initialized = True
        self.sock.setblocking(True)

        if self.parser is None:
            # wrap the socket if needed
            if self.cfg.is_ssl:
                self.sock = sock.ssl_wrap_socket(self.sock, self.cfg)

            # initialize the parser
            self.parser = http.get_parser(self.cfg, self.sock, self.client)

    def set_timeout(self):
        # Use monotonic clock for reliability (time.time() can jump due to NTP)
        self.timeout = time.monotonic() + self.cfg.keepalive

    def close(self):
        util.close(self.sock)


class PollableMethodQueue:
    """Thread-safe queue that can wake up a selector.

    Uses a pipe to allow worker threads to signal the main thread
    when work is ready, enabling lock-free coordination.

    This approach is compatible with all POSIX systems including
    Linux, macOS, FreeBSD, OpenBSD, and NetBSD. The pipe is set to
    non-blocking mode to prevent worker threads from blocking if
    the pipe buffer fills up under extreme load.
    """

    def __init__(self):
        self._read_fd = None
        self._write_fd = None
        self._queue = None

    def init(self):
        """Initialize the pipe and queue."""
        self._read_fd, self._write_fd = os.pipe()
        # Set both ends to non-blocking:
        # - Write: prevents worker threads from blocking if buffer is full
        # - Read: allows run_callbacks to drain without blocking
        os.set_blocking(self._read_fd, False)
        os.set_blocking(self._write_fd, False)
        self._queue = queue.SimpleQueue()

    def close(self):
        """Close the pipe file descriptors."""
        if self._read_fd is not None:
            try:
                os.close(self._read_fd)
            except OSError:
                pass
        if self._write_fd is not None:
            try:
                os.close(self._write_fd)
            except OSError:
                pass

    def fileno(self):
        """Return the readable file descriptor for selector registration."""
        return self._read_fd

    def defer(self, callback, *args):
        """Queue a callback to be run on the main thread.

        The callback is added to the queue first, then a wake-up byte
        is written to the pipe. If the pipe write fails (buffer full),
        it's safe to ignore because the main thread will eventually
        drain the queue when it reads other wake-up bytes.
        """
        self._queue.put(partial(callback, *args))
        try:
            os.write(self._write_fd, b'\x00')
        except OSError:
            # Pipe buffer full (EAGAIN/EWOULDBLOCK) - safe to ignore
            # The main thread will still process the queue
            pass

    def run_callbacks(self, _fileobj, max_callbacks=50):
        """Run queued callbacks. Called when the pipe is readable.

        Drains all available wake-up bytes and runs corresponding callbacks.
        The max_callbacks limit prevents starvation of other event sources.
        """
        # Read all available wake-up bytes (up to limit)
        try:
            data = os.read(self._read_fd, max_callbacks)
        except OSError:
            return

        # Run callbacks for each byte read, plus any extras in queue
        # (extras can accumulate if pipe writes were dropped)
        callbacks_run = 0
        while callbacks_run < len(data) + 10:  # +10 to drain dropped writes
            try:
                callback = self._queue.get_nowait()
                callback()
                callbacks_run += 1
            except queue.Empty:
                break


class ThreadWorker(base.Worker):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.worker_connections = self.cfg.worker_connections
        self.max_keepalived = self.cfg.worker_connections - self.cfg.threads

        self.tpool = None
        self.poller = None
        self.method_queue = PollableMethodQueue()
        self.keepalived_conns = deque()
        self.nr_conns = 0
        self._accepting = False

    @classmethod
    def check_config(cls, cfg, log):
        max_keepalived = cfg.worker_connections - cfg.threads

        if max_keepalived <= 0 and cfg.keepalive:
            log.warning("No keepalived connections can be handled. " +
                        "Check the number of worker connections and threads.")

    def init_process(self):
        self.tpool = self.get_thread_pool()
        self.poller = selectors.DefaultSelector()
        self.method_queue.init()
        super().init_process()

    def get_thread_pool(self):
        """Override this method to customize how the thread pool is created"""
        return futures.ThreadPoolExecutor(max_workers=self.cfg.threads)

    def handle_exit(self, sig, frame):
        """Handle SIGTERM - begin graceful shutdown."""
        if self.alive:
            self.alive = False
            # Wake up the poller so it can start shutdown
            self.method_queue.defer(lambda: None)

    def handle_quit(self, sig, frame):
        """Handle SIGQUIT - immediate shutdown."""
        self.tpool.shutdown(wait=False)
        super().handle_quit(sig, frame)

    def set_accept_enabled(self, enabled):
        """Enable or disable accepting new connections."""
        if enabled == self._accepting:
            return

        for sock in self.sockets:
            if enabled:
                sock.setblocking(False)
                self.poller.register(sock, selectors.EVENT_READ, self.accept)
            else:
                self.poller.unregister(sock)

        self._accepting = enabled

    def enqueue_req(self, conn):
        """Submit connection to thread pool for processing."""
        fs = self.tpool.submit(self.handle, conn)
        fs.add_done_callback(
            lambda fut: self.method_queue.defer(self.finish_request, conn, fut))

    def accept(self, listener):
        """Accept a new connection from a listener socket."""
        try:
            client_sock, client_addr = listener.accept()
            self.nr_conns += 1
            client_sock.setblocking(True)

            conn = TConn(self.cfg, client_sock, client_addr, listener.getsockname())

            # Submit directly to thread pool for processing
            self.enqueue_req(conn)
        except OSError as e:
            if e.errno not in (errno.EAGAIN, errno.ECONNABORTED, errno.EWOULDBLOCK):
                raise

    def on_client_socket_readable(self, conn, client):
        """Handle a keepalive connection becoming readable."""
        self.poller.unregister(client)
        self.keepalived_conns.remove(conn)

        # Submit to thread pool for processing
        self.enqueue_req(conn)

    def murder_keepalived(self):
        """Close expired keepalive connections."""
        now = time.monotonic()
        while self.keepalived_conns:
            conn = self.keepalived_conns[0]
            delta = conn.timeout - now
            if delta > 0:
                break

            # Connection has timed out
            self.keepalived_conns.popleft()
            try:
                self.poller.unregister(conn.sock)
            except (OSError, KeyError, ValueError):
                pass  # Already unregistered
            self.nr_conns -= 1
            conn.close()

    def is_parent_alive(self):
        # If our parent changed then we shut down.
        if self.ppid != os.getppid():
            self.log.info("Parent changed, shutting down: %s", self)
            return False
        return True

    def wait_for_and_dispatch_events(self, timeout):
        """Wait for events and dispatch callbacks."""
        try:
            events = self.poller.select(timeout)
            for key, _ in events:
                callback = key.data
                callback(key.fileobj)
        except OSError as e:
            if e.errno != errno.EINTR:
                raise

    def run(self):
        # Register the method queue with the poller
        self.poller.register(self.method_queue.fileno(),
                             selectors.EVENT_READ,
                             self.method_queue.run_callbacks)

        # Start accepting connections
        self.set_accept_enabled(True)

        while self.alive:
            # Notify the arbiter we are alive
            self.notify()

            # Check if we can accept more connections
            can_accept = self.nr_conns < self.worker_connections
            if can_accept != self._accepting:
                self.set_accept_enabled(can_accept)

            # Wait for events (unified event loop - no futures.wait())
            self.wait_for_and_dispatch_events(timeout=1.0)

            if not self.is_parent_alive():
                break

            # Handle keepalive timeouts
            self.murder_keepalived()

        # Graceful shutdown: stop accepting but handle existing connections
        self.set_accept_enabled(False)

        # Wait for in-flight connections within grace period
        graceful_timeout = time.monotonic() + self.cfg.graceful_timeout
        while self.nr_conns > 0:
            time_remaining = max(graceful_timeout - time.monotonic(), 0)
            if time_remaining == 0:
                break
            self.wait_for_and_dispatch_events(timeout=time_remaining)
            self.murder_keepalived()

        # Cleanup
        self.tpool.shutdown(wait=False)
        self.poller.close()
        self.method_queue.close()

        for s in self.sockets:
            s.close()

    def finish_request(self, conn, fs):
        """Handle completion of a request (called via method_queue on main thread)."""
        try:
            keepalive = not fs.cancelled() and fs.result()
            if keepalive and self.alive:
                # Put connection back in the poller for keepalive
                conn.sock.setblocking(False)
                conn.set_timeout()
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
        """Handle a request on a connection. Runs in a worker thread."""
        req = None
        try:
            # Initialize connection in worker thread to handle SSL errors gracefully
            # (ENOTCONN from ssl_wrap_socket would crash main thread otherwise)
            conn.init()

            req = next(conn.parser)
            if not req:
                return False

            # Handle the request
            keepalive = self.handle_request(req, conn)
            if keepalive:
                # Discard any unread request body before keepalive
                # to prevent socket appearing readable due to leftover bytes
                conn.parser.finish_body()
                return True
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
