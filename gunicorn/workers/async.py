# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import errno
import socket
import traceback

import gunicorn.util as util
import gunicorn.wsgi as wsgi
from gunicorn.workers.base import Worker

from simplehttp import RequestParser

ALREADY_HANDLED = object()

class AsyncWorker(Worker):

    def __init__(self, *args, **kwargs):
        Worker.__init__(self, *args, **kwargs)
        self.worker_connections = self.cfg.worker_connections
    
    def timeout(self):
        raise NotImplementedError()

    def handle(self, client, addr):
        try:
            parser = RequestParser(client)
            try:
                while True:
                    req = None
                    with self.timeout():
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
                    self.log.warn("Ignoring EPIPE")
        except UnexpectedEOF:
            self.log.exception("Client closed the connection unexpectedly.")
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
            debug = self.cfg.get("debug", False)
            resp, environ = wsgi.create(req, sock, addr, self.address, debug)
            respiter = self.app(environ, resp.start_response)
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
            util.write_error(client, traceback.format_exc())
            return False
        return True
