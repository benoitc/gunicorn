
import errno
import logging
import os
import select
import signal
import socket

import http
import util

log = logging.getLogger(__name__)

class Worker(object):

    SIGNALS = map(
        lambda x: getattr(signal, "SIG%s" % x),
        "WINCH QUIT INT TERM USR1 USR2 HUP TTIN TTOU".split()
    )

    def __init__(self, workerid, socket, module):
        self.id = workerid
        self.socket = socket
        self.address = socket.getsockname()
        self.tmp = os.tmpfile()
        self.app = util.import_app(module)
    
    def init_signals(self):
        map(lambda s: signal.signal(s, signal.SIG_DFL), self.SIGNALS)

    def run(self):
        self.init_signals()
        while True:
            # Wait for a request to handle.
            while True:
                ret = select.select([self.socket], [], [], 2.0)
                if ret[0]:
                    break

            # Accept until we hit EAGAIN
            while True:
                try:
                    (conn, addr) = self.socket.accept()
                except socket.error, e:
                    if e[0] in [errno.EAGAIN, errno.EINTR]:
                        continue # Jump back to select
                    raise # Uh oh!

                #log.info("Client connected: %s:%s" % addr)
                conn.setblocking(1)
                try:
                    self.handle(conn, addr)
                except:
                    log.exception("Error processing request.")
                finally:
                    conn.close()

    def handle(self, conn, client):
        while True:
            req = http.HTTPRequest(conn, client, self.address)
            result = self.app(req.read(), req.start_response)
            response = http.HTTPResponse(req, result) 
            response.send()
            if req.should_close():
                conn.close()
                return
