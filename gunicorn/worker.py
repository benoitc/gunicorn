# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.


import errno
import fcntl
import logging
import os
import select
import signal
import socket
import sys
import tempfile
import time

from gunicorn import http
from gunicorn import util

class Worker(object):

    SIGNALS = map(
        lambda x: getattr(signal, "SIG%s" % x),
        "HUP QUIT INT TERM TTIN TTOU USR1".split()
    )

    def __init__(self, workerid, ppid, socket, app, timeout):
        self.id = workerid
        self.ppid = ppid
        self.timeout = timeout
        fd, tmpname = tempfile.mkstemp()
        self.tmp = os.fdopen(fd, "r+b")
        self.tmpname = tmpname
        
        # prevent inherientence
        self.close_on_exec(socket)
        self.close_on_exec(fd)
        
        self.socket = socket
        self.address = socket.getsockname()
        
        self.app = app
        self.alive = True
        
        self.log = logging.getLogger(__name__)
    
    def close_on_exec(self, fd):
        flags = fcntl.fcntl(fd, fcntl.F_GETFD) | fcntl.FD_CLOEXEC
        fcntl.fcntl(fd, fcntl.F_SETFL, flags)
        
    def init_signals(self):
        map(lambda s: signal.signal(s, signal.SIG_DFL), self.SIGNALS)
        signal.signal(signal.SIGQUIT, self.handle_quit)
        signal.signal(signal.SIGTERM, self.handle_exit)
        signal.signal(signal.SIGINT, self.handle_exit)
        signal.signal(signal.SIGUSR1, self.handle_quit)

    def handle_quit(self, sig, frame):
        self.alive = False

    def handle_exit(self, sig, frame):
        sys.exit(0)
        
    def _fchmod(self, mode):
        if getattr(os, 'fchmod', None):
            os.fchmod(self.tmp.fileno(), mode)
        else:
            os.chmod(self.tmpname, mode)
    
    def run(self):
        self.init_signals()
        spinner = 0 
        while self.alive:
                
            while self.alive:
                spinner = (spinner+1) % 2
                self._fchmod(spinner)
                try:
                    ret = select.select([self.socket], [], [], 
                                    self.timeout)
                    if ret[0]:
                        break
                except select.error, e:
                    if e[0] == errno.EINTR:
                        break
                    elif e[0] == errno.EBADF:
                        return
                    raise
                    
            spinner = (spinner+1) % 2
            self._fchmod(spinner)
            
            # Accept until we hit EAGAIN. We're betting that when we're
            # processing clients that more clients are waiting. When
            # there's no more clients waiting we go back to the select()
            # loop and wait for some lovin.
            while self.alive:
                try:
                    client, addr = self.socket.accept()
                    client.setblocking(0)
                    
                    # handle connection
                    self.handle(client, addr)
                    
                    # Update the fd mtime on each client completion
                    # to signal that this worker process is alive.
                    spinner = (spinner+1) % 2
                    self._fchmod(spinner)
                except socket.error, e:
                    if e[0] in [errno.EAGAIN, errno.ECONNABORTED,
                            errno.EWOULDBLOCK]:
                        break # Uh oh!
                    raise

    def handle(self, client, addr):
        self.close_on_exec(client)
        try:
            req = http.HTTPRequest(client, addr, self.address)
            response = self.app(req.read(), req.start_response)
            http.HTTPResponse(client, response, req).send()
        except Exception, e:
            self.log.exception("Error processing request. [%s]" % str(e))
            # try to send something if an error happend
            msg = "HTTP/1.1 500 Internal Server Error\r\n\r\n"
            util.write_nonblock(client, msg)
            util.close(client)
