# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.


import logging
import os
import signal
import sys
import tempfile

from gunicorn import util

class Worker(object):

    SIGNALS = map(
        lambda x: getattr(signal, "SIG%s" % x),
        "HUP QUIT INT TERM USR1 USR2 WINCH CHLD".split()
    )
    
    PIPE = []

    def __init__(self, age, ppid, socket, app, timeout, cfg):
        """\
        This is called pre-fork so it shouldn't do anything to the
        current process. If there's a need to make process wide
        changes you'll want to do that in ``self.init_process()``.
        """
        self.age = age
        self.ppid = ppid
        self.socket = socket
        self.app = app
        self.timeout = timeout
        self.cfg = cfg
        
        self.nr = 0
        self.alive = True
        self.spinner = 0
        self.log = logging.getLogger(__name__)
        self.debug = cfg.debug
        self.address = self.socket.getsockname()

        self.fd, self.tmpname = tempfile.mkstemp(prefix="wgunicorn-")
        util.chown(self.tmpname, cfg.uid, cfg.gid)
        self.tmp = os.fdopen(self.fd, "r+b")
        
    def __str__(self):
        return "<Worker %s>" % self.pid
        
    @property
    def pid(self):
        return os.getpid()

    def notify(self):
        """\
        Your worker subclass must arrange to have this method called
        once every ``self.timeout`` seconds. If you fail in accomplishing
        this task, the master process will murder your workers.
        """
        self.spinner = (self.spinner+1) % 2
        if getattr(os, 'fchmod', None):
            os.fchmod(self.tmp.fileno(), self.spinner)
        else:
            os.chmod(self.tmpname, self.spinner)

    def run(self):
        """\
        This is the mainloop of a worker process. You should override
        this method in a subclass to provide the intended behaviour
        for your particular evil schemes.
        """
        raise NotImplementedError()

    def init_process(self):
        """\
        If you override this method in a subclass, the last statement
        in the function should be to call this method with
        super(MyWorkerClass, self).init_process() so that the ``run()``
        loop is initiated.
        """
        util.set_owner_process(self.cfg.uid, self.cfg.gid)

        # For waking ourselves up
        self.PIPE = os.pipe()
        map(util.set_non_blocking, self.PIPE)
        map(util.close_on_exec, self.PIPE)
        
        # Prevent fd inherientence
        util.close_on_exec(self.socket)
        util.close_on_exec(self.fd)
        self.init_signals()
        
        self.wsgi = self.app.wsgi()
        
        # Enter main run loop
        self.run()

    def init_signals(self):
        map(lambda s: signal.signal(s, signal.SIG_DFL), self.SIGNALS)
        signal.signal(signal.SIGQUIT, self.handle_quit)
        signal.signal(signal.SIGTERM, self.handle_exit)
        signal.signal(signal.SIGINT, self.handle_exit)
        signal.signal(signal.SIGWINCH, self.handle_winch)
            
    def handle_quit(self, sig, frame):
        self.alive = False

    def handle_exit(self, sig, frame):
        self.alive = False
        sys.exit(0)

    def handle_winch(self, sig, fname):
        # Ignore SIGWINCH in worker. Fixes a crash on OpenBSD.
        return
