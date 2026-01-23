#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.
import errno
import os
import queue
import random
import signal
import sys
import time
import traceback
import socket

from gunicorn.errors import HaltServer, AppImportError
from gunicorn.pidfile import Pidfile
from gunicorn import sock, systemd, util

from gunicorn import __version__, SERVER_SOFTWARE


class Arbiter:
    """
    Arbiter maintain the workers processes alive. It launches or
    kills them if needed. It also manages application reloading
    via SIGHUP/USR2.
    """

    # A flag indicating if a worker failed to
    # to boot. If a worker process exist with
    # this error code, the arbiter will terminate.
    WORKER_BOOT_ERROR = 3

    # A flag indicating if an application failed to be loaded
    APP_LOAD_ERROR = 4

    START_CTX = {}

    LISTENERS = []
    WORKERS = {}

    # Sentinel value for non-signal wakeups
    WAKEUP_REQUEST = signal.NSIG

    SIGNALS = [getattr(signal, "SIG%s" % x)
               for x in "HUP QUIT INT TERM TTIN TTOU USR1 USR2 WINCH".split()]
    SIG_NAMES = dict(
        (getattr(signal, name), name[3:].lower()) for name in dir(signal)
        if name[:3] == "SIG" and name[3] != "_"
    )

    def __init__(self, app):
        os.environ["SERVER_SOFTWARE"] = SERVER_SOFTWARE

        self._num_workers = None
        self._last_logged_active_worker_count = None
        self.log = None

        # Signal queue - SimpleQueue is reentrant-safe for signal handlers
        self.SIG_QUEUE = queue.SimpleQueue()

        self.setup(app)

        self.pidfile = None
        self.systemd = False
        self.worker_age = 0
        self.reexec_pid = 0
        self.master_pid = 0
        self.master_name = "Master"

        cwd = util.getcwd()

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

        if self.log is None:
            self.log = self.cfg.logger_class(app.cfg)

        # reopen files
        if 'GUNICORN_PID' in os.environ:
            self.log.reopen_files()

        self.worker_class = self.cfg.worker_class
        self.address = self.cfg.address
        self.num_workers = self.cfg.workers
        self.timeout = self.cfg.timeout
        self.proc_name = self.cfg.proc_name

        self.log.debug('Current configuration:\n{0}'.format(
            '\n'.join(
                '  {0}: {1}'.format(config, value.value)
                for config, value
                in sorted(self.cfg.settings.items(),
                          key=lambda setting: setting[1]))))

        # set environment' variables
        if self.cfg.env:
            for k, v in self.cfg.env.items():
                os.environ[k] = v

        if self.cfg.preload_app:
            self.app.wsgi()

    def start(self):
        """\
        Initialize the arbiter. Start listening and set pidfile if needed.
        """
        self.log.info("Starting gunicorn %s", __version__)

        if 'GUNICORN_PID' in os.environ:
            self.master_pid = int(os.environ.get('GUNICORN_PID'))
            self.proc_name = self.proc_name + ".2"
            self.master_name = "Master.2"

        self.pid = os.getpid()
        if self.cfg.pidfile is not None:
            pidname = self.cfg.pidfile
            if self.master_pid != 0:
                pidname += ".2"
            self.pidfile = Pidfile(pidname)
            self.pidfile.create(self.pid)
        self.cfg.on_starting(self)

        self.init_signals()

        if not self.LISTENERS:
            fds = None
            listen_fds = systemd.listen_fds()
            if listen_fds:
                self.systemd = True
                fds = range(systemd.SD_LISTEN_FDS_START,
                            systemd.SD_LISTEN_FDS_START + listen_fds)

            elif self.master_pid:
                fds = []
                for fd in os.environ.pop('GUNICORN_FD').split(','):
                    fds.append(int(fd))

            if not (self.cfg.reuse_port and hasattr(socket, 'SO_REUSEPORT')):
                self.LISTENERS = sock.create_sockets(self.cfg, self.log, fds)

        listeners_str = ",".join([str(lnr) for lnr in self.LISTENERS])
        self.log.debug("Arbiter booted")
        self.log.info("Listening at: %s (%s)", listeners_str, self.pid)
        self.log.info("Using worker: %s", self.cfg.worker_class_str)
        systemd.sd_notify("READY=1\nSTATUS=Gunicorn arbiter booted", self.log)

        # check worker class requirements
        if hasattr(self.worker_class, "check_config"):
            self.worker_class.check_config(self.cfg, self.log)

        self.cfg.when_ready(self)

    def init_signals(self):
        """\
        Initialize master signal handling. Most of the signals
        are queued. Child signals only wake up the master.
        """
        self.log.close_on_exec()

        # initialize all signals
        for s in self.SIGNALS:
            signal.signal(s, self.signal)
        signal.signal(signal.SIGCHLD, self.signal_chld)

    def signal(self, sig, frame):
        """Signal handler - NO LOGGING, just queue the signal."""
        self.SIG_QUEUE.put_nowait(sig)

    def run(self):
        "Main master loop."
        self.start()
        util._setproctitle("master [%s]" % self.proc_name)

        try:
            self.manage_workers()

            while True:
                self.maybe_promote_master()

                # Wait for and process signals
                for sig in self.wait_for_signals(timeout=1.0):
                    if sig not in self.SIG_NAMES:
                        self.log.info("Ignoring unknown signal: %s", sig)
                        continue

                    signame = self.SIG_NAMES.get(sig)
                    handler = getattr(self, "handle_%s" % signame, None)
                    if not handler:
                        self.log.error("Unhandled signal: %s", signame)
                        continue
                    # Log SIGCHLD at debug level since it's frequent
                    log_level = self.log.debug if sig == signal.SIGCHLD else self.log.info
                    log_level("Handling signal: %s", signame)
                    handler()

                self.murder_workers()
                self.manage_workers()
        except (StopIteration, KeyboardInterrupt):
            self.halt()
        except HaltServer as inst:
            self.halt(reason=inst.reason, exit_status=inst.exit_status)
        except SystemExit:
            raise
        except Exception:
            self.log.error("Unhandled exception in main loop",
                           exc_info=True)
            self.stop(False)
            if self.pidfile is not None:
                self.pidfile.unlink()
            sys.exit(-1)

    def signal_chld(self, sig, frame):
        """SIGCHLD signal handler - NO LOGGING, just queue the signal."""
        self.SIG_QUEUE.put_nowait(sig)

    def handle_chld(self):
        """SIGCHLD handling - called from main loop, safe to log."""
        self.reap_workers()

    # SIGCLD is an alias for SIGCHLD on Linux. The SIG_NAMES dict may map
    # to either "chld" or "cld" depending on iteration order of dir(signal).
    handle_cld = handle_chld

    def handle_hup(self):
        """\
        HUP handling.
        - Reload configuration
        - Start the new worker processes with a new configuration
        - Gracefully shutdown the old worker processes
        """
        self.log.info("Hang up: %s", self.master_name)
        self.reload()

    def handle_term(self):
        "SIGTERM handling"
        raise StopIteration

    def handle_int(self):
        "SIGINT handling"
        self.stop(False)
        raise StopIteration

    def handle_quit(self):
        "SIGQUIT handling"
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
        self.log.reopen_files()
        self.kill_workers(signal.SIGUSR1)

    def handle_usr2(self):
        """\
        SIGUSR2 handling.
        Creates a new arbiter/worker set as a fork of the current
        arbiter without affecting old workers. Use this to do live
        deployment with the ability to backout a change.
        """
        self.reexec()

    def handle_winch(self):
        """SIGWINCH handling"""
        if self.cfg.daemon:
            self.log.info("graceful stop of workers")
            self.num_workers = 0
            self.kill_workers(signal.SIGTERM)
        else:
            self.log.debug("SIGWINCH ignored. Not daemonized")

    def maybe_promote_master(self):
        if self.master_pid == 0:
            return

        if self.master_pid != os.getppid():
            self.log.info("Master has been promoted.")
            # reset master infos
            self.master_name = "Master"
            self.master_pid = 0
            self.proc_name = self.cfg.proc_name
            del os.environ['GUNICORN_PID']
            # rename the pidfile
            if self.pidfile is not None:
                self.pidfile.rename(self.cfg.pidfile)
            # reset proctitle
            util._setproctitle("master [%s]" % self.proc_name)

    def wakeup(self):
        """Wake up the arbiter's main loop."""
        self.SIG_QUEUE.put_nowait(self.WAKEUP_REQUEST)

    def halt(self, reason=None, exit_status=0):
        """ halt arbiter """
        self.stop()

        log_func = self.log.info if exit_status == 0 else self.log.error
        log_func("Shutting down: %s", self.master_name)
        if reason is not None:
            log_func("Reason: %s", reason)

        if self.pidfile is not None:
            self.pidfile.unlink()
        self.cfg.on_exit(self)
        sys.exit(exit_status)

    def wait_for_signals(self, timeout=1.0):
        """\
        Wait for signals with timeout.
        Returns a list of signals that were received.
        """
        signals = []
        try:
            # Block until we get a signal or timeout
            sig = self.SIG_QUEUE.get(block=True, timeout=timeout)
            if sig != self.WAKEUP_REQUEST:
                signals.append(sig)
            # Drain any additional queued signals
            while True:
                try:
                    sig = self.SIG_QUEUE.get_nowait()
                    if sig != self.WAKEUP_REQUEST:
                        signals.append(sig)
                except queue.Empty:
                    break
        except queue.Empty:
            pass
        except KeyboardInterrupt:
            sys.exit()
        return signals

    def stop(self, graceful=True):
        """\
        Stop workers

        :attr graceful: boolean, If True (the default) workers will be
        killed gracefully  (ie. trying to wait for the current connection)
        """
        unlink = (
            self.reexec_pid == self.master_pid == 0
            and not self.systemd
            and not self.cfg.reuse_port
        )
        sock.close_sockets(self.LISTENERS, unlink)

        self.LISTENERS = []
        sig = signal.SIGTERM
        if not graceful:
            sig = signal.SIGQUIT
        limit = time.time() + self.cfg.graceful_timeout
        # instruct the workers to exit
        self.kill_workers(sig)
        # wait until the graceful timeout
        while self.WORKERS and time.time() < limit:
            self.reap_workers()
            time.sleep(0.1)

        self.kill_workers(signal.SIGKILL)
        # Final reap to clean up any remaining zombies
        self.reap_workers()

    def reexec(self):
        """\
        Relaunch the master and workers.
        """
        if self.reexec_pid != 0:
            self.log.warning("USR2 signal ignored. Child exists.")
            return

        if self.master_pid != 0:
            self.log.warning("USR2 signal ignored. Parent exists.")
            return

        master_pid = os.getpid()
        self.reexec_pid = os.fork()
        if self.reexec_pid != 0:
            return

        self.cfg.pre_exec(self)

        environ = self.cfg.env_orig.copy()
        environ['GUNICORN_PID'] = str(master_pid)

        if self.systemd:
            environ['LISTEN_PID'] = str(os.getpid())
            environ['LISTEN_FDS'] = str(len(self.LISTENERS))
        else:
            environ['GUNICORN_FD'] = ','.join(
                str(lnr.fileno()) for lnr in self.LISTENERS)

        os.chdir(self.START_CTX['cwd'])

        # exec the process using the original environment
        os.execvpe(self.START_CTX[0], self.START_CTX['args'], environ)

    def reload(self):
        old_address = self.cfg.address

        # reset old environment
        for k in self.cfg.env:
            if k in self.cfg.env_orig:
                # reset the key to the value it had before
                # we launched gunicorn
                os.environ[k] = self.cfg.env_orig[k]
            else:
                # delete the value set by gunicorn
                try:
                    del os.environ[k]
                except KeyError:
                    pass

        # reload conf
        self.app.reload()
        self.setup(self.app)

        # reopen log files
        self.log.reopen_files()

        # do we need to change listener ?
        if old_address != self.cfg.address:
            # close all listeners
            for lnr in self.LISTENERS:
                lnr.close()
            # init new listeners
            self.LISTENERS = sock.create_sockets(self.cfg, self.log)
            listeners_str = ",".join([str(lnr) for lnr in self.LISTENERS])
            self.log.info("Listening at: %s", listeners_str)

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

        # Remember current worker age before spawning new workers
        last_worker_age = self.worker_age

        # spawn new workers
        for _ in range(self.cfg.workers):
            self.spawn_worker()

        # manage workers - this will kill old workers beyond num_workers
        self.manage_workers()

        # wait for old workers to terminate to prevent double SIGTERM
        deadline = time.monotonic() + self.cfg.graceful_timeout
        while time.monotonic() < deadline:
            if not self.WORKERS:
                break
            # Check if all remaining workers are newer than last_worker_age
            oldest = min(w.age for w in self.WORKERS.values())
            if oldest > last_worker_age:
                break
            self.reap_workers()
            time.sleep(0.1)

    def murder_workers(self):
        """\
        Kill unused/idle workers
        """
        if not self.timeout:
            return
        workers = list(self.WORKERS.items())
        for (pid, worker) in workers:
            try:
                if time.monotonic() - worker.tmp.last_update() <= self.timeout:
                    continue
            except (OSError, ValueError):
                continue

            if not worker.aborted:
                self.log.critical("WORKER TIMEOUT (pid:%s)", pid)
                worker.aborted = True
                self.kill_worker(pid, signal.SIGABRT)
            else:
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
                    # A worker was terminated. If the termination reason was
                    # that it could not boot, we'll shut it down to avoid
                    # infinite start/stop cycles.
                    exitcode = None
                    if os.WIFEXITED(status):
                        exitcode = os.WEXITSTATUS(status)
                    elif os.WIFSIGNALED(status):
                        sig = os.WTERMSIG(status)
                        try:
                            sig_name = signal.Signals(sig).name
                        except ValueError:
                            sig_name = "signal {}".format(sig)
                        msg = "Worker (pid:{}) was sent {}!".format(
                            wpid, sig_name)

                        # SIGKILL suggests OOM, log as error
                        if sig == signal.SIGKILL:
                            msg += " Perhaps out of memory?"
                            self.log.error(msg)
                        elif sig == signal.SIGTERM:
                            # SIGTERM is expected during graceful shutdown
                            self.log.info(msg)
                        else:
                            # Other signals are unexpected
                            self.log.warning(msg)

                    if exitcode is not None and exitcode != 0:
                        self.log.error("Worker (pid:%s) exited with code %s.",
                                       wpid, exitcode)

                    if exitcode == self.WORKER_BOOT_ERROR:
                        reason = "Worker failed to boot."
                        raise HaltServer(reason, self.WORKER_BOOT_ERROR)
                    if exitcode == self.APP_LOAD_ERROR:
                        reason = "App failed to load."
                        raise HaltServer(reason, self.APP_LOAD_ERROR)

                    worker = self.WORKERS.pop(wpid, None)
                    if not worker:
                        continue
                    worker.tmp.close()
                    self.cfg.child_exit(self, worker)
        except OSError as e:
            if e.errno != errno.ECHILD:
                raise

    def manage_workers(self):
        """\
        Maintain the number of workers by spawning or killing
        as required.
        """
        if len(self.WORKERS) < self.num_workers:
            self.spawn_workers()

        workers = self.WORKERS.items()
        workers = sorted(workers, key=lambda w: w[1].age)
        while len(workers) > self.num_workers:
            (pid, _) = workers.pop(0)
            self.kill_worker(pid, signal.SIGTERM)

        active_worker_count = len(workers)
        if self._last_logged_active_worker_count != active_worker_count:
            self._last_logged_active_worker_count = active_worker_count
            self.log.debug("{0} workers".format(active_worker_count),
                           extra={"metric": "gunicorn.workers",
                                  "value": active_worker_count,
                                  "mtype": "gauge"})

        if self.cfg.enable_backlog_metric:
            backlog = sum(sock.get_backlog() or 0
                          for sock in self.LISTENERS)

            if backlog >= 0:
                self.log.debug("socket backlog: {0}".format(backlog),
                               extra={"metric": "gunicorn.backlog",
                                      "value": backlog,
                                      "mtype": "histogram"})

    def spawn_worker(self):
        self.worker_age += 1
        worker = self.worker_class(self.worker_age, self.pid, self.LISTENERS,
                                   self.app, self.timeout / 2.0,
                                   self.cfg, self.log)
        self.cfg.pre_fork(self, worker)
        pid = os.fork()
        if pid != 0:
            worker.pid = pid
            self.WORKERS[pid] = worker
            return pid

        # Do not inherit the temporary files of other workers
        for sibling in self.WORKERS.values():
            sibling.tmp.close()

        # Process Child
        worker.pid = os.getpid()
        try:
            util._setproctitle("worker [%s]" % self.proc_name)
            self.log.info("Booting worker with pid: %s", worker.pid)
            if self.cfg.reuse_port:
                worker.sockets = sock.create_sockets(self.cfg, self.log)
            self.cfg.post_fork(self, worker)
            worker.init_process()
            sys.exit(0)
        except SystemExit:
            raise
        except AppImportError as e:
            self.log.debug("Exception while loading the application",
                           exc_info=True)
            print("%s" % e, file=sys.stderr)
            sys.stderr.flush()
            sys.exit(self.APP_LOAD_ERROR)
        except Exception as e:
            self.log.exception("Exception in worker process")
            print("%s" % e, file=sys.stderr)
            sys.stderr.flush()
            if not worker.booted:
                sys.exit(self.WORKER_BOOT_ERROR)
            sys.exit(-1)
        finally:
            self.log.info("Worker exiting (pid: %s)", worker.pid)
            try:
                worker.tmp.close()
                self.cfg.worker_exit(self, worker)
            except Exception:
                self.log.warning("Exception during worker exit:\n%s",
                                 traceback.format_exc())

    def spawn_workers(self):
        """\
        Spawn new workers as needed.

        This is where a worker process leaves the main loop
        of the master process.
        """

        for _ in range(self.num_workers - len(self.WORKERS)):
            self.spawn_worker()
            time.sleep(0.1 * random.random())

    def kill_workers(self, sig):
        """\
        Kill all workers with the signal `sig`
        :attr sig: `signal.SIG*` value
        """
        worker_pids = list(self.WORKERS.keys())
        for pid in worker_pids:
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
