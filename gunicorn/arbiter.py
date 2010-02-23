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

from gunicorn.sock import create_socket
from gunicorn.worker import Worker
from gunicorn import util

class Arbiter(object):
    """
    Arbiter maintain the workers processes alive. It launches or kill them if needed.
    It also manage application reloading via SIGHUP/USR2.
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

    def __init__(self, address, num_workers, app, **kwargs):
        self.address = address
        self.num_workers = num_workers
        self.app = app
        
        self.timeout = 30
        self.reexec_pid = 0
        self.debug = kwargs.get("debug", False)
        self.log = logging.getLogger(__name__)
        self.opts = kwargs
        self.conf = kwargs.get("config", {})
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
        """ Really initialize the arbiter. Strat to listen and set pidfile if needed."""
        self.pid = os.getpid()
        self.init_signals()
        self.LISTENER = create_socket(self.conf)
        self.pidfile = self.opts.get("pidfile")
        self.log.info("Booted Arbiter: %s" % os.getpid())
        self.log.info("Listening on socket: %s" % self.LISTENER)
        
    def _del_pidfile(self):
        self._pidfile = None
        
    def _get_pidfile(self):
        return self._pidfile
        
    def _set_pidfile(self, path):
        if not path:
            return
        pid = self.valid_pidfile(path)
        if pid:
            if self.pidfile and path == self.pidfile and pid == os.getpid():
                return path
            raise RuntimeError("Already running on PID %s " \
                        "(or pid file '%s' is stale)" % (os.getpid(), path))
        if self.pidfile:    
            self.unlink_pidfile(self.pidfile)

        # write pidfile
        fd, fname = tempfile.mkstemp(dir=os.path.dirname(path))
        os.write(fd, "%s\n" % self.pid)
        os.rename(fname, path)
        os.close(fd)
        self._pidfile = path
    pidfile = property(_get_pidfile, _set_pidfile, _del_pidfile, 
                    "manage creation/delettion of pidfile")
    
    def unlink_pidfile(self, path):
        """ delete pidfile"""
        try:
            with open(path, "r") as f:
                if int(f.read() or 0) == self.pid:
                    os.unlink(f)
        except:
            pass
        
    def valid_pidfile(self, path):
        """ Validate pidfile and make it stale if needed"""
        try:
            with open(path, "r") as f:
                wpid = int(f.read() or 0)

                if wpid <= 0: return None
     
                try:
                    os.kill(wpid, 0)
                    return wpid
                except OSError, e:
                    if e[0] == errno.ESRCH:
                        return
                    raise
        except IOError, e:
            if e[0] == errno.ENOENT:
                return
            raise
    
    def init_signals(self):
        """ Init master signals handling. Most of signal are queued. Childs signals
        only wake up the master"""
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
            self.log.warn("Ignoring rapid signaling: %s" % sig)

    def run(self):
        """ main master loop. Launch to start the master"""
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
                self.log.info("Unhandled exception in main loop. [%s]" %  
                            traceback.format_exc())
                self.stop(False)
                if self.pidfile:
                    self.unlink_pidfile(self.pidfile)
                sys.exit(-1)

        self.stop()
        self.log.info("%s is shutting down." % self.master_name)
        if self.pidfile:
            self.unlink_pidfile(self.pidfile)
        sys.exit(0)
        
    def handle_chld(self, sig, frame):
        """ SIGCHLD handling """
        self.wakeup()
        self.reap_workers()
        
    def handle_hup(self):
        """ HUP handling . We relaunch gracefully the workers and app while 
        reloading configuration."""
        self.log.info("%s hang up." % self.master_name)
        self.reexec()
        raise StopIteration
        
    def handle_quit(self):
        """ SIGQUIT handling"""
        raise StopIteration
    
    def handle_int(self):
        """ SIGINT handling """
        self.stop(False)
        raise StopIteration
    
    def handle_term(self):
        """ SIGTERM handling """
        self.stop(False)
        raise StopIteration

    def handle_ttin(self):
        """ SIGTTIN handling. Increase number of workers."""
        self.num_workers += 1
        self.manage_workers()
    
    def handle_ttou(self):
        """ SIGTTOU handling. Decrease number of workers."""
        if self.num_workers > 0:
            self.num_workers -= 1
        self.manage_workers()
            
    def handle_usr1(self):
        """ SIGUSR1 handling. send USR1 to workers (which will kill it)"""
        self.kill_workers(signal.SIGUSR1)
    
    def handle_usr2(self):
        """ SIGUSR2 handling. relaunch WORKERS and reload app but don't kill old master/workers"""
        self.reexec()
        
    def handle_winch(self):
        """ SIGWINCH handling """
        if os.getppid() == 1 or os.getpgrp() != os.getpid():
            self.logger.info("graceful stop of workers")
            self.kill_workers(True)
        else:
            self.log.info("SIGWINCH ignored. not daemonized")
    
    def wakeup(self):
        """ Wake up the arbiter by writing to the PIPE"""
        try:
            os.write(self.PIPE[1], '.')
        except IOError, e:
            if e.errno not in [errno.EAGAIN, errno.EINTR]:
                raise
                    
    def sleep(self):
        """ Master sleep and wake up when its PIPE change or timeout"""
        
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
        """ Stop workers
        
        :attr graceful: boolean, by default is True. If True workers will be killed gracefully 
        (ie. we trying to wait end of client connection)
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
        """ relaunch the master """
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
        """ kill unused/idle workers"""
        for (pid, worker) in list(self.WORKERS.items()):
            diff = time.time() - os.fstat(worker.tmp.fileno()).st_ctime
            if diff <= self.timeout:
                continue
            self.log.error("%s (pid:%s) timed out." % (worker, pid))
            self.kill_worker(pid, signal.SIGKILL)
    
    def reap_workers(self):
        """ reap workers """
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
        """ maintain number of workers """
        if len(self.WORKERS.keys()) < self.num_workers:
            self.spawn_workers()

        for pid, w in self.WORKERS.items():
            if w.id >= self.num_workers:
                self.kill_worker(pid, signal.SIGQUIT)

    def spawn_workers(self):
        """ spawn new workers """
        workers = set(w.id for w in self.WORKERS.values())
        for i in range(self.num_workers):
            if i in workers:
                continue

            worker = Worker(i, self.pid, self.LISTENER, self.app,
                        self.timeout/2.0, self.conf)
            self.conf.before_fork(self, worker)
            pid = os.fork()
            if pid != 0:
                self.WORKERS[pid] = worker
                continue

            # Process Child
            worker_pid = os.getpid()
            try:
                util._setproctitle("worker [%s]" % self.proc_name)
                self.log.debug("Worker %s booting" % worker_pid)
                self.conf.after_fork(self, worker)
                worker.run()
                sys.exit(0)
            except SystemExit:
                raise
            except:
                self.log.exception("Exception in worker process.")
                sys.exit(-1)
            finally:
                self.log.info("Worker %s exiting." % worker_pid)
                try:
                    worker.tmp.close()
                    os.unlink(worker.tmpname)
                except:
                    pass

    def kill_workers(self, sig):
        """ kill all workers with signal sig
        :attr sig: `signal.SIG*` value
        """
        for pid in self.WORKERS.keys():
            self.kill_worker(pid, sig)
                    
    def kill_worker(self, pid, sig):
        """ kill a worker
        
        :attr pid: int, worker pid
        :attr sig: `signal.SIG*` value
         """
        try:
            os.kill(pid, sig)
        except OSError, e:
            if e.errno == errno.ESRCH:
                worker = self.WORKERS.pop(pid)
                try:
                    worker.tmp.close()
                    os.unlink(worker.tmpname)
                except:
                    pass
            raise            
