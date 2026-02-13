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

# gunicorn.dirty is imported lazily in spawn_dirty_arbiter() for gevent compatibility


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

        # Dirty arbiter process
        self.dirty_arbiter_pid = 0
        self.dirty_arbiter = None
        self.dirty_pidfile = None  # Well-known location for orphan detection

        # Control socket server
        self._control_server = None

        # Stats tracking
        self._stats = {
            'start_time': None,
            'workers_spawned': 0,
            'workers_killed': 0,
            'reloads': 0,
        }

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

        # Initialize stats tracking
        self._stats['start_time'] = time.time()

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

        # Start dirty arbiter if configured
        if self.cfg.dirty_workers > 0 and self.cfg.dirty_apps:
            self.spawn_dirty_arbiter()

        # Start control socket server
        self._start_control_server()

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
                self.manage_dirty_arbiter()
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
        self.reap_dirty_arbiter()

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
        # Forward to dirty arbiter
        if self.dirty_arbiter_pid:
            self.kill_dirty_arbiter(signal.SIGHUP)

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
        # Forward to dirty arbiter
        if self.dirty_arbiter_pid:
            self.kill_dirty_arbiter(signal.SIGUSR1)

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
        # Stop control socket server first
        self._stop_control_server()

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

        # Stop dirty arbiter
        if self.dirty_arbiter_pid:
            self.kill_dirty_arbiter(sig)

        # instruct the workers to exit
        self.kill_workers(sig)
        # wait until the graceful timeout
        quick_shutdown = not graceful
        while (self.WORKERS or self.dirty_arbiter_pid) and time.time() < limit:
            # Check for SIGINT/SIGQUIT to trigger quick shutdown
            if not quick_shutdown:
                try:
                    pending_sig = self.SIG_QUEUE.get_nowait()
                    if pending_sig in (signal.SIGINT, signal.SIGQUIT):
                        self.log.info("Quick shutdown requested")
                        quick_shutdown = True
                        self.kill_workers(signal.SIGQUIT)
                        if self.dirty_arbiter_pid:
                            self.kill_dirty_arbiter(signal.SIGQUIT)
                        # Give workers a short time to exit cleanly
                        limit = time.time() + 2.0
                except Exception:
                    pass
            self.reap_workers()
            self.reap_dirty_arbiter()
            time.sleep(0.1)

        self.kill_workers(signal.SIGKILL)
        if self.dirty_arbiter_pid:
            self.kill_dirty_arbiter(signal.SIGKILL)
        # Final reap to clean up any remaining zombies
        self.reap_workers()
        self.reap_dirty_arbiter()

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
        # Track reload stats
        self._stats['reloads'] += 1

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
            self._stats['workers_spawned'] += 1
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
            # Track kills only on SIGTERM/SIGKILL (actual termination signals)
            if sig in (signal.SIGTERM, signal.SIGKILL):
                self._stats['workers_killed'] += 1
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

    # =========================================================================
    # Dirty Arbiter Management
    # =========================================================================

    def _get_dirty_pidfile_path(self):
        """Get the well-known PID file path for orphan detection.

        Uses self.proc_name (not self.cfg.proc_name) so that during USR2
        the new master gets a different PID file path ("myapp.2" vs "myapp").
        This prevents the old dirty arbiter from removing the new one's PID file.
        """
        import tempfile
        safe_name = self.proc_name.replace('/', '_').replace(' ', '_')
        return os.path.join(tempfile.gettempdir(), f"gunicorn-dirty-{safe_name}.pid")

    def _cleanup_orphaned_dirty_arbiter(self):
        """Kill any orphaned dirty arbiter from a previous crash.

        Only runs on fresh start (master_pid == 0), not during USR2.
        """
        # During USR2, master_pid is set - don't cleanup old dirty arbiter
        if self.master_pid != 0:
            return

        pidfile = self._get_dirty_pidfile_path()
        if not os.path.exists(pidfile):
            return

        try:
            with open(pidfile) as f:
                old_pid = int(f.read().strip())

            # Check if process exists
            os.kill(old_pid, 0)
            # Process exists - kill orphan
            self.log.warning("Killing orphaned dirty arbiter (pid: %s)", old_pid)
            os.kill(old_pid, signal.SIGTERM)
            # Wait briefly for graceful exit
            for _ in range(10):
                time.sleep(0.1)
                try:
                    os.kill(old_pid, 0)
                except OSError:
                    break
            else:
                os.kill(old_pid, signal.SIGKILL)
        except (ValueError, IOError, OSError):
            pass

        # Remove stale PID file
        try:
            os.unlink(pidfile)
        except OSError:
            pass

    def spawn_dirty_arbiter(self):
        """\
        Spawn the dirty arbiter process.

        The dirty arbiter manages a separate pool of workers for
        long-running, blocking operations.
        """
        # Lazy import for gevent compatibility (see #3482)
        from gunicorn.dirty import DirtyArbiter, set_dirty_socket_path

        if self.dirty_arbiter_pid:
            return  # Already running

        # Cleanup any orphaned dirty arbiter from previous crash
        self._cleanup_orphaned_dirty_arbiter()

        # Get well-known PID file path
        self.dirty_pidfile = self._get_dirty_pidfile_path()

        self.dirty_arbiter = DirtyArbiter(
            self.cfg, self.log,
            pidfile=self.dirty_pidfile
        )
        socket_path = self.dirty_arbiter.socket_path

        pid = os.fork()
        if pid != 0:
            # Parent process
            self.dirty_arbiter_pid = pid
            # Set socket path for HTTP workers to use
            set_dirty_socket_path(socket_path)
            os.environ['GUNICORN_DIRTY_SOCKET'] = socket_path
            self.log.info("Spawned dirty arbiter (pid: %s) at %s",
                          pid, socket_path)
            return pid

        # Child process - run the dirty arbiter
        try:
            self.dirty_arbiter.run()
            sys.exit(0)
        except SystemExit:
            raise
        except Exception:
            self.log.exception("Exception in dirty arbiter process")
            sys.exit(-1)

    def kill_dirty_arbiter(self, sig):
        """\
        Send a signal to the dirty arbiter.

        :attr sig: `signal.SIG*` value
        """
        if not self.dirty_arbiter_pid:
            return

        try:
            os.kill(self.dirty_arbiter_pid, sig)
        except OSError as e:
            if e.errno == errno.ESRCH:
                self.dirty_arbiter_pid = 0
                self.dirty_arbiter = None

    def reap_dirty_arbiter(self):
        """\
        Reap the dirty arbiter process if it has exited.
        """
        if not self.dirty_arbiter_pid:
            return

        try:
            wpid, status = os.waitpid(self.dirty_arbiter_pid, os.WNOHANG)
            if not wpid:
                return

            if os.WIFEXITED(status):
                exitcode = os.WEXITSTATUS(status)
                if exitcode != 0:
                    self.log.error("Dirty arbiter (pid:%s) exited with code %s",
                                   wpid, exitcode)
                else:
                    self.log.info("Dirty arbiter (pid:%s) exited", wpid)
            elif os.WIFSIGNALED(status):
                sig = os.WTERMSIG(status)
                self.log.warning("Dirty arbiter (pid:%s) killed by signal %s",
                                 wpid, sig)

            self.dirty_arbiter_pid = 0
            self.dirty_arbiter = None
        except OSError as e:
            if e.errno == errno.ECHILD:
                self.dirty_arbiter_pid = 0
                self.dirty_arbiter = None

    def manage_dirty_arbiter(self):
        """\
        Maintain the dirty arbiter process by respawning if needed.
        """
        if self.dirty_arbiter_pid:
            return  # Already running

        if self.cfg.dirty_workers > 0 and self.cfg.dirty_apps:
            self.log.info("Spawning dirty arbiter...")
            self.spawn_dirty_arbiter()

    # =========================================================================
    # Control Socket Management
    # =========================================================================

    def _get_control_socket_path(self):
        """Get the control socket path, making relative paths absolute."""
        socket_path = self.cfg.control_socket
        if not os.path.isabs(socket_path):
            socket_path = os.path.join(util.getcwd(), socket_path)
        return socket_path

    def _start_control_server(self):
        """\
        Start the control socket server.

        The server runs in a background thread and accepts commands
        via Unix socket.
        """
        if self.cfg.control_socket_disable:
            self.log.debug("Control socket disabled")
            return

        # Lazy import to avoid circular imports and gevent compatibility
        from gunicorn.ctl.server import ControlSocketServer

        socket_path = self._get_control_socket_path()
        socket_mode = self.cfg.control_socket_mode

        try:
            self._control_server = ControlSocketServer(
                self, socket_path, socket_mode
            )
            self._control_server.start()
        except Exception as e:
            self.log.warning("Failed to start control socket: %s", e)
            self._control_server = None

    def _stop_control_server(self):
        """\
        Stop the control socket server.
        """
        if self._control_server:
            try:
                self._control_server.stop()
            except Exception as e:
                self.log.debug("Error stopping control server: %s", e)
            self._control_server = None
