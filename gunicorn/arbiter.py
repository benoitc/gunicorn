import errno
import fcntl
import logging
import os
import select
import signal
import socket
import sys
import time

from worker import Worker

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

class Arbiter(object):
    
    LISTENER = None
    WORKERS = {}    
    PIPE = []

    # I love dyanmic languages
    SIG_QUEUE = []
    SIGNALS = map(
        lambda x: getattr(signal, "SIG%s" % x),
        "WINCH CHLD QUIT INT TERM USR1 USR2 HUP TTIN TTOU".split()
    )
    SIG_NAMES = dict(
        (getattr(signal, name), name) for name in dir(signal)
        if name[:3] == "SIG"
    )
    
    def __init__(self, address, num_workers, modname):
        log.info("Booting Arbiter.")
        self.address = address
        self.num_workers = num_workers
        self.modname = modname
        self.pid = os.getpid()
        self.init_signals()
        self.listen(self.address)

    def init_signals(self):
        if self.PIPE:
            map(lambda p: p.close(), self.PIPE)
        self.PIPE = pair = os.pipe()
        map(self.set_non_blocking, pair)
        map(lambda p: fcntl.fcntl(p, fcntl.F_SETFD, fcntl.FD_CLOEXEC), pair)
        map(lambda s: signal.signal(s, self.signal), self.SIGNALS)
    
    def set_non_blocking(self, fd):
        flags = fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_NONBLOCK
        fcntl.fcntl(fd, fcntl.F_SETFL, flags)
    
    def signal(self, sig, frame):
        if len(self.SIG_QUEUE) < 5:
            self.SIG_QUEUE.append(sig)
        else:
            log.warn("Ignoring rapid signaling: %s" % sig)
        # Wake up the arbiter
        try:
            os.write(self.PIPE[1], '.')
        except IOError, e:
            if e.errno not in [errno.EAGAIN, errno.EINTR]:
                raise
    
    def sleep(self):
        try:
            ready = select.select([self.PIPE[0]], [], [], 1)
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
    
    def listen(self, addr):
        for i in range(5):
            try:
                sock = self.init_socket(addr)
                self.LISTENER = sock
                break
            except socket.error, e:
                if e[0] == errno.EADDRINUSE:
                    log.error("Connection in use: %s" % str(addr))
                if i < 5:
                    log.error("Retrying in 1 second.")
                time.sleep(1)

    def init_socket(self, address):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setblocking(0)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.bind(address)
        sock.listen(2048)
        return sock

    def run(self):
        self.manage_workers()
        while True:
            try:
                sig = self.SIG_QUEUE.pop(0) if len(self.SIG_QUEUE) else None
                if sig is not None:
                    log.info("SIGNAL: %s" % self.SIG_NAMES.get(sig, "Unknown"))
                if sig is None:
                    self.sleep()
                elif sig is signal.SIGINT:
                    self.kill_workers(signal.SIGINT)
                    sys.exit(1)
                elif sig is signal.SIGQUIT:
                    self.kill_workers(signal.SIGTERM)
                    sys.exit(0)
                else:
                    name = self.SIG_NAMES.get(sig, "UNKNOWN")
                    log.warn("IGNORED: %s" % name)
                
                self.reap_workers()
                self.manage_workers()

            except KeyboardInterrupt:
                self.kill_workers(signal.SIGTERM)
                sys.exit()
            except Exception, e:
                self.kill_workers(signal.SIGTERM)
                log.exception("Unhandled exception in main loop.")
                sys.exit()
    
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

            worker = Worker(i, self.LISTENER, self.modname)
            pid = os.fork()
            if pid != 0:
                self.WORKERS[pid] = worker
                continue
            
            # Process Child
            try:
                log.info("Worker %s booting" % os.getpid())
                worker.run()
                log.info("Worker %s exiting" % os.getpid())
                sys.exit(0)
            except SystemExit:
                pass
            except:
                log.exception("Exception in worker process.")
                sys.exit(-1)
            finally:
                log.info("Done.")
    
    def reap_workers(self):
        try:
            while True:
                wpid, status = os.waitpid(-1, os.WNOHANG)
                if not wpid:
                    break
                worker = self.WORKERS.pop(wpid)
                if not worker:
                    continue
                worker.tmp.close()
        except OSError, e:
            if e.errno == errno.ECHILD:
                pass

    def kill_workers(self, sig):
        for pid in self.WORKERS.keys():
            self.kill_worker(pid, sig)
        
    def kill_worker(self, pid, sig):
        worker = self.WORKERS.pop(pid)
        try:
            os.kill(pid, sig) 
        finally:
            worker.tmp.close()

