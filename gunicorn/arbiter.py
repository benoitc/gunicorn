# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

from __future__ import with_statement

import copy
import errno
import logging
import os
import select
import signal
import sys
import tempfile
import time
import traceback

from gunicorn.pidfile import Pidfile
from gunicorn.sock import create_socket
from gunicorn.worker import Worker
from gunicorn import util

class Arbiter(object):
    """
    Arbiter maintain the workers processes alive. It launches or
    kills them if needed. It also manages application reloading
    via SIGHUP/USR2.
    """
    
    START_CTX = {}
    
    LISTENER = None
    WORKERS = {}    
    PIPE = []

    # I love dynamic languages
    SIG_QUEUE = []
    SIGNALS = map(
        lambda x: getattr(signal, "SIG%s" % x),
        "HUP QUIT INT TERM TTIN TTOU USR1 USR2 WINCH".split()
    )
    SIG_NAMES = dict(
        (getattr(signal, name), name[3:].lower()) for name in dir(signal)
        if name[:3] == "SIG" and name[3] != "_"
    )
    
    pidfile = Pidfile()

    def __init__(self, address, num_workers, app, **kwargs):
        self.address = address
        self.num_workers = num_workers
        self.worker_age = 0
        self.app = app
        self.conf = kwargs.get("config", {})
        self.timeout = self.conf['timeout']
        self.reexec_pid = 0
        self.debug = kwargs.get("debug", False)
        self.log = logging.getLogger(__name__)
        self.opts = kwargs
        
        self._pidfile = None
        self.master_name = "Master"
        self.proc_name = self.conf['proc_name']
        
        # get current path, try to use PWD env first
        try:
            a = os.stat(os.environ('PWD'))
            b = os.stat(os.getcwd())
            if a.ino == b.ino and a.dev == b.dev:
                cwd = os.environ('PWD')
            else:
                cwd = os.getcwd()
        except:
            cwd = os.getcwd()
            
        # init start context
        self.START_CTX = {
            "argv": copy.copy(sys.argv),
            "cwd": cwd,
            0: copy.copy(sys.argv[0])
        }

    def start(self):
        """\
        Initialize the arbiter. Start listening and set pidfile if needed.
        """
        self.pid = os.getpid()
        self.init_signals()
        self.LISTENER = create_socket(self.conf)
        self.pidfile = self.opts.get("pidfile")
        self.log.info("Arbiter booted")
        self.log.info("Listening at: %s" % self.LISTENER)
        
    
    def init_signals(self):
        """\
        Initialize master signal handling. Most of the signals
        are queued. Child signals only wake up the master.
        """
        if self.PIPE:
            map(lambda p: p.close(), self.PIPE)
        self.PIPE = pair = os.pipe()
        map(util.set_non_blocking, pair)
        map(util.close_on_exec, pair)
        map(lambda s: signal.signal(s, self.signal), self.SIGNALS)
        signal.signal(signal.SIGCHLD, self.handle_chld)

    def signal(self, sig, frame):
        if len(self.SIG_QUEUE) < 5:
            self.SIG_QUEUE.append(sig)
            self.wakeup()
        else:
            self.log.warn("Dropping signal: %s" % sig)

    def run(self):
        "Main master loop."
        self.start()
        util._setproctitle("master [%s]" % self.proc_name)
        self.manage_workers()
        while True:
            try:
                self.reap_workers()
                sig = self.SIG_QUEUE.pop(0) if len(self.SIG_QUEUE) else None
                if sig is None:
                    self.sleep()
                    self.murder_workers()
                    self.manage_workers()
                    continue
                
                if sig not in self.SIG_NAMES:
                    self.log.info("Ignoring unknown signal: %s" % sig)
                    continue
                
                signame = self.SIG_NAMES.get(sig)
                handler = getattr(self, "handle_%s" % signame, None)
                if not handler:
                    self.log.error("Unhandled signal: %s" % signame)
                    continue
                self.log.info("Handling signal: %s" % signame)
                handler()  
                self.wakeup()   
            except StopIteration:
                break
            except KeyboardInterrupt:
                break
            except Exception:
                self.log.info("Unhandled exception in main loop:\n%s" %  
                            traceback.format_exc())
                self.stop(False)
                if self.pidfile:
                    del self.pidfile
                sys.exit(-1)

        self.stop()
        self.log.info("Shutting down: %s" % self.master_name)
        if self.pidfile:
            del self.pidfile
        sys.exit(0)
        
    def handle_chld(self, sig, frame):
        "SIGCHLD handling"
        self.wakeup()
        self.reap_workers()
        
    def handle_hup(self):
        """\
        HUP handling.
        Entirely reloading the application including gracefully
        restart the workers and rereading the configuration.
        """
        self.log.info("Hang up: %s" % self.master_name)
        self.reexec()
        raise StopIteration
        
    def handle_quit(self):
        "SIGQUIT handling"
        raise StopIteration
    
    def handle_int(self):
        "SIGINT handling"
        self.stop(False)
        raise StopIteration
    
    def handle_term(self):
        "SIGTERM handling"
        self.stop(False)
        raise StopIteration

    def handle_ttin(self):
        """\
        SIGTTIN handling.
        Increases the number of workers by one.
        """
        self.num_workers += 1
        self.manage_workers()
    
    def handle_ttou(self):
        """\
        SIGTTOU handling.
        Decreases the number of workers by one.
        """
        if self.num_workers <= 1:
            return
        self.num_workers -= 1
        self.manage_workers()

    def handle_usr1(self):
        """\
        SIGUSR1 handling.
        Kill all workers by sending them a SIGUSR1
        """
        self.kill_workers(signal.SIGUSR1)
    
    def handle_usr2(self):
        """\
        SIGUSR2 handling.
        Creates a new master/worker set as a slave of the current
        master without affecting old workers. Use this to do live
        deployment with the ability to backout a change.
        """
        self.reexec()
        
    def handle_winch(self):
        "SIGWINCH handling"
        if os.getppid() == 1 or os.getpgrp() != os.getpid():
            self.logger.info("graceful stop of workers")
            self.kill_workers(True)
        else:
            self.log.info("SIGWINCH ignored. Not daemonized")
    
    def wakeup(self):
        """\
        Wake up the arbiter by writing to the PIPE
        """
        try:
            os.write(self.PIPE[1], '.')
        except IOError, e:
            if e.errno not in [errno.EAGAIN, errno.EINTR]:
                raise
                    
    def sleep(self):
        """\
        Sleep until PIPE is readable or we timeout.
        A readable PIPE means a signal occurred.
        """
        try:
            ready = select.select([self.PIPE[0]], [], [], 1.0)
            if not ready[0]:
                return
            while os.read(self.PIPE[0], 1):
                pass
        except select.error, e:
            if e[0] not in [errno.EAGAIN, errno.EINTR]:
                raise
        except OSError, e:
            if e.errno not in [errno.EAGAIN, errno.EINTR]:
                raise
        except KeyboardInterrupt:
            sys.exit()
    
    def stop(self, graceful=True):
        """\
        Stop workers
        
        :attr graceful: boolean, If True (the default) workers will be
        killed gracefully  (ie. trying to wait for the current connection)
        """
        self.LISTENER = None
        sig = signal.SIGQUIT
        if not graceful:
            sig = signal.SIGTERM
        limit = time.time() + self.timeout
        while self.WORKERS or time.time() > limit:
            self.kill_workers(sig)
            time.sleep(0.1)
            self.reap_workers()
        self.kill_workers(signal.SIGKILL)

    def reexec(self):
        """\
        Relaunch the master and workers.
        """
        if self.pidfile:
            old_pidfile = "%s.oldbin" % self.pidfile
            self.pidfile = old_pidfile            
        
        self.reexec_pid = os.fork()
        if self.reexec_pid != 0:
            self.master_name = "Old Master"
            return
            
        os.environ['GUNICORN_FD'] = str(self.LISTENER.fileno())
        os.chdir(self.START_CTX['cwd'])
        self.conf.before_exec(self)
        os.execlp(self.START_CTX[0], *self.START_CTX['argv'])

    def murder_workers(self):
        """\
        Kill unused/idle workers
        """
        for (pid, worker) in list(self.WORKERS.items()):
            try:
                diff = time.time() - os.fstat(worker.tmp.fileno()).st_ctime
                if diff <= self.timeout:
                    continue
            except ValueError:
                continue

            self.log.critical("WORKER TIMEOUT (pid:%s)" % pid)
            self.kill_worker(pid, signal.SIGKILL)
    
    def reap_workers(self):
        """\
        Reap workers to avoid zombie processes
        """
        try:
            while True:
                wpid, status = os.waitpid(-1, os.WNOHANG)
                if not wpid: break
                if self.reexec_pid == wpid:
                    self.reexec_pid = 0
                else:
                    worker = self.WORKERS.pop(wpid, None)
                    if not worker:
                        continue
                    worker.tmp.close()
        except OSError, e:
            if e.errno == errno.ECHILD:
                pass
    
    def manage_workers(self):
        """\
        Maintain the number of workers by spawning or killing
        as required.
        """
        if len(self.WORKERS.keys()) < self.num_workers:
            self.spawn_workers()

        num_to_kill = len(self.WORKERS) - self.num_workers
        for i in range(num_to_kill, 0, -1):
            pid, age = 0, sys.maxint
            for (wpid, worker) in self.WORKERS.iteritems():
                if worker.age < age:
                    pid, age = wpid, worker.age
            self.kill_worker(pid, signal.SIGQUIT)
            
    def init_worker(self, worker_age, pid, listener, app, timeout, conf):
        return Worker(worker_age, pid, listener, app, timeout, conf)

    def spawn_workers(self):
        """\
        Spawn new workers as needed.
        
        This is where a worker process leaves the main loop
        of the master process.
        """
        
        for i in range(self.num_workers - len(self.WORKERS.keys())):
            self.worker_age += 1
            worker = self.init_worker(self.worker_age, self.pid, self.LISTENER, 
                            self.app, self.timeout/2.0, self.conf)
            self.conf.before_fork(self, worker)
            pid = os.fork()
            if pid != 0:
                self.WORKERS[pid] = worker
                continue

            # Process Child
            worker_pid = os.getpid()
            try:
                util._setproctitle("worker [%s]" % self.proc_name)
                self.log.debug("Booting worker: %s (age: %s)" % (
                                                worker_pid, self.worker_age))
                self.conf.after_fork(self, worker)
                worker.run()
                sys.exit(0)
            except SystemExit:
                raise
            except:
                self.log.exception("Exception in worker process.")
                sys.exit(-1)
            finally:
                self.log.info("Worker exiting (pid: %s)" % worker_pid)
                try:
                    worker.tmp.close()
                    os.unlink(worker.tmpname)
                except:
                    pass

    def kill_workers(self, sig):
        """\
        Lill all workers with the signal `sig`
        :attr sig: `signal.SIG*` value
        """
        for pid in self.WORKERS.keys():
            self.kill_worker(pid, sig)
                    
    def kill_worker(self, pid, sig):
        """\
        Kill a worker
        
        :attr pid: int, worker pid
        :attr sig: `signal.SIG*` value
         """
        try:
            os.kill(pid, sig)
        except OSError, e:
            if e.errno == errno.ESRCH:
                try:
                    worker = self.WORKERS.pop(pid)
                    worker.tmp.close()
                    os.unlink(worker.tmpname)
                except (KeyError, OSError):
                    return
            raise            
