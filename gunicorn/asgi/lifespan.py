#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
ASGI lifespan protocol manager.

Manages startup and shutdown events for ASGI applications,
enabling frameworks like FastAPI to run initialization and
cleanup code.
"""

import asyncio


class LifespanManager:
    """Manages ASGI lifespan events (startup/shutdown).

    The lifespan protocol allows ASGI applications to run code at
    startup and shutdown. This is essential for applications that
    need to initialize database connections, caches, or other
    resources.

    ASGI lifespan messages:
    - Server sends: {"type": "lifespan.startup"}
    - App responds: {"type": "lifespan.startup.complete"} or
                    {"type": "lifespan.startup.failed", "message": "..."}
    - Server sends: {"type": "lifespan.shutdown"}
    - App responds: {"type": "lifespan.shutdown.complete"}
    """

    def __init__(self, app, logger, state=None):
        """Initialize the lifespan manager.

        Args:
            app: ASGI application callable
            logger: Logger instance
            state: Shared state dict for the application
        """
        self.app = app
        self.logger = logger
        self.state = state if state is not None else {}

        self._startup_complete = asyncio.Event()
        self._shutdown_complete = asyncio.Event()
        self._startup_failed = False
        self._startup_error = None
        self._shutdown_error = None
        self._receive_queue = asyncio.Queue()
        self._task = None
        self._app_finished = False

    async def startup(self):
        """Run lifespan startup and wait for completion.

        Raises:
            RuntimeError: If startup fails or app doesn't support lifespan
        """
        scope = {
            "type": "lifespan",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "state": self.state,
        }

        # Send startup event
        await self._receive_queue.put({"type": "lifespan.startup"})

        # Run lifespan in background task
        self._task = asyncio.create_task(self._run_lifespan(scope))

        # Wait for startup with timeout
        try:
            await asyncio.wait_for(
                self._startup_complete.wait(),
                timeout=30.0  # Reasonable startup timeout
            )
        except asyncio.TimeoutError:
            if self._task:
                self._task.cancel()
            raise RuntimeError("Lifespan startup timed out")

        if self._startup_failed:
            if self._task:
                self._task.cancel()
            msg = self._startup_error or "Unknown error"
            raise RuntimeError(f"Lifespan startup failed: {msg}")

        self.logger.debug("ASGI lifespan startup complete")

    async def shutdown(self):
        """Signal shutdown and wait for completion.

        This should be called during graceful shutdown.
        """
        if self._app_finished:
            self.logger.debug("ASGI lifespan already finished")
            return

        # Send shutdown event
        await self._receive_queue.put({"type": "lifespan.shutdown"})

        # Wait for shutdown with timeout
        try:
            await asyncio.wait_for(
                self._shutdown_complete.wait(),
                timeout=30.0  # Reasonable shutdown timeout
            )
        except asyncio.TimeoutError:
            self.logger.warning("Lifespan shutdown timed out")

        if self._shutdown_error:
            self.logger.error("Lifespan shutdown error: %s", self._shutdown_error)

        # Cancel the task if still running
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self.logger.debug("ASGI lifespan shutdown complete")

    async def _run_lifespan(self, scope):
        """Run the ASGI lifespan protocol."""
        try:
            await self.app(scope, self._receive, self._send)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.logger.debug("Lifespan application raised: %s", e)
            # If startup hasn't completed, mark it as failed
            if not self._startup_complete.is_set():
                self._startup_failed = True
                self._startup_error = str(e)
                self._startup_complete.set()
            # If shutdown hasn't completed, mark error
            elif not self._shutdown_complete.is_set():
                self._shutdown_error = str(e)
                self._shutdown_complete.set()
        finally:
            self._app_finished = True
            # Ensure events are set to unblock waiters
            if not self._startup_complete.is_set():
                self._startup_failed = True
                self._startup_error = "Application exited before startup complete"
                self._startup_complete.set()
            if not self._shutdown_complete.is_set():
                self._shutdown_complete.set()

    async def _receive(self):
        """ASGI receive callable for lifespan."""
        return await self._receive_queue.get()

    async def _send(self, message):
        """ASGI send callable for lifespan."""
        msg_type = message["type"]

        if msg_type == "lifespan.startup.complete":
            self._startup_complete.set()
            self.logger.debug("Received lifespan.startup.complete")

        elif msg_type == "lifespan.startup.failed":
            self._startup_failed = True
            self._startup_error = message.get("message", "")
            self._startup_complete.set()
            self.logger.debug("Received lifespan.startup.failed: %s",
                              self._startup_error)

        elif msg_type == "lifespan.shutdown.complete":
            self._shutdown_complete.set()
            self.logger.debug("Received lifespan.shutdown.complete")

        elif msg_type == "lifespan.shutdown.failed":
            self._shutdown_error = message.get("message", "")
            self._shutdown_complete.set()
            self.logger.debug("Received lifespan.shutdown.failed: %s",
                              self._shutdown_error)
