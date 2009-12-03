
import BaseHTTPServer
import logging
import os
import select
import signal

import util

log = logging.getLogger(__name__)

class Handler(BaseHTTPServer.BaseHTTPRequestHandler):
    
    protocol = 'HTTP/1.1'
    worker = None
    
    def do_GET(self):
        self.respond("Hello, World!\n")

    def respond(self, body):
        log.info("Responding")
        self.send_response(200, 'OK')
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        log.info("Sending body.")
        self.wfile.write(body)
        self.wfile.flush()
        log.info("Done.")

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
            try:
                self.handle(conn, addr)
            finally:
                log.info("Client disconnected.")
                conn.close()

    def handle(self, conn, client):
        while True:
            req = Handler(conn, client, self.socket)
            req.setup()
            req.worker = self
            log.info("Handling request.")
            req.handle()
            log.info("Done.")
            if req.close_connection:
                return
