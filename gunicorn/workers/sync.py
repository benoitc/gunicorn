# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.
#

import errno
import os
import select
import socket
import traceback

from gunicorn import http, util
from gunicorn.http.tee import UnexpectedEOF
from gunicorn.workers.base import Worker

class SyncWorker(Worker):
    
    def run(self):
        self.nr = 0

        # self.socket appears to lose its blocking status after
        # we fork in the arbiter. Reset it here.
        self.socket.setblocking(0)

        while self.alive:
            self.nr = 0
            self.notify()
            
            # Accept a connection. If we get an error telling us
            # that no connection is waiting we fall down to the
            # select which is where we'll wait for a bit for new
            # workers to come give us some love.
            try:
                client, addr = self.socket.accept()
                client.setblocking(1)
                util.close_on_exec(client)
                self.handle(client, addr)
                self.nr += 1
            except socket.error, e:
                if e[0] not in (errno.EAGAIN, errno.ECONNABORTED):
                    raise

            # Keep processing clients until no one is waiting. This
            # prevents the need to select() for every client that we
            # process.
            if self.nr > 0:
                continue
            
            # If our parent changed then we shut down.
            if self.ppid != os.getppid():
                self.log.info("Parent changed, shutting down: %s" % self)
                return
            
            try:
                self.notify()
                ret = select.select([self.socket], [], self.PIPE, self.timeout)
                if ret[0]:
                    continue
            except select.error, e:
                if e[0] == errno.EINTR:
                    continue
                if e[0] == errno.EBADF:
                    if self.nr < 0:
                        continue
                    else:
                        return
                raise
        
    def handle(self, client, addr):
        try:
            self.handle_request(client, addr)
        except socket.error, e:
            if e[0] != errno.EPIPE:
                self.log.exception("Error processing request.")
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
        finally:    
            util.close(client)

    def handle_request(self, client, addr):
        req = http.Request(client, addr, self.address, self.cfg)
        try:
            environ = req.read()
            if not environ or not req.parser.status_line:
                return
            respiter = self.app(environ, req.start_response)
            for item in respiter:
                req.response.write(item)
            req.response.close()
            if hasattr(respiter, "close"):
                respiter.close()
        except socket.error:
            raise
        except Exception, e:
            # Only send back traceback in HTTP in debug mode.
            if not self.debug:
                raise
            util.write_error(client, traceback.format_exc())
            return
