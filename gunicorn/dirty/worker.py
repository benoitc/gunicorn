#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Dirty Worker Process

Asyncio-based worker that loads dirty apps and handles requests
from the DirtyArbiter.

Threading Model
---------------
Each dirty worker runs an asyncio event loop in the main thread for:
- Handling connections from the arbiter
- Managing heartbeat updates
- Coordinating task execution

Actual app execution runs in a ThreadPoolExecutor (separate threads):
- The number of threads is controlled by ``dirty_threads`` config (default: 1)
- Each thread can execute one app action at a time
- The asyncio event loop is NOT blocked by task execution

State and Global Objects
------------------------
Apps can maintain persistent state because:

1. Apps are loaded ONCE when the worker starts (in ``load_apps()``)
2. The same app instances are reused for ALL requests
3. App state (instance variables, loaded models, etc.) persists

Example::

    class MLApp(DirtyApp):
        def init(self):
            self.model = load_heavy_model()  # Loaded once, reused
            self.cache = {}                   # Persistent cache

        def predict(self, data):
            return self.model.predict(data)  # Uses loaded model

Thread Safety:
- With ``dirty_threads=1`` (default): No concurrent access, thread-safe by design
- With ``dirty_threads > 1``: Multiple threads share the same app instances,
  apps MUST be thread-safe (use locks, thread-local storage, etc.)

Heartbeat and Liveness
----------------------
The worker sends heartbeat updates to prove it's alive:

1. A dedicated asyncio task (``_heartbeat_loop``) runs independently
2. It updates the heartbeat file every ``dirty_timeout / 2`` seconds
3. Since tasks run in executor threads, they do NOT block heartbeats
4. The arbiter kills workers that miss heartbeat updates

Timeout Control
---------------
Execution timeout is enforced at two levels:

1. **Worker level**: Each task execution has a timeout (``dirty_timeout``).
   If exceeded, the worker returns a timeout error but the thread may
   continue running (Python threads cannot be cancelled).

2. **Arbiter level**: The arbiter also enforces timeout when waiting
   for worker response. Workers that don't respond are killed via SIGABRT.

