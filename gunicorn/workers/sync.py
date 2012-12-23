# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.
#

from datetime import datetime
import errno
import os
import select
import socket
import ssl

import gunicorn.http as http
import gunicorn.http.wsgi as wsgi
import gunicorn.util as util
import gunicorn.workers.base as base
from gunicorn import six


class SyncWorker(base.Worker):

    def run(self):
        # self.socket appears to lose its blocking status after
        # we fork in the arbiter. Reset it here.
        [s.setblocking(0) for s in self.sockets]

        ready = self.sockets
        while self.alive:
            self.notify()

            # Accept a connection. If we get an error telling us
            # that no connection is waiting we fall down to the
            # select which is where we'll wait for a bit for new
            # workers to come give us some love.

            for sock in ready:
                try:
                    client, addr = sock.accept()
                    client.setblocking(1)
                    util.close_on_exec(client)
                    self.handle(sock, client, addr)

                    # Keep processing clients until no one is waiting. This
                    # prevents the need to select() for every client that we
                    # process.
                    continue

                except socket.error as e:
                    if e.args[0] not in (errno.EAGAIN, errno.ECONNABORTED,
                            errno.EWOULDBLOCK):
                        raise

            # If our parent changed then we shut down.
            if self.ppid != os.getppid():
                self.log.info("Parent changed, shutting down: %s", self)
                return

            try:
                self.notify()
                ret = select.select(self.sockets, [], self.PIPE, self.timeout)
                if ret[0]:
                    ready = ret[0]
                    continue
            except select.error as e:
                if e.args[0] == errno.EINTR:
                    ready = self.sockets
                    continue
                if e.args[0] == errno.EBADF:
                    if self.nr < 0:
                        ready = self.sockets
                        continue
                    else:
                        return
                raise

    def handle(self, listener, client, addr):
        req = None
        try:
            if self.cfg.is_ssl:
                client = ssl.wrap_socket(client, server_side=True,
                        do_handshake_on_connect=False,
                        **self.cfg.ssl_options)

            parser = http.RequestParser(self.cfg, client)
            req = six.next(parser)
            self.handle_request(listener, req, client, addr)
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
            if e.args[0] != errno.EPIPE:
                self.log.exception("Error processing request.")
            else:
                self.log.debug("Ignoring EPIPE")
        except Exception as e:
            self.handle_error(req, client, addr, e)
        finally:
            util.close(client)

    def handle_request(self, listener, req, client, addr):
        environ = {}
        resp = None
        try:
            self.cfg.pre_request(self, req)
            request_start = datetime.now()
            resp, environ = wsgi.create(req, client, addr,
                    listener.getsockname(), self.cfg)
            # Force the connection closed until someone shows
            # a buffering proxy that supports Keep-Alive to
            # the backend.
            resp.force_close()
            self.nr += 1
            if self.nr >= self.max_requests:
                self.log.info("Autorestarting worker after current request.")
                self.alive = False
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
        except socket.error:
            raise
        except Exception as e:
            # Only send back traceback in HTTP in debug mode.
            self.handle_error(req, client, addr, e)
            return
        finally:
            try:
                self.cfg.post_request(self, req, environ, resp)
            except Exception:
                self.log.exception("Exception in post_request hook")
