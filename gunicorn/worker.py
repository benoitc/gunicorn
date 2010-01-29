# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.


import errno
import logging
import os
import select
import signal
import socket
import sys
import tempfile
import traceback

from gunicorn import http
from gunicorn import util


class Worker(object):

    SIGNALS = map(
        lambda x: getattr(signal, "SIG%s" % x),
        "HUP QUIT INT TERM TTIN TTOU USR1 USR2 WINCH".split()
    )
    
    PIPE = []

    def __init__(self, workerid, ppid, socket, app, timeout,
            pipe, debug=False):
        self.nr = 0
        self.id = workerid
        self.ppid = ppid
        self.debug = debug
        self.socket = socket
        self.timeout = timeout / 2.0
        fd, tmpname = tempfile.mkstemp()
        self.tmp = os.fdopen(fd, "r+b")
        self.tmpname = tmpname
        self.app = app
        self.alive = True
        self.log = logging.getLogger(__name__)
        
        
        # init pipe
        self.PIPE = pipe
        map(util.set_non_blocking, pipe)
        map(util.close_on_exec, pipe)
        
        # prevent inherientence
        util.close_on_exec(self.socket)
        util.close_on_exec(fd)
        
        self.address = self.socket.getsockname()

    def init_signals(self):
        map(lambda s: signal.signal(s, signal.SIG_DFL), self.SIGNALS)
        signal.signal(signal.SIGQUIT, self.handle_quit)
        signal.signal(signal.SIGUSR1, self.handle_usr1)
        signal.signal(signal.SIGTERM, self.handle_exit)
        signal.signal(signal.SIGINT, self.handle_exit)
        
    def handle_usr1(self, sig, frame):
        self.nr = -65536; 
        try:
            map(lambda p: p.close(), self.PIPE)
        except:
            pass
            
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
        self.nr = 0
        while self.alive:
            
            self.nr = 0
            # Accept until we hit EAGAIN. We're betting that when we're
            # processing clients that more clients are waiting. When
            # there's no more clients waiting we go back to the select()
            # loop and wait for some lovin.
            while self.alive:
                self.nr = 0
                try:
                    client, addr = self.socket.accept() 
                    
                    # handle connection
                    self.handle(client, addr)

                    # Update the fd mtime on each client completion
                    # to signal that this worker process is alive.
                    spinner = (spinner+1) % 2
                    self._fchmod(spinner)
                    self.nr += 1
                except socket.error, e:
                    if e[0] in (errno.EAGAIN, errno.ECONNABORTED):
                        break # Uh oh!
                    raise
                if self.nr == 0: break
                
            if self.ppid != os.getppid():
                return
                
            while self.alive:
                spinner = (spinner+1) % 2
                self._fchmod(spinner)
                try:
                    ret = select.select([self.socket], [], self.PIPE, 
                                    self.timeout)
                    if ret[0]: break
                except select.error, e:
                    if e[0] == errno.EINTR:
                        break
                    if e[0] == errno.EBADF:
                        if nr >= 0:
                            return
                    raise
                    
            spinner = (spinner+1) % 2
            self._fchmod(spinner) 
        sys.exit(0)   

    def handle(self, client, addr):
        util.close_on_exec(client)
        try:
            req = http.HttpRequest(client, addr, self.address, self.debug)
            try:
                response = self.app(req.read(), req.start_response)
            except Exception, e:
                exc = ''.join(traceback.format_exception(*sys.exc_info()))
                msg = "<h1>Internal Server Error</h1><h2>wsgi error:</h2><pre>%s</pre>" % exc
                util.writelines(client, 
                ["HTTP/1.0 500 Internal Server Error\r\n",
                "Connection: close\r\n",
                "Content-type: text/html\r\n",
                "Content-length: %s\r\n" % str(len(msg)),
                "\r\n",
                msg])
                return 
            http.HttpResponse(client, response, req).send()
        except Exception, e:
            self.log.exception("Error processing request. [%s]" % str(e))
            
            # try to send a response even if something happend    
            try:
                write_nonblock(sock, 
                    "HTTP/1.0 500 Internal Server Error\r\n\r\n")
            except:
                pass
        finally:    
            util.close(client)
            
