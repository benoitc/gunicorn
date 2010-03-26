# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import errno
import os
import select
import socket
import traceback

from gunicorn import http
from gunicorn.http.tee import UnexpectedEOF
from gunicorn import util
from gunicorn.worker import Worker

ALREADY_HANDLED = object()

class KeepaliveResponse(http.Response):

    def default_headers(self):
        if self.req.parser.should_close:
            connection_hdr = "close"
        else:
            connection_hdr = "keep-alive"

        return [
            "HTTP/1.1 %s\r\n" % self.status,
            "Server: %s\r\n" % self.version,
            "Date: %s\r\n" % util.http_date(),
            "Connection: %s\r\n" % connection_hdr
        ]

    def close(self):
        if self.chunked:
            write_chunk(self.socket, "")

class KeepaliveRequest(http.Request):

    RESPONSE_CLASS = KeepaliveResponse

    def read(self):
        ret = select.select([self.socket], [], [], self.conf.keepalive)
        if not ret[0]:
            return
        try:
            return super(KeepaliveRequest, self).read()
        except socket.error, e:
            if e[0] == 54:
                return
            raise

class KeepaliveWorker(Worker):

    def __init__(self, *args, **kwargs):
        Worker.__init__(self, *args, **kwargs)
        self.nb_connections = 0
        self.worker_connections = self.conf.worker_connections

    def handle(self, client, addr):
         
        self.nb_connections += 1
        try:
            self.init_sock(client)
            while True:
                req = KeepaliveRequest(client, addr, self.address, self.conf)
                
                try:
                    environ = req.read()
                    if not environ or not req.parser.headers:
                        return
                    respiter = self.app(environ, req.start_response)
                    if respiter == ALREADY_HANDLED:
                        break
                    for item in respiter:
                        req.response.write(item)
                    req.response.close()
                    if hasattr(respiter, "close"):
                        respiter.close()
                    if req.parser.should_close:
                        break
                except Exception, e:
                    #Only send back traceback in HTTP in debug mode.
                    if not self.debug:
                        raise
                    util.write_error(client, traceback.format_exc())
                    break
        except socket.error, e:
            if e[0] != errno.EPIPE:
                self.log.exception("Error processing request.")
            else:
                self.log.warn("Ignoring EPIPE")
        except UnexpectedEOF:
            self.log.exception("remote closed the connection unexpectedly.")
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
            self.nb_connections -= 1 
            util.close(client)

    def run(self):
        self.init_process()
        self.socket.setblocking(0)

        while self.alive:
            self.notify()
            
            # If our parent changed then we shut down.
            if self.ppid != os.getppid():
                self.log.info("Parent changed, shutting down: %s" % self)
                return
                
            if self.nb_connections > self.worker_connections:
                continue
                
            try:
                ret = select.select([self.socket], [], [], 1)
                if ret[0]:
                    self.accept()
            except select.error, e:
                if e[0] == errno.EINTR:
                    continue
                if e[0] == errno.EBADF:
                    continue
                raise
            except KeyboardInterrupt :
                return

