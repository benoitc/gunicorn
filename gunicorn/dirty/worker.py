#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Dirty Worker Process

Asyncio-based worker that loads dirty apps and handles requests
from the DirtyArbiter.
"""

import asyncio
import os
import signal
import traceback
import uuid

from gunicorn import util
from gunicorn.workers.workertmp import WorkerTmp

from .app import load_dirty_apps
from .errors import DirtyAppError, DirtyAppNotFoundError, DirtyWorkerError
from .protocol import (
    DirtyProtocol,
    make_response,
    make_error_response,
)


class DirtyWorker:
    """
    Dirty worker process that loads dirty apps and handles requests.

    Each worker runs its own asyncio event loop and listens on a
    worker-specific Unix socket for requests from the DirtyArbiter.
    """

    SIGNALS = [getattr(signal, "SIG%s" % x) for x in
               "ABRT HUP QUIT INT TERM USR1".split()]

    def __init__(self, age, ppid, app_paths, cfg, log, socket_path):
        """
        Initialize a dirty worker.

        Args:
            age: Worker age (for identifying workers)
            ppid: Parent process ID
            app_paths: List of dirty app import paths
            cfg: Gunicorn config
            log: Logger
            socket_path: Path to this worker's Unix socket
        """
        self.age = age
        self.pid = "[booting]"
        self.ppid = ppid
        self.app_paths = app_paths
        self.cfg = cfg
        self.log = log
        self.socket_path = socket_path
        self.booted = False
        self.aborted = False
        self.alive = True
        self.tmp = WorkerTmp(cfg)
        self.apps = {}
        self._server = None
        self._loop = None

    def __str__(self):
        return f"<DirtyWorker {self.pid}>"

    def notify(self):
        """Update heartbeat timestamp."""
        self.tmp.notify()

    def init_process(self):
        """
        Initialize the worker process after fork.

        This is called in the child process after fork. It sets up
        the environment, loads apps, and starts the main run loop.
        """
        # Set environment variables
        if self.cfg.env:
            for k, v in self.cfg.env.items():
                os.environ[k] = v

        util.set_owner_process(self.cfg.uid, self.cfg.gid,
                               initgroups=self.cfg.initgroups)

        # Reseed random number generator
        util.seed()

        # Prevent fd inheritance
        util.close_on_exec(self.tmp.fileno())
        self.log.close_on_exec()

        # Set up signals
        self.init_signals()

        # Load dirty apps
        self.load_apps()

        # Call hook
        self.cfg.dirty_worker_init(self)

        # Enter main run loop
        self.pid = os.getpid()
        self.booted = True
        self.run()

    def init_signals(self):
        """Set up signal handlers."""
        # Reset signal handlers from parent
        for sig in self.SIGNALS:
            signal.signal(sig, signal.SIG_DFL)

        # Handle graceful shutdown
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGQUIT, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        # Handle abort (timeout)
        signal.signal(signal.SIGABRT, self._signal_handler)

        # Handle USR1 (reopen logs)
        signal.signal(signal.SIGUSR1, self._signal_handler)

    def _signal_handler(self, sig, frame):
        """Handle signals by setting alive = False."""
        if sig == signal.SIGUSR1:
            self.log.reopen_files()
            return

        self.alive = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._shutdown)

    def _shutdown(self):
        """Initiate async shutdown."""
        if self._server:
            self._server.close()

    def load_apps(self):
        """Load all configured dirty apps."""
        try:
            self.apps = load_dirty_apps(self.app_paths)
            for path, app in self.apps.items():
                self.log.debug("Loaded dirty app: %s", path)
                try:
                    app.init()
                    self.log.info("Initialized dirty app: %s", path)
                except Exception as e:
                    self.log.error("Failed to initialize dirty app %s: %s",
                                   path, e)
                    raise
        except Exception as e:
            self.log.error("Failed to load dirty apps: %s", e)
            raise

    def run(self):
        """Run the main asyncio event loop."""
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._run_async())
        except Exception as e:
            self.log.error("Worker error: %s", e)
        finally:
            self._cleanup()

    async def _run_async(self):
        """Main async loop - start server and handle connections."""
        # Remove socket if it exists
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

        # Start Unix socket server
        self._server = await asyncio.start_unix_server(
            self.handle_connection,
            path=self.socket_path
        )

        # Make socket accessible
        os.chmod(self.socket_path, 0o600)

        self.log.info("Dirty worker %s listening on %s",
                      self.pid, self.socket_path)

        # Start heartbeat task
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        try:
            async with self._server:
                await self._server.serve_forever()
        except asyncio.CancelledError:
            pass
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

    async def _heartbeat_loop(self):
        """Periodically update heartbeat."""
        while self.alive:
            self.notify()
            await asyncio.sleep(self.cfg.dirty_timeout / 2.0)

    async def handle_connection(self, reader, writer):
        """
        Handle a connection from the arbiter.

        Each connection can send multiple requests.
        """
        self.log.debug("New connection from arbiter")

        try:
            while self.alive:
                try:
                    message = await DirtyProtocol.read_message_async(reader)
                except asyncio.IncompleteReadError:
                    # Connection closed
                    break

                # Handle the request
                response = await self.handle_request(message)

                # Send response
                await DirtyProtocol.write_message_async(writer, response)
        except Exception as e:
            self.log.error("Connection error: %s", e)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def handle_request(self, message):
        """
        Handle a single request message.

        Args:
            message: Request dict from protocol

        Returns:
            Response dict to send back
        """
        request_id = message.get("id", str(uuid.uuid4()))
        msg_type = message.get("type")

        if msg_type != DirtyProtocol.MSG_TYPE_REQUEST:
            return make_error_response(
                request_id,
                DirtyWorkerError(f"Unknown message type: {msg_type}")
            )

        app_path = message.get("app_path")
        action = message.get("action")
        args = message.get("args", [])
        kwargs = message.get("kwargs", {})

        # Update heartbeat before executing
        self.notify()

        try:
            result = await self.execute(app_path, action, args, kwargs)
            return make_response(request_id, result)
        except Exception as e:
            tb = traceback.format_exc()
            self.log.error("Error executing %s.%s: %s\n%s",
                           app_path, action, e, tb)
            return make_error_response(
                request_id,
                DirtyAppError(str(e), app_path=app_path, action=action,
                              traceback=tb)
            )

    async def execute(self, app_path, action, args, kwargs):
        """
        Execute an action on a dirty app.

        Args:
            app_path: Import path of the dirty app
            action: Action name to execute
            args: Positional arguments
            kwargs: Keyword arguments

        Returns:
            Result from the app action

        Raises:
            DirtyAppNotFoundError: If app is not loaded
            DirtyAppError: If execution fails
        """
        if app_path not in self.apps:
            raise DirtyAppNotFoundError(app_path)

        app = self.apps[app_path]

        # Run the app call in a thread pool to avoid blocking
        # the event loop for CPU-bound operations
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: app(action, *args, **kwargs)
        )
        return result

    def _cleanup(self):
        """Clean up resources on shutdown."""
        # Close all apps
        for path, app in self.apps.items():
            try:
                app.close()
                self.log.debug("Closed dirty app: %s", path)
            except Exception as e:
                self.log.error("Error closing dirty app %s: %s", path, e)

        # Close temp file
        try:
            self.tmp.close()
        except Exception:
            pass

        # Remove socket file
        try:
            if os.path.exists(self.socket_path):
                os.unlink(self.socket_path)
        except Exception:
            pass

        self.log.info("Dirty worker %s exiting", self.pid)
