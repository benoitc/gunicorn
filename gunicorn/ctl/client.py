#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Control Socket Client

Client library for connecting to gunicorn control socket.
"""

import shlex
import socket

from gunicorn.ctl.protocol import (
    ControlProtocol,
    make_request,
)


class ControlClientError(Exception):
    """Control client error."""


class ControlClient:
    """
    Client for connecting to gunicorn control socket.

    Can be used as a context manager:

        with ControlClient('/path/to/gunicorn.ctl') as client:
            result = client.send_command('show workers')
    """

    def __init__(self, socket_path: str, timeout: float = 30.0):
        """
        Initialize control client.

        Args:
            socket_path: Path to the Unix socket
            timeout: Socket timeout in seconds (default 30)
        """
        self.socket_path = socket_path
        self.timeout = timeout
        self._sock = None
        self._request_id = 0

    def connect(self):
        """
        Connect to control socket.

        Raises:
            ControlClientError: If connection fails
        """
        if self._sock:
            return

        try:
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._sock.settimeout(self.timeout)
            self._sock.connect(self.socket_path)
        except socket.error as e:
            self._sock = None
            raise ControlClientError(f"Failed to connect to {self.socket_path}: {e}")

    def close(self):
        """Close connection."""
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def send_command(self, command: str, args: list = None) -> dict:
        """
        Send command and wait for response.

        Args:
            command: Command string (e.g., "show workers")
            args: Optional additional arguments

        Returns:
            Response data dictionary

        Raises:
            ControlClientError: If communication fails
        """
        if not self._sock:
            self.connect()

        self._request_id += 1
        request = make_request(self._request_id, command, args)

        try:
            ControlProtocol.write_message(self._sock, request)
            response = ControlProtocol.read_message(self._sock)
        except Exception as e:
            self.close()
            raise ControlClientError(f"Communication error: {e}")

        if response.get("status") == "error":
            raise ControlClientError(response.get("error", "Unknown error"))

        return response.get("data", {})

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()


def parse_command(line: str) -> tuple:
    """
    Parse a command line into command and args.

    Args:
        line: Command line string

    Returns:
        Tuple of (command_string, args_list)
    """
    parts = shlex.split(line)
    if not parts:
        return "", []

    # Find where numeric/value args start
    command_parts = []
    args = []

    for part in parts:
        # If we haven't hit args yet and this looks like a command word
        if not args and not part.isdigit() and not part.startswith('-'):
            command_parts.append(part)
        else:
            args.append(part)

    return " ".join(command_parts), args
