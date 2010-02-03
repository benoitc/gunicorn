# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

from __future__ import with_statement

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

from gunicorn.worker import Worker
from gunicorn import util

class Arbiter(object):
    
    LISTENER = None
    WORKERS = {}    
    PIPE = []

    # I love dyanmic languages
    SIG_QUEUE = []
    SIGNALS = map(
        lambda x: getattr(signal, "SIG%s" % x),
        "HUP QUIT INT TERM TTIN TTOU USR1 USR2 WINCH".split()
    )
    SIG_NAMES = dict(
        (getattr(signal, name), name[3:].lower()) for name in dir(signal)
        if name[:3] == "SIG" and name[3] != "_"
    )

    def __init__(self, address, num_workers, modname, 
            **kwargs):
        self.address = address
        self.num_workers = num_workers
        self.modname = modname
        self.timeout = 30
        self.reexec_pid = 0
        self.debug = kwargs.get("debug", False)
        self.log = logging.getLogger(__name__)
        self.opts = kwargs
        self._pidfile = None
        
        
    def start(self):
        self.pid = os.getpid()
        self.init_signals()
        self.listen(self.address)
        self.pidfile = self.opts.get("pidfile")
        self.log.info("Booted Arbiter: %s" % os.getpid())
        
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
    pidfile = property(_get_pidfile, _set_pidfile, _del_pidfile)
    
         
    def unlink_pidfile(self, path):
        try:
            with open(path, "r") as f:
                if int(f.read() or 0) == self.pid:
                    os.unlink(f)
        except:
            pass
        
    def valid_pidfile(self, path):
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

    def listen(self, addr):
        if 'GUNICORN_FD' in os.environ:
            fd = int(os.environ['GUNICORN_FD'])
            del os.environ['GUNICORN_FD']
            try:
                sock = self.init_socket_fromfd(fd, addr)
                self.LISTENER = sock
                return
            except socket.error, e:
                if e[0] == errno.ENOTCONN:
                    self.log.error("should be a non GUNICORN environnement")
                else:
                    raise
                    
        for i in range(5):
            try:
                sock = self.init_socket(addr)
                self.LISTENER = sock
                break            
            except socket.error, e:
                if e[0] == errno.EADDRINUSE:
                    self.log.error("Connection in use: %s" % str(addr))
                if i < 5:
                    self.log.error("Retrying in 1 second.")
                    time.sleep(1)
          
        if self.LISTENER:
            try:
                self.log.info("Listen on %s:%s" % self.LISTENER.getsockname())
            except TypeError:
                self.log.info("Listen on %s" % self.LISTENER.getsockname())
        else:
            self.log.error("Can't connect to %s" % str(addr))
            sys.exit(1)
                
    def init_socket_fromfd(self, fd, address):
        if isinstance(address, basestring):
            sock = socket.fromfd(fd, socket.AF_UNIX, socket.SOCK_STREAM)
        else:
            sock = socket.fromfd(fd, socket.AF_INET, socket.SOCK_STREAM)
            self.set_tcp_sockopts(sock)
        self.set_sockopts(sock, address)
        return sock

    def init_socket(self, address):
        if isinstance(address, basestring):
            try:
                os.remove(address)
            except OSError, e:
                pass
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.set_tcp_sockopts(sock)
        self.set_sockopts(sock, address)
        return sock
        
    def set_tcp_sockopts(self, sock):
        if hasattr(socket, "TCP_CORK"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_CORK, 1)
        elif hasattr(socket, "TCP_NOPUSH"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NOPUSH, 1)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        
    def set_sockopts(self, sock, address):
        sock.setblocking(0)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(address)
        sock.listen(2048)
        
    def run(self):
        self.start()
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
                self.log.info("Unhandled exception in main loop.")
                self.stop(False)
                if self.pidfile:
                    self.unlink_pidfile(self.pidfile)
                sys.exit(-1)

        self.stop()
        self.log.info("Master is shutting down.")
        if self.pidfile:
            self.unlink_pidfile(self.pidfile)
        sys.exit(0)
        
    def handle_chld(self, sig, frame):
        self.wakeup()
        self.reap_workers()
        
    def handle_hup(self):
        self.log.info("Master hang up.")
        self.reexec()
        raise StopIteration
        
    def handle_quit(self):
        raise StopIteration
    
    def handle_int(self):
        self.stop(False)
        raise StopIteration
    
    def handle_term(self):
        self.stop(False)
        raise StopIteration

    def handle_ttin(self):
        self.num_workers += 1
    
    def handle_ttou(self):
        if self.num_workers > 0:
            self.num_workers -= 1
            
    def handle_usr1(self):
        self.kill_workers(signal.SIGUSR1)
    
    def handle_usr2(self):
        self.reexec()
        
    def handle_winch(self):
        if os.getppid() == 1 or os.getpgrp() != os.getpid():
            self.logger.info("graceful stop of workers")
            self.kill_workers(True)
        else:
            self.log.info("SIGWINCH ignored. not daemonized")
    
    def wakeup(self):
        # Wake up the arbiter
        try:
            os.write(self.PIPE[1], '.')
        except IOError, e:
            if e.errno not in [errno.EAGAIN, errno.EINTR]:
                raise
                    
    def sleep(self):
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
        self.reexec_pid = os.fork()
        if self.reexec_pid == 0:
            os.environ['GUNICORN_FD'] = str(self.LISTENER.fileno())
            os.execlp(sys.argv[0], *sys.argv)

    def murder_workers(self):
        for (pid, worker) in list(self.WORKERS.items()):
            diff = time.time() - os.fstat(worker.tmp.fileno()).st_ctime
            if diff <= self.timeout:
                continue
            self.log.error("%s (pid:%s) timed out." % (worker, pid))
            self.kill_worker(pid, signal.SIGKILL)
    
    def reap_workers(self):
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
        if len(self.WORKERS.keys()) < self.num_workers:
            self.spawn_workers()

        for pid, w in self.WORKERS.items():
            if w.id >= self.num_workers:
                self.kill_worker(pid, signal.SIGQUIT)

    def spawn_workers(self):
        workers = set(w.id for w in self.WORKERS.values())
        for i in range(self.num_workers):
            if i in workers:
                continue

            worker = Worker(i, self.pid, self.LISTENER, self.modname,
                        self.timeout/2.0, self.debug)
            pid = os.fork()
            if pid != 0:
                self.WORKERS[pid] = worker
                continue

            # Process Child
            worker_pid = os.getpid()
            try:
                self.log.info("Worker %s booting" % worker_pid)
                worker.run()
                sys.exit(0)
            except SystemExit:
                raise
            except:
                self.log.exception("Exception in worker process.")
                sys.exit(-1)
            finally:
                self.log.info("Worker %s exiting." % worker_pid)

    def kill_workers(self, sig):
        for pid in self.WORKERS.keys():
            self.kill_worker(pid, sig)
        
    def kill_worker(self, pid, sig):
        try:
            os.kill(pid, sig)
        except OSError, e:
            if e.errno == errno.ESRCH:
                worker = self.WORKERS.pop(pid)
                try:
                    worker.tmp.close()
                except:
                    pass
            raise
