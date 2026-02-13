#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Control Socket Server

Runs in the arbiter process and accepts commands via Unix socket.
Uses asyncio in a background thread to handle client connections.
"""

import asyncio
import os
import shlex
import threading

from gunicorn.ctl.handlers import CommandHandlers
from gunicorn.ctl.protocol import (
    ControlProtocol,
    make_response,
    make_error_response,
)


class ControlSocketServer:
    """
    Control socket server running in arbiter process.

    The server runs an asyncio event loop in a background thread,
    accepting connections and dispatching commands to handlers.
    """

    def __init__(self, arbiter, socket_path, socket_mode=0o600):
        """
        Initialize control socket server.

        Args:
            arbiter: The Gunicorn arbiter instance
            socket_path: Path for the Unix socket
            socket_mode: Permission mode for socket (default 0o600)
        """
        self.arbiter = arbiter
        self.socket_path = socket_path
        self.socket_mode = socket_mode

        self.handlers = CommandHandlers(arbiter)
        self._server = None
        self._loop = None
        self._thread = None
        self._running = False

    def start(self):
        """Start server in background thread with asyncio event loop."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop server and cleanup socket."""
        if not self._running:
            return

        self._running = False

        if self._loop and self._server:
            # Schedule server close in the loop
            self._loop.call_soon_threadsafe(self._shutdown)

        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

        # Clean up socket file
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass

    def _shutdown(self):
        """Shutdown server (called from event loop thread)."""
        if self._server:
            self._server.close()

    def _run_loop(self):
        """Run the asyncio event loop in background thread."""
        try:
            asyncio.run(self._serve())
        except Exception as e:
            if self.arbiter.log:
                self.arbiter.log.error("Control server error: %s", e)

    async def _serve(self):
        """Main async server loop."""
        self._loop = asyncio.get_running_loop()

        # Remove socket if it exists
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

        # Create Unix socket server
        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=self.socket_path
        )

        # Set socket permissions
        os.chmod(self.socket_path, self.socket_mode)

        if self.arbiter.log:
            self.arbiter.log.info("Control socket listening at %s",
                                  self.socket_path)

        try:
            async with self._server:
                await self._server.serve_forever()
        except asyncio.CancelledError:
            pass
        finally:
            if os.path.exists(self.socket_path):
                try:
                    os.unlink(self.socket_path)
                except OSError:
                    pass

    async def _handle_client(self, reader, writer):
        """
        Handle client connection.

        Args:
            reader: asyncio StreamReader
            writer: asyncio StreamWriter
        """
        try:
            while self._running:
                try:
                    message = await asyncio.wait_for(
                        ControlProtocol.read_message_async(reader),
                        timeout=300.0  # 5 minute idle timeout
                    )
                except asyncio.TimeoutError:
                    # Client idle too long, close connection
                    break
                except asyncio.IncompleteReadError:
                    # Client disconnected
                    break
                except Exception:
                    # Protocol error
                    break

                # Process command
                response = await self._dispatch(message)

                # Send response
                await ControlProtocol.write_message_async(writer, response)

        except Exception as e:
            if self.arbiter.log:
                self.arbiter.log.debug("Control client error: %s", e)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _dispatch(self, message: dict) -> dict:
        """
        Dispatch command to appropriate handler.

        Args:
            message: Request message dict

        Returns:
            Response dictionary
        """
        request_id = message.get("id", 0)
        command = message.get("command", "").strip()
        args = message.get("args", [])

        if not command:
            return make_error_response(request_id, "Empty command")

        try:
            # Parse command (e.g., "show workers" or "worker add 2")
            parts = shlex.split(command)
            if args:
                parts.extend(str(a) for a in args)

            if not parts:
                return make_error_response(request_id, "Empty command")

            # Route to handler
            result = self._execute_command(parts)
            return make_response(request_id, result)

        except ValueError as e:
            return make_error_response(request_id, f"Invalid argument: {e}")
        except Exception as e:
            if self.arbiter.log:
                self.arbiter.log.exception("Command error")
            return make_error_response(request_id, f"Command failed: {e}")

    def _execute_command(self, parts: list) -> dict:  # pylint: disable=too-many-return-statements
        """
        Execute a parsed command.

        Args:
            parts: Command parts (e.g., ["show", "workers"])

        Returns:
            Handler result dictionary
        """
        if not parts:
            raise ValueError("Empty command")

        cmd = parts[0].lower()
        rest = parts[1:]

        # Map commands to handlers
        if cmd == "show":
            return self._handle_show(rest)
        elif cmd == "worker":
            return self._handle_worker(rest)
        elif cmd == "dirty":
            return self._handle_dirty(rest)
        elif cmd == "reload":
            return self.handlers.reload()
        elif cmd == "reopen":
            return self.handlers.reopen()
        elif cmd == "shutdown":
            mode = rest[0] if rest else "graceful"
            return self.handlers.shutdown(mode)
        elif cmd == "help":
            return self.handlers.help()
        else:
            raise ValueError(f"Unknown command: {cmd}")

    def _handle_show(self, args: list) -> dict:
        """Handle 'show' commands."""
        if not args:
            raise ValueError("Missing show target (all|workers|dirty|config|stats|listeners)")

        target = args[0].lower()

        if target == "all":
            return self.handlers.show_all()
        elif target == "workers":
            return self.handlers.show_workers()
        elif target == "dirty":
            return self.handlers.show_dirty()
        elif target == "config":
            return self.handlers.show_config()
        elif target == "stats":
            return self.handlers.show_stats()
        elif target == "listeners":
            return self.handlers.show_listeners()
        else:
            raise ValueError(f"Unknown show target: {target}")

    def _handle_worker(self, args: list) -> dict:
        """Handle 'worker' commands."""
        if not args:
            raise ValueError("Missing worker action (add|remove|kill)")

        action = args[0].lower()
        action_args = args[1:]

        if action == "add":
            count = int(action_args[0]) if action_args else 1
            return self.handlers.worker_add(count)
        elif action == "remove":
            count = int(action_args[0]) if action_args else 1
            return self.handlers.worker_remove(count)
        elif action == "kill":
            if not action_args:
                raise ValueError("Missing PID for worker kill")
            pid = int(action_args[0])
            return self.handlers.worker_kill(pid)
        else:
            raise ValueError(f"Unknown worker action: {action}")

    def _handle_dirty(self, args: list) -> dict:
        """Handle 'dirty' commands."""
        if not args:
            raise ValueError("Missing dirty action (add|remove)")

        action = args[0].lower()
        action_args = args[1:]

        if action == "add":
            count = int(action_args[0]) if action_args else 1
            return self.handlers.dirty_add(count)
        elif action == "remove":
            count = int(action_args[0]) if action_args else 1
            return self.handlers.dirty_remove(count)
        else:
            raise ValueError(f"Unknown dirty action: {action}")
