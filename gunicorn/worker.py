
import logging
import os
import select
import signal

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
        self.tmp = os.tmpfile()
        self.module = util.import_mod(module)
    
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

            (conn, addr) = self.socket.accept()
            log.info("Client connected: %s:%s" % addr)
            conn.setblocking(1)
            if not self.handle(conn, addr):
                log.info("Client requested process recycle.")
                return

    def handle(self, conn, client):
        fp = conn.makefile()
        line = fp.readline()
        while line:
            log.info("Received: %s" % line.strip())
            if line.strip().startswith("q"):
                log.info("Client disconnected.")
                conn.close()
                return True
            elif line.strip().startswith("k"):
                log.info("Client disconnected.")
                conn.close()
                return False
            else:
                fp.write(line)
                fp.flush()
            line = fp.readline()
