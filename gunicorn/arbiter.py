# -*- coding: utf-8 -
#
# 2009 (c) Benoit Chesneau <benoitc@e-engura.com> 
# 2009 (c) Paul J. Davis <paul.joseph.davis@gmail.com>
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation
# files (the "Software"), to deal in the Software without
# restriction, including without limitation the rights to use,
# copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following
# conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
# OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.

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
        "QUIT INT TERM TTIN TTOU".split()
    )
    SIG_NAMES = dict(
        (getattr(signal, name), name[3:].lower()) for name in dir(signal)
        if name[:3] == "SIG"
    )
    
    def __init__(self, address, num_workers, modname):
        self.address = address
        self.num_workers = num_workers
        self.modname = modname
        self.timeout = 30
        self.pid = os.getpid()
        self.init_signals()
        self.listen(self.address)
        log.info("Booted Arbiter: %s" % os.getpid())

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
        
        if hasattr(socket, "TCP_CORK"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_CORK, 1)
        elif hasattr(socket, "TCP_NOPUSH"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NOPUSH, 1)
        sock.bind(address)
        sock.listen(2048)
        return sock

    def run(self):
        self.manage_workers()
        while True:
            try:
                sig = self.SIG_QUEUE.pop(0) if len(self.SIG_QUEUE) else None

                if sig is None:
                    self.sleep()
                    continue
                
                if sig not in self.SIG_NAMES:
                    log.info("Ignoring unknown signal: %s" % sig)
                    continue
                
                signame = self.SIG_NAMES.get(sig)
                handler = getattr(self, "handle_%s" % signame, None)
                if not handler:
                    log.error("Unhandled signal: %s" % signame)
                    continue

                log.info("Handling signal: %s" % signame)
                handler()
                
                self.murder_workers()
                self.reap_workers()
                self.manage_workers()

            except StopIteration:
                break
            except KeyboardInterrupt:
                self.stop(False)
                sys.exit(-1)
            except Exception, e:
                log.exception("Unhandled exception in main loop.")
                self.stop(False)
                sys.exit(-1)

        log.info("Master is shutting down.")
        self.stop()
    
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
    
    def stop(self, graceful=True):
        self.LISTENER.close()
        sig = signal.SIGQUIT
        if not graceful:
            sig = signal.SIGTERM
        limit = time.time() + self.timeout
        while len(self.WORKERS) and time.time() < limit:
            self.kill_workers(sig)
            time.sleep(0.1)
            self.reap_workers()
        self.kill_workers(signal.SIGKILL)
    
    def murder_workers(self):
        for (pid, worker) in self.WORKERS.iteritems():
            diff = time.time() - os.fstat(worker.tmp.fileno()).st_mtime
            if diff < self.timeout:
                continue
            self.kill_worker(pid, signal.SIGKILL)
    
    def reap_workers(self):
        try:
            while True:
                wpid, status = os.waitpid(-1, os.WNOHANG)
                if not wpid:
                    break
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

            worker = Worker(i, self.pid, self.LISTENER, self.modname)
            pid = os.fork()
            if pid != 0:
                self.WORKERS[pid] = worker
                continue
            
            # Process Child
            try:
                log.info("Worker %s booting" % os.getpid())
                worker.run()
                sys.exit(0)
            except SystemExit:
                raise
            except:
                log.exception("Exception in worker process.")
                sys.exit(-1)
            finally:
                log.info("Worker %s exiting." % os.getpid())

    def kill_workers(self, sig):
        for pid in self.WORKERS.keys():
            self.kill_worker(pid, sig)
        
    def kill_worker(self, pid, sig):
        worker = self.WORKERS.pop(pid)
        try:
            os.kill(pid, sig) 
        except OSError, e:
            if e.errno == errno.ESRCH:
                pass
        finally:
            worker.tmp.close()

