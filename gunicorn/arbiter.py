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
import time

from gunicorn.worker import Worker

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
    
    def __init__(self, address, num_workers, modname):
        self.address = address
        self.num_workers = num_workers
        self.modname = modname
        self.timeout = 30
        self.reexec_pid = 0
        self.pid = os.getpid()
        self.log = logging.getLogger(__name__)
        self.init_signals()
        self.listen(self.address)
        self.log.info("Booted Arbiter: %s" % os.getpid())
        
                    
    def init_signals(self):
        if self.PIPE:
            map(lambda p: p.close(), self.PIPE)
        self.PIPE = pair = os.pipe()
        map(self.set_non_blocking, pair)
        map(lambda p: fcntl.fcntl(p, fcntl.F_SETFD, fcntl.FD_CLOEXEC), pair)
        map(lambda s: signal.signal(s, self.signal), self.SIGNALS)
        signal.signal(signal.SIGCHLD, self.handle_chld)
    
    def set_non_blocking(self, fd):
        flags = fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_NONBLOCK
        fcntl.fcntl(fd, fcntl.F_SETFL, flags)

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
                
    def init_socket_fromfd(self, fd, address):
        sock = socket.fromfd(fd, socket.AF_INET, socket.SOCK_STREAM)
        self.set_sockopts(sock)
        return sock

    def init_socket(self, address):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.set_sockopts(sock)
        sock.bind(address)
        sock.listen(2048)
        return sock
        
    def set_sockopts(self, sock):
        sock.setblocking(0)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if hasattr(socket, "TCP_CORK"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_CORK, 1)
        elif hasattr(socket, "TCP_NOPUSH"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NOPUSH, 1)

    def run(self):
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
                self.stop(False)
                sys.exit(-1)
            except Exception:
                self.log.exception("Unhandled exception in main loop.")
                self.stop(False)
                sys.exit(-1)
                
        self.log.info("Master is shutting down.")
        self.stop()
        
    def handle_chld(self, sig, frame):
        self.wakeup()
        
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
        while len(self.WORKERS) and time.time() < limit:
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
            self.log.error("worker %s PID %s timeout killing." % (str(worker.id), pid))
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
                        self.timeout)
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
                worker.tmp.close()
                self.log.info("Worker %s exiting." % worker_pid)

    def kill_workers(self, sig):
        for pid in self.WORKERS.keys():
            self.kill_worker(pid, sig)
        
    def kill_worker(self, pid, sig):
        worker = self.WORKERS.pop(pid)
        try:
            os.kill(pid, sig)
            kpid, stat = os.waitpid(pid, os.WNOHANG)
            if kpid:
                self.log.warning("Problem killing process: %s" % pid)
        except OSError, e:
            if e.errno == errno.ESRCH:
                try:
                    worker.tmp.close()
                except:
                    pass

