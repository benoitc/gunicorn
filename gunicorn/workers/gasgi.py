#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
ASGI worker for gunicorn.

Provides native asyncio-based ASGI support using gunicorn's own
HTTP parsing infrastructure.
"""

import asyncio
import os
import signal
import sys

from gunicorn.workers import base
from gunicorn.asgi.protocol import ASGIProtocol


class ASGIWorker(base.Worker):
    """ASGI worker using asyncio event loop.

    Supports:
    - HTTP/1.1 with keepalive
    - WebSocket connections
    - Lifespan protocol (startup/shutdown hooks)
    - Optional uvloop for improved performance
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.worker_connections = self.cfg.worker_connections
        self.loop = None
        self.servers = []
        self.nr_conns = 0
        self.lifespan = None
        self.state = {}  # Shared state for lifespan
        self._quick_shutdown = False  # True for SIGINT/SIGQUIT (immediate), False for SIGTERM (graceful)
        self._accepting = True  # Whether we're currently accepting new connections

    @classmethod
    def check_config(cls, cfg, log):
        """Validate configuration for ASGI worker."""
        if cfg.threads > 1:
            log.warning("ASGI worker does not use threads configuration. "
                        "Use worker_connections instead.")

    def init_process(self):
        """Initialize the worker process."""
        # Setup event loop before calling super()
        self._setup_event_loop()
        super().init_process()

    def _setup_event_loop(self):
        """Setup the asyncio event loop."""
        loop_type = getattr(self.cfg, 'asgi_loop', 'auto')

        if loop_type == "auto":
            try:
                import uvloop
                loop_type = "uvloop"
            except ImportError:
                loop_type = "asyncio"

        if loop_type == "uvloop":
            try:
                import uvloop
                self.loop = uvloop.new_event_loop()
                self.log.debug("Using uvloop event loop")
            except ImportError:
                self.log.warning("uvloop not available, falling back to asyncio")
                self.loop = asyncio.new_event_loop()
        else:
            self.loop = asyncio.new_event_loop()
            self.log.debug("Using asyncio event loop")

        asyncio.set_event_loop(self.loop)

    def load_wsgi(self):
        """Load the ASGI application."""
        try:
            self.asgi = self.app.wsgi()
        except SyntaxError as e:
            if not self.cfg.reload:
                raise
            self.log.exception(e)
            self.asgi = self._make_error_app(str(e))

    def _make_error_app(self, error_msg):
        """Create an error ASGI app for syntax errors during reload."""
        async def error_app(scope, receive, send):
            if scope["type"] == "http":
                await send({
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [(b"content-type", b"text/plain")],
                })
                await send({
                    "type": "http.response.body",
                    "body": f"Application error: {error_msg}".encode(),
                })
            elif scope["type"] == "lifespan":
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                message = await receive()
                if message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
        return error_app

    def init_signals(self):
        """Initialize signal handlers for asyncio."""
        # Reset all signals first
        for s in self.SIGNALS:
            signal.signal(s, signal.SIG_DFL)

        # Set up signal handlers via the event loop
        self.loop.add_signal_handler(signal.SIGQUIT, self.handle_quit_signal)
        self.loop.add_signal_handler(signal.SIGTERM, self.handle_exit_signal)
        self.loop.add_signal_handler(signal.SIGINT, self.handle_quit_signal)
        self.loop.add_signal_handler(signal.SIGUSR1, self.handle_usr1_signal)
        self.loop.add_signal_handler(signal.SIGWINCH, self.handle_winch_signal)
        self.loop.add_signal_handler(signal.SIGABRT, self.handle_abort_signal)

    def handle_quit_signal(self):
        """Handle SIGQUIT/SIGINT - immediate shutdown."""
        self._quick_shutdown = True
        if not self.alive:
            # Already shutting down (SIGTERM was sent) - wake up the loop
            return
        self.alive = False
        self.cfg.worker_int(self)

    def handle_exit_signal(self):
        """Handle SIGTERM - graceful shutdown."""
        self.alive = False

    def handle_usr1_signal(self):
        """Handle SIGUSR1 - reopen log files."""
        self.log.reopen_files()

    def handle_winch_signal(self):
        """Handle SIGWINCH - ignored in worker."""
        self.log.debug("worker: SIGWINCH ignored.")

    def handle_abort_signal(self):
        """Handle SIGABRT - abort."""
        self.alive = False
        self.cfg.worker_abort(self)
        sys.exit(1)

    def run(self):
        """Main entry point for the worker."""
        try:
            self.loop.run_until_complete(self._serve())
        except Exception as e:
            self.log.exception("Worker exception: %s", e)
        finally:
            self._cleanup()

    async def _serve(self):
        """Main async serving loop."""
        # Run lifespan startup
        lifespan_mode = getattr(self.cfg, 'asgi_lifespan', 'auto')
        if lifespan_mode != "off":
            from gunicorn.asgi.lifespan import LifespanManager
            self.lifespan = LifespanManager(self.asgi, self.log, self.state)
            try:
                await self.lifespan.startup()
            except Exception as e:
                if lifespan_mode == "on":
                    self.log.error("ASGI lifespan startup failed: %s", e)
                    return
                else:
                    # auto mode - app doesn't support lifespan
                    self.log.debug("ASGI lifespan not supported by app: %s", e)
                    self.lifespan = None

        # Create servers for each listener socket
        ssl_context = self._get_ssl_context()
        self._ssl_context = ssl_context

        for sock in self.sockets:
            try:
                server = await self.loop.create_server(
                    lambda: ASGIProtocol(self),
                    sock=sock.sock,
                    ssl=ssl_context,
                    reuse_address=True,
                    start_serving=True,
                )
                self.servers.append(server)
                self.log.info("ASGI server listening on %s", sock)
            except Exception as e:
                self.log.error("Failed to create server on %s: %s", sock, e)

        if not self.servers:
            self.log.error("No servers could be started")
            return

        # Main loop with heartbeat
        try:
            while self.alive:
                self.notify()

                # Check if parent is still alive
                if self.ppid != os.getppid():
                    self.log.info("Parent changed, shutting down: %s", self)
                    break

                # Enforce connection limit at OS level:
                # - At capacity: remove socket FDs from event loop so kernel
                #   won't deliver new connections to this worker
                # - Below capacity: re-register socket FDs so this worker
                #   can accept again
                at_capacity = self.nr_conns >= self.worker_connections
                if at_capacity and self._accepting:
                    self._pause_accepting()
                elif not at_capacity and not self._accepting:
                    self._resume_accepting()

                await asyncio.sleep(0.25)

        except asyncio.CancelledError:
            pass

        # Graceful shutdown
        await self._shutdown()

    def _pause_accepting(self):
        """Stop accepting new connections at the OS level.

        Removes socket file descriptors from the event loop's reader set.
        The kernel will not deliver new connections to this worker while
        paused, routing them to other workers that are still accepting.
        The sockets remain open so they can be re-registered later.
        """
        for server in self.servers:
            # Use _sockets (raw sockets), not .sockets (TransportSocket wrappers)
            raw_sockets = getattr(server, '_sockets', None) or []
            for sock in raw_sockets:
                self.loop.remove_reader(sock.fileno())
        self._accepting = False
        self.log.debug(
            "Connection limit reached (%d/%d), paused accepting",
            self.nr_conns, self.worker_connections
        )

    def _resume_accepting(self):
        """Resume accepting connections at the OS level.

        Re-registers socket file descriptors with the event loop so the
        kernel can deliver new connections to this worker again.
        Uses server._sockets (raw sockets) because _start_serving needs
        the actual socket object with .accept() method.
        """
        for server in self.servers:
            raw_sockets = getattr(server, '_sockets', None) or []
            for sock in raw_sockets:
                self.loop._start_serving(
                    lambda: ASGIProtocol(self),
                    sock,
                    self._ssl_context,
                    server,
                    self.cfg.backlog,
                )
        self._accepting = True
        self.log.debug(
            "Connections available (%d/%d), resumed accepting",
            self.nr_conns, self.worker_connections
        )

    async def _shutdown(self):
        """Perform graceful shutdown."""
        self.log.info("Worker shutting down...")

        # Stop accepting new connections
        for server in self.servers:
            server.close()

        # Wait for servers to close (skip on quick shutdown)
        if not self._quick_shutdown:
            for server in self.servers:
                if self._quick_shutdown:
                    break
                try:
                    await asyncio.wait_for(server.wait_closed(), timeout=0.5)
                except asyncio.TimeoutError:
                    pass  # Check _quick_shutdown on next iteration

        # Wait for in-flight connections (skip on quick shutdown)
        if self.nr_conns > 0 and not self._quick_shutdown:
            graceful_timeout = self.cfg.graceful_timeout
            self.log.info("Waiting for %d connections to finish...", self.nr_conns)
            deadline = self.loop.time() + graceful_timeout
            while self.nr_conns > 0 and self.loop.time() < deadline:
                if self._quick_shutdown:
                    self.log.info("Quick shutdown requested")
                    break
                await asyncio.sleep(0.1)

            if self.nr_conns > 0:
                self.log.warning("Forcing close of %d connections", self.nr_conns)

        # Run lifespan shutdown (skip on quick shutdown)
        if self.lifespan and not self._quick_shutdown:
            try:
                await self.lifespan.shutdown()
            except Exception as e:
                self.log.error("ASGI lifespan shutdown error: %s", e)

    def _get_ssl_context(self):
        """Get SSL context if configured."""
        if not self.cfg.is_ssl:
            return None

        try:
            from gunicorn import sock
            return sock.ssl_context(self.cfg)
        except Exception as e:
            self.log.error("Failed to create SSL context: %s", e)
            return None

    def _cleanup(self):
        """Clean up resources on exit."""
        try:
            # Cancel all pending tasks
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()

            # Run loop until all tasks are cancelled (with timeout on quick exit)
            if pending:
                gather = asyncio.gather(*pending, return_exceptions=True)
                if self._quick_shutdown:
                    # Quick exit - don't wait long for tasks to cancel
                    try:
                        self.loop.run_until_complete(
                            asyncio.wait_for(gather, timeout=1.0)
                        )
                    except asyncio.TimeoutError:
                        self.log.debug("Timeout waiting for tasks to cancel")
                else:
                    self.loop.run_until_complete(gather)

            self.loop.close()
        except Exception as e:
            self.log.debug("Cleanup error: %s", e)

        # Close sockets
        for s in self.sockets:
            try:
                s.close()
            except Exception:
                pass
