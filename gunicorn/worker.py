# -*- coding: utf-8 -
#
# 2009 (c) Benoit Chesneau <benoitc@e-engura.com> 
# 2009 (c) Paul J. Davis <paul.joseph.davis@gmail.com>
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation
# files (the "Software"), to deal in the Software without
# restriction, including without limitation the rights to use,
# copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following
# conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
# OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.

import errno
import fcntl
import logging
import os
import select
import signal
import socket
import sys

import http
import util

log = logging.getLogger(__name__)

class Worker(object):

    SIGNALS = map(
        lambda x: getattr(signal, "SIG%s" % x),
        "QUIT INT TERM TTIN TTOU".split()
    )

    def __init__(self, workerid, ppid, socket, app):
        
        self.id = workerid
        self.ppid = ppid
        self.socket = socket
        self.address = socket.getsockname()
        self.tmp = os.tmpfile()
        self.app = app
        self.alive = self.tmp.fileno()
    
    def init_signals(self):
        map(lambda s: signal.signal(s, signal.SIG_DFL), self.SIGNALS)
        signal.signal(signal.SIGQUIT, self.handle_quit)
        signal.signal(signal.SIGTERM, self.handle_exit)
        signal.signal(signal.SIGINT, self.handle_exit)

    def handle_quit(self, sig, frame):
        self.alive = False

    def handle_exit(self, sig, frame):
        sys.exit(-1)
    
    def run(self):
        self.init_signals()
        spinner = 0 
        while self.alive:
            spinner = (spinner+1) % 2
            os.fchmod(self.alive, spinner)
                
            while True:
                try:
                    ret = select.select([self.socket], [], [], 2.0)
                except select.error, e:
                    if e[0] != errno.EINTR:
                        raise
                if ret[0]:
                    break

            # Accept until we hit EAGAIN. We're betting that when we're
            # processing clients that more clients are waiting. When
            # there's no more clients waiting we go back to the select()
            # loop and wait for some lovin.
            while True:
                try:
                    (conn, addr) = self.socket.accept()
                except socket.error, e:
                    if e[0] in (errno.EAGAIN, errno.EINTR, 
                            errno.ECONNABORTED):
                        break # Jump back to select
                    raise # Uh oh!

                conn.setblocking(1)
                try:
                    self.handle(conn, addr)
                except Exception, e:
                    log.exception("Error processing request. [%s]" % str(e))

                # Update the fd mtime on each client completion
                # to signal that this worker process is alive.
                spinner = (spinner+1) % 2
                os.fchmod(self.alive, spinner)

    def handle(self, conn, client):
        req = http.HTTPRequest(conn, client, self.address)
        result = self.app(req.read(), req.start_response)
        response = http.HTTPResponse(req, result)
        response.send()
