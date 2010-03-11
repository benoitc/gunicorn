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
from gunicorn.http.tee import UnexpectedEOF

class Worker(object):

    SIGNALS = map(
        lambda x: getattr(signal, "SIG%s" % x),
        "HUP QUIT INT TERM USR1 USR2 WINCH CHLD".split()
    )
    
    PIPE = []

    def __init__(self, age, ppid, socket, app, timeout, conf):
        self.nr = 0
        self.age = age
        self.ppid = ppid
        self.debug = conf['debug']
        self.conf = conf
        self.socket = socket
        self.timeout = timeout
        self.fd, self.tmpname = tempfile.mkstemp(prefix="wgunicorn-")
        util.chown(self.tmpname, conf.uid, conf.gid)
        self.tmp = os.fdopen(self.fd, "r+b")
        self.app = app
        self.alive = True
        self.log = logging.getLogger(__name__)
        self.spinner = 0
        self.address = self.socket.getsockname()
        
    def __str__(self):
        return "<Worker %s>" % os.getpid()
        
    @property
    def pid(self):
        return os.getpid()

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
        
    def notify(self):
        """\
        Notify our parent process that we're still alive.
        """
        self.spinner = (self.spinner+1) % 2
        if getattr(os, 'fchmod', None):
            os.fchmod(self.tmp.fileno(), self.spinner)
        else:
            os.chmod(self.tmpname, self.spinner)
            
    def init_process(self):
        util.set_owner_process(self.conf.uid, self.conf.gid)
        
        # init pipe
        self.PIPE = os.pipe()
        map(util.set_non_blocking, self.PIPE)
        map(util.close_on_exec, self.PIPE)
        
        # prevent inherientence
        util.close_on_exec(self.socket)
        util.close_on_exec(self.fd)
        self.init_signals()
    
    def accept(self):
        try:
            client, addr = self.socket.accept()
            self.handle(client, addr)
            self.nr += 1
        except socket.error, e:
            if e[0] not in (errno.EAGAIN, errno.ECONNABORTED):
                raise
    
    def run(self):
        self.init_process()
        self.nr = 0

        # self.socket appears to lose its blocking status after
        # we fork in the arbiter. Reset it here.
        self.socket.setblocking(0)

        while self.alive:
            self.nr = 0
            self.notify()
            
            # accept a new connection
            self.accept()

            # Keep processing clients until no one is waiting.
            # This prevents the need to select() for every
            # client that we process.
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
        util.close_on_exec(client)
        try:
            req = http.Request(client, addr, self.address, self.conf)

            try:
                response = self.app(req.read(), req.start_response)
            except Exception, e:
                # Only send back traceback in HTTP in debug mode.
                if not self.debug:
                    raise
                util.write_error(client, traceback.format_exc())
                return 

            http.Response(client, response, req).send()
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
        finally:    
            util.close(client)
            
