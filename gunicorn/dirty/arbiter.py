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

from gunicorn import util

from .app import get_app_workers_attribute, parse_dirty_app_spec
from .errors import (
    DirtyError,
    DirtyNoWorkersAvailableError,
    DirtyTimeoutError,
    DirtyWorkerError,
)
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

    def __init__(self, cfg, log, socket_path=None, pidfile=None):
        """
        Initialize the dirty arbiter.

        Args:
            cfg: Gunicorn config
            log: Logger
            socket_path: Path to the arbiter's Unix socket
            pidfile: Well-known PID file location for orphan detection
        """
        self.cfg = cfg
        self.log = log
        self.pid = None
        self.ppid = os.getpid()
        self.pidfile = pidfile  # Well-known location for orphan detection

        # Use a temp directory for sockets
        self.tmpdir = tempfile.mkdtemp(prefix="gunicorn-dirty-")
        self.socket_path = socket_path or os.path.join(
            self.tmpdir, "arbiter.sock"
        )

        self.workers = {}  # pid -> DirtyWorker
        self.worker_sockets = {}  # pid -> socket_path
        self.worker_connections = {}  # pid -> (reader, writer)
        self.worker_queues = {}  # pid -> asyncio.Queue
        self.worker_consumers = {}  # pid -> asyncio.Task
        self._worker_rr_index = 0  # Round-robin index for worker selection
        self.worker_age = 0
        self.alive = True

        self._server = None
        self._loop = None
        self._pending_requests = {}  # request_id -> Future

        # Per-app worker allocation tracking
        # Maps import_path -> {import_path, worker_count, original_spec}
        self.app_specs = {}
        # Maps import_path -> set of worker PIDs that have loaded the app
        self.app_worker_map = {}
        # Maps worker_pid -> list of import_paths loaded by this worker
        self.worker_app_map = {}
        # Per-app round-robin indices for routing
        self._app_rr_indices = {}
        # Queue of app lists from dead workers to respawn with same apps
        self._pending_respawns = []

        # Parse app specs on init
        self._parse_app_specs()

    def _parse_app_specs(self):
        """
        Parse all app specifications from config.

        Populates self.app_specs with parsed information about each app,
        including the import path and worker count limits.

        Worker count priority:
        1. Config override (e.g., "module:Class:2") - highest priority
        2. Class attribute (e.g., workers = 2 on the class)
        3. None (all workers) - default
        """
        for spec in self.cfg.dirty_apps:
            import_path, worker_count = parse_dirty_app_spec(spec)

            # If no config override, check class attribute
            if worker_count is None:
                try:
                    worker_count = get_app_workers_attribute(import_path)
                except Exception as e:
                    # Log but don't fail - we'll discover the error when loading
                    self.log.warning(
                        "Could not read workers attribute from %s: %s",
                        import_path, e
                    )

            self.app_specs[import_path] = {
                'import_path': import_path,
                'worker_count': worker_count,
                'original_spec': spec,
            }
            # Initialize the app_worker_map for this app
            self.app_worker_map[import_path] = set()

    def _get_apps_for_new_worker(self):
        """
        Determine which apps a new worker should load.

        Returns a list of import paths for apps that need more workers.
        Apps with workers=None (all workers) are always included.
        Apps with worker limits are included only if they haven't
        reached their limit yet.

        Returns:
            List of import paths to load, or empty list if no apps need workers
        """
        app_paths = []

        for import_path, spec in self.app_specs.items():
            worker_count = spec['worker_count']
            current_workers = len(self.app_worker_map.get(import_path, set()))

            # None means all workers should load this app
            if worker_count is None:
                app_paths.append(import_path)
            # Otherwise check if we've reached the limit
            elif current_workers < worker_count:
                app_paths.append(import_path)

        return app_paths

    def _register_worker_apps(self, worker_pid, app_paths):
        """
        Register which apps a worker has loaded.

        Updates both app_worker_map and worker_app_map to track the
        bidirectional relationship between workers and apps.

        Args:
            worker_pid: The PID of the worker
            app_paths: List of app import paths loaded by this worker
        """
        self.worker_app_map[worker_pid] = list(app_paths)

        for app_path in app_paths:
            if app_path not in self.app_worker_map:
                self.app_worker_map[app_path] = set()
            self.app_worker_map[app_path].add(worker_pid)

    def _unregister_worker(self, worker_pid):
        """
        Unregister a worker's apps when it exits.

        Removes the worker from all tracking maps.

        Args:
            worker_pid: The PID of the worker to unregister
        """
        # Get the apps this worker had
        app_paths = self.worker_app_map.pop(worker_pid, [])

        # Remove worker from each app's worker set
        for app_path in app_paths:
            if app_path in self.app_worker_map:
                self.app_worker_map[app_path].discard(worker_pid)

    def run(self):
        """Run the dirty arbiter (blocking call)."""
        self.pid = os.getpid()
        self.log.info("Dirty arbiter starting (pid: %s)", self.pid)

        # Write PID to well-known location for orphan detection
        if self.pidfile:
            try:
                with open(self.pidfile, 'w') as f:
                    f.write(str(self.pid))
            except IOError as e:
                self.log.warning("Failed to write PID file: %s", e)

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

            # Check if parent (main arbiter) died unexpectedly
            if os.getppid() != self.ppid:
                self.log.warning("Parent changed, shutting down dirty arbiter")
                self.alive = False
                self._shutdown()
                return

            await self.murder_workers()
            await self.manage_workers()

    async def _handle_sigchld(self):
        """Handle SIGCHLD - reap dead workers."""
        self.reap_workers()
        # Only spawn new workers if we're still alive
        if self.alive:
            await self.manage_workers()

    async def handle_client(self, reader, writer):
        """
        Handle a connection from an HTTP worker.

        Routes requests to available dirty workers and returns responses.
        Supports both regular responses and streaming (chunk-based) responses.
        """
        self.log.debug("New client connection from HTTP worker")

        try:
            while self.alive:
                try:
                    message = await DirtyProtocol.read_message_async(reader)
                except asyncio.IncompleteReadError:
                    break

                # Route request to a dirty worker - pass writer for streaming
                await self.route_request(message, writer)
        except Exception as e:
            self.log.error("Client connection error: %s", e)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def route_request(self, request, client_writer):
        """
        Route a request to an available dirty worker via queue.

        Each worker has a dedicated queue and consumer task. Requests are
        submitted to the queue and processed sequentially by the consumer.

        For streaming responses, messages (chunks) are forwarded directly
        to the client_writer as they arrive from the worker.

        Args:
            request: Request message dict
            client_writer: StreamWriter to send responses to client
        """
        request_id = request.get("id", "unknown")
        app_path = request.get("app_path")

        # Find an available worker (filtered by app if specified)
        worker_pid = await self._get_available_worker(app_path)
        if worker_pid is None:
            # Distinguish between no workers at all vs. no workers for this app
            if not self.workers:
                error = DirtyError("No dirty workers available")
            elif app_path and self.app_specs:
                # Per-app allocation is configured and no workers have this app
                error = DirtyNoWorkersAvailableError(app_path)
            else:
                error = DirtyError("No dirty workers available")
            response = make_error_response(request_id, error)
            await DirtyProtocol.write_message_async(client_writer, response)
            return

        # Get queue (start consumer if needed)
        if worker_pid not in self.worker_queues:
            await self._start_worker_consumer(worker_pid)

        queue = self.worker_queues[worker_pid]
        future = asyncio.get_running_loop().create_future()

        # Submit request to queue with client writer for streaming support
        await queue.put((request, client_writer, future))

        # Wait for completion (streaming messages forwarded by consumer)
        try:
            await future
        except Exception as e:
            response = make_error_response(
                request_id,
                DirtyWorkerError(f"Request failed: {e}", worker_id=worker_pid)
            )
            await DirtyProtocol.write_message_async(client_writer, response)

    async def _start_worker_consumer(self, worker_pid):
        """Start a consumer task for a worker's request queue."""
        queue = asyncio.Queue()
        self.worker_queues[worker_pid] = queue

        async def consumer():
            while self.alive:
                try:
                    request, client_writer, future = await queue.get()
                    try:
                        await self._execute_on_worker(
                            worker_pid, request, client_writer
                        )
                        if not future.done():
                            future.set_result(None)
                    except Exception as e:
                        if not future.done():
                            future.set_exception(e)
                    finally:
                        queue.task_done()
                except asyncio.CancelledError:
                    break

        task = asyncio.create_task(consumer())
        self.worker_consumers[worker_pid] = task

    async def _execute_on_worker(self, worker_pid, request, client_writer):
        """
        Execute request on a specific worker (called by consumer).

        Handles both regular responses and streaming (chunk-based) responses.
        For streaming, chunk and end messages are forwarded directly to the
        client_writer as they arrive from the worker.
        """
        request_id = request.get("id", "unknown")

        try:
            reader, writer = await self._get_worker_connection(worker_pid)
            await DirtyProtocol.write_message_async(writer, request)

            # Read messages until we get a response, end, or error
            while True:
                try:
                    message = await asyncio.wait_for(
                        DirtyProtocol.read_message_async(reader),
                        timeout=self.cfg.dirty_timeout
                    )
                except asyncio.TimeoutError:
                    response = make_error_response(
                        request_id,
                        DirtyTimeoutError("Worker timeout", self.cfg.dirty_timeout)
                    )
                    await DirtyProtocol.write_message_async(client_writer, response)
                    return

                msg_type = message.get("type")

                # Forward chunk messages to client
                if msg_type == DirtyProtocol.MSG_TYPE_CHUNK:
                    await DirtyProtocol.write_message_async(client_writer, message)
                    continue

                # Forward end message and complete
                if msg_type == DirtyProtocol.MSG_TYPE_END:
                    await DirtyProtocol.write_message_async(client_writer, message)
                    return

                # Forward response or error and complete
                if msg_type in (DirtyProtocol.MSG_TYPE_RESPONSE,
                                DirtyProtocol.MSG_TYPE_ERROR):
                    await DirtyProtocol.write_message_async(client_writer, message)
                    return

                # Unknown message type - log and continue
                self.log.warning("Unknown message type from worker: %s", msg_type)

        except Exception as e:
            self.log.error("Error executing on worker %s: %s", worker_pid, e)
            self._close_worker_connection(worker_pid)
            response = make_error_response(
                request_id,
                DirtyWorkerError(f"Worker communication failed: {e}",
                                 worker_id=worker_pid)
            )
            await DirtyProtocol.write_message_async(client_writer, response)

    async def _get_available_worker(self, app_path=None):
        """
        Get an available worker PID using round-robin selection.

        If app_path is provided, only returns workers that have loaded
        that specific app. Uses per-app round-robin to ensure fair
        distribution among eligible workers.

        Args:
            app_path: Optional import path of the target app. If None,
                     returns any worker using global round-robin.

        Returns:
            Worker PID or None if no eligible workers are available.
        """
        # Determine eligible workers
        if app_path and self.app_specs:
            # Per-app allocation is configured - must return a worker
            # that has this specific app
            if app_path in self.app_worker_map:
                eligible_pids = list(self.app_worker_map[app_path])
            else:
                # App not known or no workers have it
                return None
        else:
            # No specific app requested, or no app specs configured
            # (backward compatible) - any worker will do
            eligible_pids = list(self.workers.keys())

        if not eligible_pids:
            return None

        # Per-app round-robin for fairness
        if app_path and self.app_specs:
            idx = self._app_rr_indices.get(app_path, 0)
            self._app_rr_indices[app_path] = (idx + 1) % len(eligible_pids)
        else:
            idx = self._worker_rr_index
            self._worker_rr_index = (idx + 1) % len(eligible_pids)

        return eligible_pids[idx % len(eligible_pids)]

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
            _reader, writer = self.worker_connections.pop(worker_pid)
            writer.close()

    async def manage_workers(self):
        """Maintain the number of dirty workers."""
        if not self.alive:
            return

        num_workers = self.cfg.dirty_workers

        # Spawn workers if needed
        while self.alive and len(self.workers) < num_workers:
            result = self.spawn_worker()
            if result is None:
                # No apps need more workers - stop spawning
                break
            await asyncio.sleep(0.1)

        # Kill excess workers
        while len(self.workers) > num_workers:
            # Kill oldest worker
            oldest_pid = min(self.workers.keys(),
                             key=lambda p: self.workers[p].age)
            self.kill_worker(oldest_pid, signal.SIGTERM)
            await asyncio.sleep(0.1)

    def spawn_worker(self):
        """
        Spawn a new dirty worker.

        Worker app assignment follows these priorities:
        1. If there are pending respawns (from dead workers), use those apps
        2. Otherwise, determine apps for a new worker based on allocation

        Returns:
            Worker PID in parent process, or None if no apps need workers
        """
        # Priority 1: Respawn dead worker with same apps
        if self._pending_respawns:
            app_paths = self._pending_respawns.pop(0)
        else:
            # Priority 2: New worker for initial pool
            app_paths = self._get_apps_for_new_worker()

        if not app_paths:
            self.log.warning("No apps need more workers, skipping spawn")
            return None

        self.worker_age += 1
        socket_path = os.path.join(
            self.tmpdir, f"worker-{self.worker_age}.sock"
        )

        worker = DirtyWorker(
            age=self.worker_age,
            ppid=self.pid,
            app_paths=app_paths,  # Only assigned apps, not all apps
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

            # Register which apps this worker has
            self._register_worker_apps(pid, app_paths)

            self.cfg.dirty_post_fork(self, worker)
            self.log.info("Spawned dirty worker (pid: %s) with apps: %s",
                          pid, app_paths)
            return pid

        # Child process
        worker.pid = os.getpid()
        try:
            util._setproctitle(f"dirty-worker [{self.cfg.proc_name}]")
            worker.init_process()
            sys.exit(0)
        except SystemExit:
            raise
        except Exception:
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
        """
        Clean up after a worker exits.

        Saves the dead worker's app list to pending respawns so the
        replacement worker gets the same apps.
        """
        self._close_worker_connection(pid)

        # Cancel consumer task
        if pid in self.worker_consumers:
            self.worker_consumers[pid].cancel()
            del self.worker_consumers[pid]

        # Remove queue
        self.worker_queues.pop(pid, None)

        # Save dead worker's apps for respawn BEFORE unregistering
        if pid in self.worker_app_map:
            dead_apps = list(self.worker_app_map[pid])
            if dead_apps:
                self._pending_respawns.append(dead_apps)

        # Now safe to unregister the worker's apps
        self._unregister_worker(pid)

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
        # Cancel all consumer tasks
        for task in self.worker_consumers.values():
            task.cancel()

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
        # Remove PID file
        if self.pidfile and os.path.exists(self.pidfile):
            try:
                os.unlink(self.pidfile)
            except OSError:
                pass

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
