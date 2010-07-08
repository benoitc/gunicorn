# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

from __future__ import with_statement

import errno
import socket
import traceback

import gunicorn.http as http
import gunicorn.http.wsgi as wsgi
import gunicorn.util as util
import gunicorn.workers.base as base

ALREADY_HANDLED = object()

class AsyncWorker(base.Worker):

    def __init__(self, *args, **kwargs):
        super(AsyncWorker, self).__init__(*args, **kwargs)
        self.worker_connections = self.cfg.worker_connections
    
    def timeout_ctx(self):
        raise NotImplementedError()

    def handle(self, client, addr):
        try:
            parser = http.RequestParser(client)
            try:
                while True:
                    req = None
                    with self.timeout_ctx():
                        req = parser.next()
                    if not req:
                        break
                    self.handle_request(req, client, addr)
            except StopIteration:
                pass
        except socket.error, e:
            if e[0] not in (errno.EPIPE, errno.ECONNRESET):
                self.log.exception("Socket error processing request.")
            else:
                if e[0] == errno.ECONNRESET:
                    self.log.warn("Ignoring connection reset")
                else:
                    self.log.debug("Ignoring EPIPE")
        except Exception, e:
            self.log.exception("General error processing request.")
            try:            
                # Last ditch attempt to notify the client of an error.
                mesg = "HTTP/1.0 500 Internal Server Error\r\n\r\n"
                util.write_nonblock(client, mesg)
            except:
                pass
            return
        finally:
            util.close(client)

    def handle_request(self, req, sock, addr):
        try:
            debug = self.cfg.debug or False
            resp, environ = wsgi.create(req, sock, addr, self.address,
                    self.cfg)
            respiter = self.wsgi(environ, resp.start_response)
            if respiter == ALREADY_HANDLED:
                return False
            for item in respiter:
                resp.write(item)
            resp.close()
            if hasattr(respiter, "close"):
                respiter.close()
            if req.should_close():
                raise StopIteration()
        except Exception, e:
            #Only send back traceback in HTTP in debug mode.
            if not self.debug:
                raise
            util.write_error(sock, traceback.format_exc())
            return False
        return True
