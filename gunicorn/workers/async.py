# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import errno
import socket
import traceback

from gunicorn import http
from gunicorn.http.tee import UnexpectedEOF
from gunicorn import util
from gunicorn.workers.base import Worker

ALREADY_HANDLED = object()

class AsyncWorker(Worker):

    def __init__(self, *args, **kwargs):
        Worker.__init__(self, *args, **kwargs)
        self.worker_connections = self.cfg.worker_connections
    
    def keepalive_request(self, client, addr):
        return http.KeepAliveRequest(client, addr, self.address, 
            self.cfg)

    def handle(self, client, addr):
        try:
            while self.handle_request(client, addr):
                pass
        except socket.error, e:
            if e[0] not in (errno.EPIPE, errno.ECONNRESET):
                self.log.exception("Error processing request.")
            else:
                if e[0] == errno.ECONNRESET:
                    self.log.warn("Ignoring connection reset")
                else:
                    self.log.warn("Ignoring EPIPE")
        except UnexpectedEOF:
            self.log.exception("Client closed the connection unexpectedly.")
        except Exception, e:
            self.log.exception("Error processing request.")
            try:            
                # Last ditch attempt to notify the client of an error.
                mesg = "HTTP/1.0 500 Internal Server Error\r\n\r\n"
                util.write_nonblock(client, mesg)
            except:
                pass
            return
        finally:
            util.close(client)

    def handle_request(self, client, addr):
        req = self.keepalive_request(client, addr)
        if not req:
            return False
        try:
            environ = req.read()
            if not environ or not req.parser.headers:
                return False
            respiter = self.app(environ, req.start_response)
            if respiter == ALREADY_HANDLED:
                return False
            for item in respiter:
                req.response.write(item)
            req.response.close()
            if hasattr(respiter, "close"):
                respiter.close()
            if req.parser.should_close:
                return False
        except Exception, e:
            #Only send back traceback in HTTP in debug mode.
            if not self.debug:
                raise
            util.write_error(client, traceback.format_exc())
            return False
        return True
