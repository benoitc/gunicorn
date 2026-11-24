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
        self.worker = None

    def init_signals(self):
        """Stop the process until the worker installs its own handlers."""
        self.log.close_on_exec()

        # The arbiter waits for queued signals in its main loop; there is no
        # loop here, so a console interrupt has to unwind this stack.
        for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            sig = getattr(signal, name, None)
            if sig is not None:
                signal.signal(sig, self._interrupt)

    @staticmethod
    def _interrupt(sig, frame):
        raise KeyboardInterrupt

    def run(self):
        self.start()
        util._setproctitle("server [%s]" % self.proc_name)
        self._warn_ignored_settings()

        exit_status = 0
        try:
            self._serve()
        except AppImportError as e:
            self.log.debug("Exception while loading the application",
                           exc_info=True)
            print("%s" % e, file=sys.stderr)
            sys.stderr.flush()
            exit_status = self.APP_LOAD_ERROR
        except (KeyboardInterrupt, SystemExit):
            pass
        except Exception:
            self.log.exception("Exception in worker process")
            exit_status = -1

        self._arm_shutdown_deadline(exit_status)
        self.halt(exit_status=exit_status)

    def _arm_shutdown_deadline(self, exit_status):
        """End the process when a stop overruns graceful_timeout.

        The master answers an overdue worker with SIGKILL; without one, the
        process has to end itself or a thread stuck in the application keeps
        it alive past the deadline.
        """
        if self.worker is None or self.worker.stopping_at is None:
            return

        remaining = (self.worker.stopping_at + self.cfg.graceful_timeout
                     - time.monotonic())
        timer = threading.Timer(max(remaining, 0.1), os._exit,
                                args=(exit_status,))
        timer.daemon = True
        timer.start()

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
                return

    def _run_worker(self):
        self.worker_age += 1
        # There is no master to watch: ppid=None tells the worker so.
        worker = self.worker_class(self.worker_age, None,
                                   self.LISTENERS, self.app,
                                   self.timeout / 2.0, self.cfg, self.log)
        worker.pid = os.getpid()
        self.worker = worker
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
