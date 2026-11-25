#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Serve from one process where fork is unavailable.

The arbiter forks a worker per process and steers it with POSIX signals.
Windows has neither, so there the worker runs in the process that would
have been the master:

    POSIX                          Windows
    -----                          -------
    master                         this process
      |-- worker 1                 worker (same pid)
      |-- worker 2
      '-- worker 3

Signals the worker handles (SIGINT, SIGTERM, SIGBREAK) stop the process.
There is no second process, so the worker starts again in place when
`max_requests` is reached, and nothing can reload the code.
"""

import os
import signal
import socket
import sys
import threading
import time

from gunicorn import compat, sock, util
from gunicorn.arbiter import Arbiter
from gunicorn.errors import AppImportError


def check_platform(cfg):
    """Refuse settings that need the master, POSIX signals or Unix sockets.

    Windows serves from one process, so what the master would do to a worker
    cannot work. The check runs before the first socket is bound, and stands
    outside Config.validate() so that config parsing and --check-config keep
    working on every platform.
    """
    from gunicorn.workers.gthread import ThreadWorker
    from gunicorn.workers.sync import SyncWorker

    if cfg.daemon:
        raise RuntimeError("daemon mode is not supported on Windows")

    if cfg.reload:
        raise RuntimeError(
            "reload needs a master process: a new process imports the changed "
            "code; it is not supported on Windows")

    if not issubclass(cfg.worker_class, (SyncWorker, ThreadWorker)):
        raise RuntimeError(
            "worker_class %r is not supported on Windows; use sync or gthread"
            % cfg.worker_class_str)

    for addr in cfg.address:
        if not isinstance(addr, tuple):
            raise RuntimeError(
                "unix sockets and fd:// binds are not supported on Windows")

    if cfg.uid != compat.geteuid() or cfg.gid != compat.getegid():
        raise RuntimeError(
            "switching the worker user or group is not supported on Windows; "
            "workers run as the process owner")

    if cfg.dirty_workers or cfg.dirty_apps:
        raise RuntimeError("dirty workers are not supported on Windows")


class SingleProcess(Arbiter):
    """Run one worker in this process instead of forking it."""

    def __init__(self, app):
        super().__init__(app)
        self.master_name = "Server"
        self._wakeup_reader = None
        self._wakeup_writer = None
        self._stuck_generation = False

    def _exit(self, exit_status):
        """Leave without interpreter teardown when a request thread is stuck.

        The executor's atexit hook joins its threads, so an orderly exit
        would wait for the application call that could not be interrupted.
        """
        if not self._stuck_generation:
            super()._exit(exit_status)
            return

        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(exit_status)

    def init_signals(self):
        """Stop the process until the worker installs its own handlers."""
        self.log.close_on_exec()

        # The arbiter waits for queued signals in its main loop; there is no
        # loop here, so a console interrupt has to unwind this stack.
        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            sig = getattr(signal, name, None)
            if sig is not None:
                signal.signal(sig, self._interrupt)

        # A console signal runs its Python handler only when the main thread
        # is free, which it is not while the application blocks. The wakeup
        # fd is written by the C handler at once, so the shutdown deadline
        # starts regardless.
        self._wakeup_reader, self._wakeup_writer = socket.socketpair()
        self._wakeup_writer.setblocking(False)
        signal.set_wakeup_fd(self._wakeup_writer.fileno())

    @staticmethod
    def _interrupt(sig, frame):
        raise KeyboardInterrupt

    def run(self):
        self.start()
        util._setproctitle("server [%s]" % self.proc_name)
        self._warn_ignored_settings()
        self._start_shutdown_watchdog()

        exit_status = 0
        try:
            exit_status = self._serve()
        except AppImportError as e:
            self.log.debug("Exception while loading the application",
                           exc_info=True)
            print("%s" % e, file=sys.stderr)
            sys.stderr.flush()
            exit_status = self.APP_LOAD_ERROR
        except KeyboardInterrupt:
            pass
        except SystemExit as e:
            # An application that exits during startup is not a clean stop.
            if isinstance(e.code, int):
                exit_status = e.code
            elif e.code is not None:
                print(e.code, file=sys.stderr)
                exit_status = 1
        except Exception:
            self.log.exception("Exception in worker process")
            exit_status = -1

        self.halt(exit_status=exit_status)

    def _start_shutdown_watchdog(self):
        thread = threading.Thread(target=self._watch_shutdown,
                                  name="gunicorn-shutdown", daemon=True)
        thread.start()

    def _watch_shutdown(self):
        """End the process when a stop overruns graceful_timeout.

        The master answers an overdue worker with SIGKILL. Without one, a
        stop signal that arrives while the application is blocked would
        otherwise wait for the call to return.
        """
        try:
            if not self._wakeup_reader.recv(64):
                return
        except OSError:
            return

        deadline = time.monotonic() + self.cfg.graceful_timeout
        while time.monotonic() < deadline:
            time.sleep(0.05)
        os._exit(0)

    def stop(self, graceful=True):
        """Close the listeners. There are no worker processes to signal."""
        sock.close_sockets(self.LISTENERS, unlink=True)
        self.LISTENERS = []

    def _serve(self):
        # The master starts a new worker after max_requests; without one the
        # same process starts one instead, until a signal stops it.
        while True:
            worker = self._run_worker()
            if worker.stopping:
                return 0
            if getattr(worker, "nr_conns", 0) > 0:
                # Requests of the retired generation outlived the worker
                # timeout. Their threads cannot be interrupted and another
                # pool would stack on top of them, so end the process the
                # master would have killed.
                self.log.error(
                    "Worker generation did not finish within %ss",
                    self.cfg.timeout)
                self._stuck_generation = True
                return 1

    def _run_worker(self):
        self.worker_age += 1
        # There is no master to watch: ppid=None tells the worker so.
        worker = self.worker_class(self.worker_age, None,
                                   self.LISTENERS, self.app,
                                   self.timeout / 2.0, self.cfg, self.log)
        worker.pid = os.getpid()
        self.log.info("Booting worker with pid: %s", worker.pid)

        try:
            worker.init_process()
        finally:
            self.log.info("Worker exiting (pid: %s)", worker.pid)
            worker.tmp.close()
            self.cfg.worker_exit(self, worker)
        return worker

    def _warn_ignored_settings(self):
        if self.num_workers > 1:
            self.log.warning("Windows runs one process; workers=%s ignored",
                             self.num_workers)
