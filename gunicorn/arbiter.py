# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from __future__ import with_statement

import errno
import os
import select
import signal
import sys
import time
import traceback

from gunicorn.errors import HaltServer
from gunicorn.pidfile import Pidfile
from gunicorn.sock import create_sockets
from gunicorn import util

from gunicorn import __version__, SERVER_SOFTWARE


class Arbiter(object):
    """
    Arbiter maintain the workers processes alive. It launches or
    kills them if needed. It also manages application reloading
    via SIGHUP/USR2.
    """

    # A flag indicating if a worker failed to
    # to boot. If a worker process exist with
    # this error code, the arbiter will terminate.
    WORKER_BOOT_ERROR = 3

    START_CTX = {}

    LISTENERS = []
    WORKERS = {}
    PIPE = []

    # I love dynamic languages
    SIG_QUEUE = []
    SIGNALS = [getattr(signal, "SIG%s" % x) \
            for x in "HUP QUIT INT TERM TTIN TTOU USR1 USR2 WINCH".split()]
    SIG_NAMES = dict(
        (getattr(signal, name), name[3:].lower()) for name in dir(signal)
        if name[:3] == "SIG" and name[3] != "_"
    )

    def __init__(self, app):
        os.environ["SERVER_SOFTWARE"] = SERVER_SOFTWARE

        self._num_workers = None
        self.setup(app)

        self.pidfile = None
        self.worker_age = 0
        self.reexec_pid = 0
        self.master_name = "Master"

        # get current path, try to use PWD env first
        try:
            a = os.stat(os.environ['PWD'])
            b = os.stat(os.getcwd())
            if a.st_ino == b.st_ino and a.st_dev == b.st_dev:
                cwd = os.environ['PWD']
            else:
                cwd = os.getcwd()
        except:
            cwd = os.getcwd()

        args = sys.argv[:]
        args.insert(0, sys.executable)

        # init start context
        self.START_CTX = {
            "args": args,
            "cwd": cwd,
            0: sys.executable
        }

    def _get_num_workers(self):
        return self._num_workers

    def _set_num_workers(self, value):
        old_value = self._num_workers
        self._num_workers = value
        self.cfg.nworkers_changed(self, value, old_value)
    num_workers = property(_get_num_workers, _set_num_workers)

    def setup(self, app):
        self.app = app
        self.cfg = app.cfg
        self.log = self.cfg.logger_class(app.cfg)

        # reopen files
        if 'GUNICORN_FD' in os.environ:
            self.log.reopen_files()

        self.address = self.cfg.address
        self.num_workers = self.cfg.workers
        self.debug = self.cfg.debug
        self.timeout = self.cfg.timeout
        self.proc_name = self.cfg.proc_name
        self.worker_class = self.cfg.worker_class

        if self.cfg.debug:
            self.log.debug("Current configuration:")
            for config, value in sorted(self.cfg.settings.items(),
                    key=lambda setting: setting[1]):
                self.log.debug("  %s: %s", config, value.value)

        if self.cfg.preload_app:
            if not self.cfg.debug:
                self.app.wsgi()
            else:
                self.log.warning("debug mode: app isn't preloaded.")

    def start(self):
        """\
        Initialize the arbiter. Start listening and set pidfile if needed.
        """
        self.log.info("Starting gunicorn %s", __version__)
        self.pid = os.getpid()
        if self.cfg.pidfile is not None:
            self.pidfile = Pidfile(self.cfg.pidfile)
            self.pidfile.create(self.pid)
        self.cfg.on_starting(self)
        self.init_signals()
        if not self.LISTENERS:
            self.LISTENERS = create_sockets(self.cfg, self.log)

        listeners_str = ",".join([str(l) for l in self.LISTENERS])
        self.log.debug("Arbiter booted")
        self.log.info("Listening at: %s (%s)", listeners_str, self.pid)
        self.log.info("Using worker: %s",
                self.cfg.settings['worker_class'].get())

        self.cfg.when_ready(self)

    def init_signals(self):
        """\
        Initialize master signal handling. Most of the signals
        are queued. Child signals only wake up the master.
        """
        # close old PIPE
        if self.PIPE:
            [os.close(p) for p in self.PIPE]

        # initialize the pipe
        self.PIPE = pair = os.pipe()
        for p in pair:
            util.set_non_blocking(p)
            util.close_on_exec(p)

        self.log.close_on_exec()

        # intialiatze all signals
        [signal.signal(s, self.signal) for s in self.SIGNALS]
        signal.signal(signal.SIGCHLD, self.handle_chld)

    def signal(self, sig, frame):
        if len(self.SIG_QUEUE) < 5:
            self.SIG_QUEUE.append(sig)
            self.wakeup()

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
                    self.log.info("Ignoring unknown signal: %s", sig)
                    continue

                signame = self.SIG_NAMES.get(sig)
                handler = getattr(self, "handle_%s" % signame, None)
                if not handler:
                    self.log.error("Unhandled signal: %s", signame)
                    continue
                self.log.info("Handling signal: %s", signame)
                handler()
                self.wakeup()
            except StopIteration:
                self.halt()
            except KeyboardInterrupt:
                self.halt()
            except HaltServer as inst:
                self.halt(reason=inst.reason, exit_status=inst.exit_status)
            except SystemExit:
                raise
            except Exception:
                self.log.info("Unhandled exception in main loop:\n%s",
                            traceback.format_exc())
                self.stop(False)
                if self.pidfile is not None:
                    self.pidfile.unlink()
                sys.exit(-1)

    def handle_chld(self, sig, frame):
        "SIGCHLD handling"
        self.wakeup()

    def handle_hup(self):
        """\
        HUP handling.
        - Reload configuration
        - Start the new worker processes with a new configuration
        - Gracefully shutdown the old worker processes
        """
        self.log.info("Hang up: %s", self.master_name)
        self.reload()

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
        self.log.reopen_files()

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
            self.log.info("graceful stop of workers")
            self.num_workers = 0
            self.kill_workers(signal.SIGQUIT)
        else:
            self.log.info("SIGWINCH ignored. Not daemonized")

    def wakeup(self):
        """\
        Wake up the arbiter by writing to the PIPE
        """
        try:
            os.write(self.PIPE[1], b'.')
        except IOError as e:
            if e.errno not in [errno.EAGAIN, errno.EINTR]:
                raise

    def halt(self, reason=None, exit_status=0):
        """ halt arbiter """
        self.stop()
        self.log.info("Shutting down: %s", self.master_name)
        if reason is not None:
            self.log.info("Reason: %s", reason)
        if self.pidfile is not None:
            self.pidfile.unlink()
        sys.exit(exit_status)

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
        except select.error as e:
            if e.args[0] not in [errno.EAGAIN, errno.EINTR]:
                raise
        except OSError as e:
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
        for l in self.LISTENERS:
            try:
                l.close()
            except Exception:
                pass

        self.LISTENERS = []
        sig = signal.SIGQUIT
        if not graceful:
            sig = signal.SIGTERM
        limit = time.time() + self.cfg.graceful_timeout
        while self.WORKERS and time.time() < limit:
            self.kill_workers(sig)
            time.sleep(0.1)
            self.reap_workers()
        self.kill_workers(signal.SIGKILL)

    def reexec(self):
        """\
        Relaunch the master and workers.
        """
        if self.pidfile is not None:
            self.pidfile.rename("%s.oldbin" % self.pidfile.fname)

        self.reexec_pid = os.fork()
        if self.reexec_pid != 0:
            self.master_name = "Old Master"
            return

        fds = [l.fileno() for l in self.LISTENERS]
        os.environ['GUNICORN_FD'] = ",".join([str(fd) for fd in fds])

        os.chdir(self.START_CTX['cwd'])
        self.cfg.pre_exec(self)

        # close all file descriptors except bound sockets
        util.closerange(3, fds[0])
        util.closerange(fds[-1] + 1, util.get_maxfd())

        os.execvpe(self.START_CTX[0], self.START_CTX['args'], os.environ)

    def reload(self):
        old_address = self.cfg.address

        # reload conf
        self.app.reload()
        self.setup(self.app)

        # reopen log files
        self.log.reopen_files()

        # do we need to change listener ?
        if old_address != self.cfg.address:
            # close all listeners
            [l.close for l in self.LISTENERS]
            # init new listeners
            self.LISTENERS = create_sockets(self.cfg, self.log)
            self.log.info("Listening at: %s", ",".join(str(self.LISTENERS)))

        # do some actions on reload
        self.cfg.on_reload(self)

        # unlink pidfile
        if self.pidfile is not None:
            self.pidfile.unlink()

        # create new pidfile
        if self.cfg.pidfile is not None:
            self.pidfile = Pidfile(self.cfg.pidfile)
            self.pidfile.create(self.pid)

        # set new proc_name
        util._setproctitle("master [%s]" % self.proc_name)

        # spawn new workers
        for i in range(self.cfg.workers):
            self.spawn_worker()

        # manage workers
        self.manage_workers()

    def murder_workers(self):
        """\
        Kill unused/idle workers
        """
        if not self.timeout:
            return
        for (pid, worker) in self.WORKERS.items():
            try:
                if time.time() - worker.tmp.last_update() <= self.timeout:
                    continue
            except ValueError:
                continue

            self.log.critical("WORKER TIMEOUT (pid:%s)", pid)
            self.kill_worker(pid, signal.SIGKILL)

    def reap_workers(self):
        """\
        Reap workers to avoid zombie processes
        """
        try:
            while True:
                wpid, status = os.waitpid(-1, os.WNOHANG)
                if not wpid:
                    break
                if self.reexec_pid == wpid:
                    self.reexec_pid = 0
                else:
                    # A worker said it cannot boot. We'll shutdown
                    # to avoid infinite start/stop cycles.
                    exitcode = status >> 8
                    if exitcode == self.WORKER_BOOT_ERROR:
                        reason = "Worker failed to boot."
                        raise HaltServer(reason, self.WORKER_BOOT_ERROR)
                    worker = self.WORKERS.pop(wpid, None)
                    if not worker:
                        continue
                    worker.tmp.close()
        except OSError as e:
            if e.errno == errno.ECHILD:
                pass

    def manage_workers(self):
        """\
        Maintain the number of workers by spawning or killing
        as required.
        """
        if len(self.WORKERS.keys()) < self.num_workers:
            self.spawn_workers()

        workers = self.WORKERS.items()
        workers = sorted(workers, key=lambda w: w[1].age)
        while len(workers) > self.num_workers:
            (pid, _) = workers.pop(0)
            self.kill_worker(pid, signal.SIGQUIT)

    def spawn_worker(self):
        self.worker_age += 1
        worker = self.worker_class(self.worker_age, self.pid, self.LISTENERS,
                                    self.app, self.timeout / 2.0,
                                    self.cfg, self.log)
        self.cfg.pre_fork(self, worker)
        pid = os.fork()
        if pid != 0:
            self.WORKERS[pid] = worker
            return pid

        # Process Child
        worker_pid = os.getpid()
        try:
            util._setproctitle("worker [%s]" % self.proc_name)
            self.log.info("Booting worker with pid: %s", worker_pid)
            self.cfg.post_fork(self, worker)
            worker.init_process()
            sys.exit(0)
        except SystemExit:
            raise
        except:
            self.log.exception("Exception in worker process:\n%s",
                    traceback.format_exc())
            if not worker.booted:
                sys.exit(self.WORKER_BOOT_ERROR)
            sys.exit(-1)
        finally:
            self.log.info("Worker exiting (pid: %s)", worker_pid)
            try:
                worker.tmp.close()
                self.cfg.worker_exit(self, worker)
            except:
                pass

    def spawn_workers(self):
        """\
        Spawn new workers as needed.

        This is where a worker process leaves the main loop
        of the master process.
        """

        for i in range(self.num_workers - len(self.WORKERS.keys())):
            self.spawn_worker()

    def kill_workers(self, sig):
        """\
        Kill all workers with the signal `sig`
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
        except OSError as e:
            if e.errno == errno.ESRCH:
                try:
                    worker = self.WORKERS.pop(pid)
                    worker.tmp.close()
                    self.cfg.worker_exit(self, worker)
                    return
                except (KeyError, OSError):
                    return
            raise