Note: Since Python threads cannot be forcibly cancelled, a truly stuck
operation will continue until the worker is killed by the arbiter.
"""

import asyncio
import inspect
import os
import signal
import traceback
import uuid

from gunicorn import util
from gunicorn.workers.workertmp import WorkerTmp

from .app import load_dirty_apps
from .errors import (
    DirtyAppError,
    DirtyAppNotFoundError,
    DirtyTimeoutError,
    DirtyWorkerError,
)
from .protocol import (
    DirtyProtocol,
    make_response,
    make_error_response,
    make_chunk_message,
    make_end_message,
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
        self._executor = None

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
        # Lazy import for gevent compatibility (see #3482)
        from concurrent.futures import ThreadPoolExecutor

        # Create thread pool for executing app actions
        num_threads = self.cfg.dirty_threads
        self._executor = ThreadPoolExecutor(
            max_workers=num_threads,
            thread_name_prefix=f"dirty-worker-{self.pid}-"
        )
        self.log.debug("Created thread pool with %d threads", num_threads)

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

                # Handle the request - pass writer for streaming support
                await self.handle_request(message, writer)
        except Exception as e:
            self.log.error("Connection error: %s", e)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def handle_request(self, message, writer):
        """
        Handle a single request message.

        Supports both regular (non-streaming) and streaming responses.
        For streaming, detects if the result is a generator and sends
        chunk messages followed by an end message.

        Args:
            message: Request dict from protocol
            writer: StreamWriter for sending responses
        """
        request_id = message.get("id", str(uuid.uuid4()))
        msg_type = message.get("type")

        if msg_type != DirtyProtocol.MSG_TYPE_REQUEST:
            response = make_error_response(
                request_id,
                DirtyWorkerError(f"Unknown message type: {msg_type}")
            )
            await DirtyProtocol.write_message_async(writer, response)
            return

        app_path = message.get("app_path")
        action = message.get("action")
        args = message.get("args", [])
        kwargs = message.get("kwargs", {})

        # Update heartbeat before executing
        self.notify()

        try:
            result = await self.execute(app_path, action, args, kwargs)

            # Check if result is a generator (streaming)
            if inspect.isgenerator(result):
                await self._stream_sync_generator(request_id, result, writer)
            elif inspect.isasyncgen(result):
                await self._stream_async_generator(request_id, result, writer)
            else:
                # Regular non-streaming response
                response = make_response(request_id, result)
                await DirtyProtocol.write_message_async(writer, response)
        except Exception as e:
            tb = traceback.format_exc()
            self.log.error("Error executing %s.%s: %s\n%s",
                           app_path, action, e, tb)
            response = make_error_response(
                request_id,
                DirtyAppError(str(e), app_path=app_path, action=action,
                              traceback=tb)
            )
            await DirtyProtocol.write_message_async(writer, response)

    async def _stream_sync_generator(self, request_id, gen, writer):
        """
        Stream chunks from a synchronous generator.

        Args:
            request_id: Request ID for the messages
            gen: Sync generator to iterate
            writer: StreamWriter for sending messages
        """
        # Sentinel value to detect end of generator
        # (StopIteration cannot be raised into a Future in Python 3.7+)
        _EXHAUSTED = object()

        def _get_next():
            try:
                return next(gen)
            except StopIteration:
                return _EXHAUSTED

        try:
            loop = asyncio.get_running_loop()
            while True:
                # Run next() in executor to avoid blocking event loop
                chunk = await loop.run_in_executor(self._executor, _get_next)
                if chunk is _EXHAUSTED:
                    break
                # Send chunk message
                await DirtyProtocol.write_message_async(
                    writer, make_chunk_message(request_id, chunk)
                )
                # Update heartbeat during long streams
                self.notify()
            # Send end message
            await DirtyProtocol.write_message_async(
                writer, make_end_message(request_id)
            )
        except Exception as e:
            # Error during streaming - send error message
            tb = traceback.format_exc()
            self.log.error("Error during streaming: %s\n%s", e, tb)
            response = make_error_response(
                request_id,
                DirtyAppError(str(e), traceback=tb)
            )
            await DirtyProtocol.write_message_async(writer, response)
        finally:
            gen.close()

    async def _stream_async_generator(self, request_id, gen, writer):
        """
        Stream chunks from an asynchronous generator.

        Args:
            request_id: Request ID for the messages
            gen: Async generator to iterate
            writer: StreamWriter for sending messages
        """
        try:
            async for chunk in gen:
                # Send chunk message
                await DirtyProtocol.write_message_async(
                    writer, make_chunk_message(request_id, chunk)
                )
                # Update heartbeat during long streams
                self.notify()
            # Send end message
            await DirtyProtocol.write_message_async(
                writer, make_end_message(request_id)
            )
        except Exception as e:
            # Error during streaming - send error message
            tb = traceback.format_exc()
            self.log.error("Error during streaming: %s\n%s", e, tb)
            response = make_error_response(
                request_id,
                DirtyAppError(str(e), traceback=tb)
            )
            await DirtyProtocol.write_message_async(writer, response)
        finally:
            await gen.aclose()

    async def execute(self, app_path, action, args, kwargs):
        """
        Execute an action on a dirty app.

        The action runs in a thread pool executor to avoid blocking the
        asyncio event loop. Execution timeout is enforced using
        ``dirty_timeout`` config.

        Args:
            app_path: Import path of the dirty app
            action: Action name to execute
            args: Positional arguments
            kwargs: Keyword arguments

        Returns:
            Result from the app action

        Raises:
            DirtyAppNotFoundError: If app is not loaded
            DirtyTimeoutError: If execution exceeds timeout
            DirtyAppError: If execution fails
        """
        if app_path not in self.apps:
            raise DirtyAppNotFoundError(app_path)

        app = self.apps[app_path]
        timeout = self.cfg.dirty_timeout if self.cfg.dirty_timeout > 0 else None

        # Run the app call in the thread pool to avoid blocking
        # the event loop for CPU-bound operations
        loop = asyncio.get_running_loop()

        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    self._executor,
                    lambda: app(action, *args, **kwargs)
                ),
                timeout=timeout
            )
            return result
        except asyncio.TimeoutError:
            # Note: The thread continues running - we just stop waiting
            self.log.warning(
                "Execution timeout for %s.%s after %ds",
                app_path, action, timeout
            )
            raise DirtyTimeoutError(
                f"Execution of {app_path}.{action} timed out",
                timeout=timeout
            )

    def _cleanup(self):
        """Clean up resources on shutdown."""
        # Shutdown thread pool executor
        if self._executor:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

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
