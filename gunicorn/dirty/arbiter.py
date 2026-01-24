#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Dirty Arbiter Process

Asyncio-based arbiter that manages the dirty worker pool and routes
requests from HTTP workers to available dirty workers.
"""

import asyncio
import errno
import os
import signal
import sys
import tempfile
import time
import traceback

from gunicorn import util

from .errors import DirtyError, DirtyTimeoutError, DirtyWorkerError
from .protocol import (
    DirtyProtocol,
    make_error_response,
)
from .worker import DirtyWorker


class DirtyArbiter:
    """
    Dirty arbiter that manages the dirty worker pool.

    The arbiter runs an asyncio event loop and handles:
    - Spawning and managing dirty worker processes
    - Accepting connections from HTTP workers
    - Routing requests to available dirty workers
    - Monitoring worker health via heartbeat
    """

    SIGNALS = [getattr(signal, "SIG%s" % x) for x in
               "HUP QUIT INT TERM USR1 USR2 CHLD".split()]

    # Worker boot error code
    WORKER_BOOT_ERROR = 3

    def __init__(self, cfg, log, socket_path=None):
        """
        Initialize the dirty arbiter.

        Args:
            cfg: Gunicorn config
            log: Logger
            socket_path: Path to the arbiter's Unix socket
        """
        self.cfg = cfg
        self.log = log
        self.pid = None
        self.ppid = os.getpid()

        # Use a temp directory for sockets
        self.tmpdir = tempfile.mkdtemp(prefix="gunicorn-dirty-")
        self.socket_path = socket_path or os.path.join(
            self.tmpdir, "arbiter.sock"
        )

        self.workers = {}  # pid -> DirtyWorker
        self.worker_sockets = {}  # pid -> socket_path
        self.worker_connections = {}  # pid -> (reader, writer)
        self.worker_age = 0
        self.alive = True

        self._server = None
        self._loop = None
        self._pending_requests = {}  # request_id -> Future

    def run(self):
        """Run the dirty arbiter (blocking call)."""
        self.pid = os.getpid()
        self.log.info("Dirty arbiter starting (pid: %s)", self.pid)

        # Call hook
        self.cfg.on_dirty_starting(self)

        # Set up signal handlers
        self.init_signals()

        # Set process title
        util._setproctitle("dirty-arbiter")

        try:
            asyncio.run(self._run_async())
        except KeyboardInterrupt:
            pass
        finally:
            self._cleanup_sync()

    def init_signals(self):
        """Set up signal handlers."""
        for sig in self.SIGNALS:
            signal.signal(sig, signal.SIG_DFL)

        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGQUIT, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGHUP, self._signal_handler)
        signal.signal(signal.SIGUSR1, self._signal_handler)
        signal.signal(signal.SIGCHLD, self._signal_handler)

    def _signal_handler(self, sig, frame):
        """Handle signals."""
        if sig == signal.SIGCHLD:
            # Child exited - will be handled in reap_workers
            if self._loop:
                self._loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(self._handle_sigchld())
                )
            return

        if sig == signal.SIGUSR1:
            # Reopen log files
            self.log.reopen_files()
            return

        if sig == signal.SIGHUP:
            # Reload workers
            if self._loop:
                self._loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(self.reload())
                )
            return

        # Shutdown signals
        self.alive = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._shutdown)

    def _shutdown(self):
        """Initiate async shutdown."""
        if self._server:
            self._server.close()

    async def _run_async(self):
        """Main async loop - start server, manage workers."""
        self._loop = asyncio.get_running_loop()

        # Remove socket if it exists
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

        # Start Unix socket server for HTTP workers
        self._server = await asyncio.start_unix_server(
            self.handle_client,
            path=self.socket_path
        )

        # Make socket accessible
        os.chmod(self.socket_path, 0o600)

        self.log.info("Dirty arbiter listening on %s", self.socket_path)

        # Spawn initial workers
        await self.manage_workers()

        # Start periodic tasks
        monitor_task = asyncio.create_task(self._worker_monitor())

        try:
            async with self._server:
                await self._server.serve_forever()
        except asyncio.CancelledError:
            pass
        finally:
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass

            await self.stop()

    async def _worker_monitor(self):
        """Periodically check worker health and manage pool."""
        while self.alive:
            await asyncio.sleep(1.0)
            await self.murder_workers()
            await self.manage_workers()

    async def _handle_sigchld(self):
        """Handle SIGCHLD - reap dead workers."""
        self.reap_workers()
        await self.manage_workers()

    async def handle_client(self, reader, writer):
        """
        Handle a connection from an HTTP worker.

        Routes requests to available dirty workers and returns responses.
        """
        self.log.debug("New client connection from HTTP worker")

        try:
            while self.alive:
                try:
                    message = await DirtyProtocol.read_message_async(reader)
                except asyncio.IncompleteReadError:
                    break

                # Route request to a dirty worker
                response = await self.route_request(message)

                # Send response back to HTTP worker
                await DirtyProtocol.write_message_async(writer, response)
        except Exception as e:
            self.log.error("Client connection error: %s", e)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def route_request(self, request):
        """
        Route a request to an available dirty worker.

        Args:
            request: Request message dict

        Returns:
            Response message dict
        """
        request_id = request.get("id", "unknown")

        # Find an available worker
        worker_pid = await self._get_available_worker()
        if worker_pid is None:
            return make_error_response(
                request_id,
                DirtyError("No dirty workers available")
            )

        try:
            # Get or establish connection to worker
            reader, writer = await self._get_worker_connection(worker_pid)

            # Send request to worker
            await DirtyProtocol.write_message_async(writer, request)

            # Wait for response with timeout
            try:
                response = await asyncio.wait_for(
                    DirtyProtocol.read_message_async(reader),
                    timeout=self.cfg.dirty_timeout
                )
                return response
            except asyncio.TimeoutError:
                return make_error_response(
                    request_id,
                    DirtyTimeoutError("Worker timeout", self.cfg.dirty_timeout)
                )
        except Exception as e:
            self.log.error("Error routing request to worker %s: %s",
                           worker_pid, e)
            # Remove failed connection
            self._close_worker_connection(worker_pid)
            return make_error_response(
                request_id,
                DirtyWorkerError(f"Worker communication failed: {e}",
                                 worker_id=worker_pid)
            )

    async def _get_available_worker(self):
        """Get an available worker PID."""
        for pid in list(self.workers.keys()):
            # For now, just return first worker
            # Future: implement load balancing
            return pid
        return None

    async def _get_worker_connection(self, worker_pid):
        """Get or create connection to a worker."""
        if worker_pid in self.worker_connections:
            return self.worker_connections[worker_pid]

        socket_path = self.worker_sockets.get(worker_pid)
        if not socket_path:
            raise DirtyError(f"No socket for worker {worker_pid}")

        # Wait for socket to be available
        for _ in range(50):  # 5 seconds max
            if os.path.exists(socket_path):
                break
            await asyncio.sleep(0.1)
        else:
            raise DirtyError(f"Worker socket not ready: {socket_path}")

        reader, writer = await asyncio.open_unix_connection(socket_path)
        self.worker_connections[worker_pid] = (reader, writer)
        return reader, writer

    def _close_worker_connection(self, worker_pid):
        """Close connection to a worker."""
        if worker_pid in self.worker_connections:
            reader, writer = self.worker_connections.pop(worker_pid)
            writer.close()

    async def manage_workers(self):
        """Maintain the number of dirty workers."""
        num_workers = self.cfg.dirty_workers

        # Spawn workers if needed
        while len(self.workers) < num_workers:
            self.spawn_worker()
            await asyncio.sleep(0.1)

        # Kill excess workers
        while len(self.workers) > num_workers:
            # Kill oldest worker
            oldest_pid = min(self.workers.keys(),
                             key=lambda p: self.workers[p].age)
            self.kill_worker(oldest_pid, signal.SIGTERM)
            await asyncio.sleep(0.1)

    def spawn_worker(self):
        """Spawn a new dirty worker."""
        self.worker_age += 1
        socket_path = os.path.join(
            self.tmpdir, f"worker-{self.worker_age}.sock"
        )

        worker = DirtyWorker(
            age=self.worker_age,
            ppid=self.pid,
            app_paths=self.cfg.dirty_apps,
            cfg=self.cfg,
            log=self.log,
            socket_path=socket_path
        )

        pid = os.fork()
        if pid != 0:
            # Parent process
            worker.pid = pid
            self.workers[pid] = worker
            self.worker_sockets[pid] = socket_path
            self.cfg.dirty_post_fork(self, worker)
            self.log.info("Spawned dirty worker (pid: %s)", pid)
            return pid

        # Child process
        worker.pid = os.getpid()
        try:
            util._setproctitle(f"dirty-worker [{self.cfg.proc_name}]")
            worker.init_process()
            sys.exit(0)
        except SystemExit:
            raise
        except Exception as e:
            self.log.exception("Exception in dirty worker process")
            if not worker.booted:
                sys.exit(self.WORKER_BOOT_ERROR)
            sys.exit(-1)

    def kill_worker(self, pid, sig):
        """Kill a worker by PID."""
        try:
            os.kill(pid, sig)
        except OSError as e:
            if e.errno == errno.ESRCH:
                self._cleanup_worker(pid)

    def _cleanup_worker(self, pid):
        """Clean up after a worker exits."""
        self._close_worker_connection(pid)
        worker = self.workers.pop(pid, None)
        if worker:
            self.cfg.dirty_worker_exit(self, worker)
        socket_path = self.worker_sockets.pop(pid, None)
        if socket_path and os.path.exists(socket_path):
            try:
                os.unlink(socket_path)
            except OSError:
                pass

    async def murder_workers(self):
        """Kill workers that have timed out."""
        if not self.cfg.dirty_timeout:
            return

        for pid, worker in list(self.workers.items()):
            try:
                if time.monotonic() - worker.tmp.last_update() <= self.cfg.dirty_timeout:
                    continue
            except (OSError, ValueError):
                continue

            if not worker.aborted:
                self.log.critical("DIRTY WORKER TIMEOUT (pid:%s)", pid)
                worker.aborted = True
                self.kill_worker(pid, signal.SIGABRT)
            else:
                self.kill_worker(pid, signal.SIGKILL)

    def reap_workers(self):
        """Reap dead worker processes."""
        try:
            while True:
                wpid, status = os.waitpid(-1, os.WNOHANG)
                if not wpid:
                    break

                exitcode = None
                if os.WIFEXITED(status):
                    exitcode = os.WEXITSTATUS(status)
                elif os.WIFSIGNALED(status):
                    sig = os.WTERMSIG(status)
                    self.log.warning("Dirty worker (pid:%s) killed by signal %s",
                                     wpid, sig)

                if exitcode == self.WORKER_BOOT_ERROR:
                    self.log.error("Dirty worker failed to boot (pid:%s)", wpid)

                self._cleanup_worker(wpid)
                self.log.info("Dirty worker exited (pid:%s)", wpid)
        except OSError as e:
            if e.errno != errno.ECHILD:
                raise

    async def reload(self):
        """Reload workers (SIGHUP handling)."""
        self.log.info("Reloading dirty workers")

        # Spawn new workers
        for _ in range(self.cfg.dirty_workers):
            self.spawn_worker()
            await asyncio.sleep(0.1)

        # Kill old workers
        old_workers = list(self.workers.keys())
        for pid in old_workers[self.cfg.dirty_workers:]:
            self.kill_worker(pid, signal.SIGTERM)

    async def stop(self, graceful=True):
        """Stop all workers."""
        sig = signal.SIGTERM if graceful else signal.SIGQUIT
        limit = time.time() + self.cfg.dirty_graceful_timeout

        # Signal all workers
        for pid in list(self.workers.keys()):
            self.kill_worker(pid, sig)

        # Wait for workers to exit
        while self.workers and time.time() < limit:
            self.reap_workers()
            await asyncio.sleep(0.1)

        # Force kill remaining workers
        for pid in list(self.workers.keys()):
            self.kill_worker(pid, signal.SIGKILL)
        self.reap_workers()

    def _cleanup_sync(self):
        """Synchronous cleanup on exit."""
        # Clean up socket
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass

        # Clean up temp directory
        try:
            for f in os.listdir(self.tmpdir):
                os.unlink(os.path.join(self.tmpdir, f))
            os.rmdir(self.tmpdir)
        except OSError:
            pass

        self.log.info("Dirty arbiter exiting (pid: %s)", self.pid)
