# -*- coding: utf-8 -
#
# 2009 (c) Benoit Chesneau <benoitc@e-engura.com> 
# 2009 (c) Paul J. Davis <paul.joseph.davis@gmail.com>
#
# Permission to use, copy, modify, and distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

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

    def __init__(self, workerid, ppid, socket, module):
        self.alive = True
        self.id = workerid
        self.ppid = ppid
        self.socket = socket
        self.address = socket.getsockname()
        self.tmp = os.tmpfile()
        self.app = util.import_app(module)
    
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
            # Wait for a request to handle.
            while self.alive:
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
            while self.alive:
                try:
                    (conn, addr) = self.socket.accept()
                except socket.error, e:
                    if e[0] in [errno.EAGAIN, errno.EINTR]:
                        break # Jump back to select
                    raise # Uh oh!

                conn.setblocking(0)
                try:
                    self.handle(conn, addr)
                except:
                    log.exception("Error processing request.")

                # Update the fd mtime on each client completion
                # to signal that this worker process is alive.
                spinner = (spinner+1) % 2
                os.fchmod(self.tmp.fileno(), spinner)

    def handle(self, conn, client):
        fcntl.fcntl(conn.fileno(), fcntl.F_SETFD, fcntl.FD_CLOEXEC)
        req = http.HTTPRequest(conn, client, self.address)
        result = self.app(req.read(), req.start_response)
        response = http.HTTPResponse(req, result)
        response.send()
