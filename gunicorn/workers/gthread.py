# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# design:
# a threaded worker accepts connections in the main loop, accepted
# connections are are added to the thread pool as a connection job. On
# keepalive connections are put back in the loop waiting for an event.
# If no event happen after the keep alive timeout, the connectoin is
# closed.


import concurrent.futures as futures
from datetime import datetime
import errno
import heapq
import os
import operator
import socket
import ssl
import sys
import time

from .. import http
from ..http import wsgi
from .. import fdevents
from .. import util
from . import base
from .. import six


class TConn():

    def __init__(self, worker, listener, sock, addr, parser):
        self.listener = listener
        self.sock = sock
        self.addr = addr
        self.parser = parser

        # set the timeout
        self.timeout = time.time() + worker.cfg.keepalive

    def __lt__(self, other):
        return self.timeout < other.timeout

    __cmp__ = __lt__


class ThreadWorker(base.Worker):

    def __init__(self, *args, **kwargs):
        super(ThreadWorker, self).__init__(*args, **kwargs)
        # initialise the pool
        self.tpool = futures.ThreadPoolExecutor(max_workers=self.cfg.threads)
        self.poller = fdevents.DefaultPoller()
        self.futures = set()
        self._heap = []
        self.keepalived = {}

    def _wrap_future(self, fs, listener, client, addr):
        fs.listener = listener
        fs.sock = client
        fs.addr = addr
        self.futures.add(fs)

    def run(self):
        for s in self.sockets:
            s.setblocking(0)
            self.poller.addfd(s, 'r')

        listeners = dict([(s.fileno(), s) for s in self.sockets])
        while self.alive:

            # If our parent changed then we shut down.
            if self.ppid != os.getppid():
                self.log.info("Parent changed, shutting down: %s", self)
                return

            # notify the arbiter we are alive
            self.notify()

            events = self.poller.wait(0.01)
            if events:
                for (fd, mode) in events:
                    fs = None
                    client = None
                    if fd in listeners:
                        listener = listeners[fd]
                        # start to accept connections
                        try:
                            client, addr = listener.accept()

                            # add a job to the pool
                            fs = self.tpool.submit(self.handle, listener,
                                    client, addr, False)

                            self._wrap_future(fs, listener, client, addr)

                        except socket.error as e:
                            if e.args[0] not in (errno.EAGAIN,
                                    errno.ECONNABORTED, errno.EWOULDBLOCK):
                                raise
                    elif fd in self.keepalived:
                        # get the client connection
                        client = self.keepalived[fd]

                        # remove it from the heap
                        try:
                            del self._heap[operator.indexOf(self._heap, client)]
                        except (KeyError, IndexError):
                            pass

                        # add a job to the pool
                        fs = self.tpool.submit(self.handle, client.listener,
                                client.sock,  client.addr, client.parser)

                        # wrap the future
                        self._wrap_future(fs, client.listener, client.sock,
                                client.addr)

            # handle jobs, we give a chance to all jobs to be executed.
            if self.futures:
                self.notify()

                res = futures.wait(self.futures, timeout=self.timeout,
                        return_when=futures.FIRST_COMPLETED)

                for fs in res.done:
                    try:
                        (keepalive, parser) = fs.result()
                        # if the connection should be kept alived add it
                        # to the eventloop and record it
                        if keepalive:
                            # flag the socket as non blocked
                            fs.sock.setblocking(0)

                            tconn = TConn(self, fs.listener, fs.sock,
                                    fs.addr, parser)

                            # register the connection
                            heapq.heappush(self._heap, tconn)
                            self.keepalived[fs.sock.fileno()] = tconn

                            # add the socket to the event loop
                            self.poller.addfd(fs.sock, 'r', False)
                        else:
                            # at this point the connection should be
                            # closed but we make sure it is.
                            util.close(fs.sock)
                    except:
                        # an exception happened, make sure to close the
                        # socket.
                        util.close(fs.sock)
                    finally:
                        # remove the future from our list
                        self.futures.remove(fs)


            # hanle keepalive timeouts
            now = time.time()
            while True:
                if not len(self._heap):
                    break

                conn = heapq.heappop(self._heap)
                delta = conn.timeout - now
                if delta > 0:
                    heapq.heappush(self._heap, conn)
                    break
                else:
                    # remove the socket from the poller
                    self.poller.delfd(conn.sock.fileno(), 'r')
                    # close the socket
                    util.close(conn.sock)


        # shutdown the pool
        self.tpool.shutdown(False)

        # wait for the workers
        futures.wait(self.futures, timeout=self.cfg.graceful_timeout)

        # if we have still fures running, try to close them
        for fs in self.futures:
            sock = fs.sock

            # the future is not running, cancel it
            if not fs.done() and not fs.running():
                fs.cancel()

            # make sure we close the sockets after the graceful timeout
            util.close(sock)


    def handle(self, listener, client, addr, parser):
        keepalive = False
        req = None
        try:
            client.setblocking(1)

            # wrap the connection
            if not parser:
                if self.cfg.is_ssl:
                    client = ssl.wrap_socket(client, server_side=True,
                            **self.cfg.ssl_options)
                parser = http.RequestParser(self.cfg, client)

            req = six.next(parser)
            if not req:
                return (False, None)

            # handle the request
            keepalive = self.handle_request(listener, req, client, addr)
            if keepalive:
                return (keepalive, parser)
        except http.errors.NoMoreData as e:
            self.log.debug("Ignored premature client disconnection. %s", e)

        except StopIteration as e:
            self.log.debug("Closing connection. %s", e)
        except ssl.SSLError as e:
            if e.args[0] == ssl.SSL_ERROR_EOF:
                self.log.debug("ssl connection closed")
                client.close()
            else:
                self.log.debug("Error processing SSL request.")
                self.handle_error(req, client, addr, e)

        except socket.error as e:
            if e.args[0] not in (errno.EPIPE, errno.ECONNRESET):
                self.log.exception("Socket error processing request.")
            else:
                if e.args[0] == errno.ECONNRESET:
                    self.log.debug("Ignoring connection reset")
                else:
                    self.log.debug("Ignoring EPIPE")
        except Exception as e:
            self.handle_error(req, client, addr, e)

        return (False, None)

    def handle_request(self, listener, req, client, addr):
        environ = {}
        resp = None
        try:
            self.cfg.pre_request(self, req)
            request_start = datetime.now()
            resp, environ = wsgi.create(req, client, addr,
                    listener.getsockname(), self.cfg)
            environ["wsgi.multithread"] = True

            self.nr += 1
            if self.nr >= self.max_requests:
                self.log.info("Autorestarting worker after current request.")
                self.alive = False

            if not self.cfg.keepalive:
                resp.force_close()

            respiter = self.wsgi(environ, resp.start_response)
            try:
                if isinstance(respiter, environ['wsgi.file_wrapper']):
                    resp.write_file(respiter)
                else:
                    for item in respiter:
                        resp.write(item)
                resp.close()
                request_time = datetime.now() - request_start
                self.log.access(resp, req, environ, request_time)
            finally:
                if hasattr(respiter, "close"):
                    respiter.close()

            if resp.should_close():
                self.log.debug("Closing connection.")
                return False
        except socket.error:
            exc_info = sys.exc_info()
            # pass to next try-except level
            six.reraise(exc_info[0], exc_info[1], exc_info[2])
        except Exception:
            if resp and resp.headers_sent:
                # If the requests have already been sent, we should close the
                # connection to indicate the error.
                self.log.exception("Error handling request")
                try:
                    client.shutdown(socket.SHUT_RDWR)
                    client.close()
                except socket.error:
                    pass
                raise StopIteration()
            raise
        finally:
            try:
                self.cfg.post_request(self, req, environ, resp)
            except Exception:
                self.log.exception("Exception in post_request hook")

        return True
