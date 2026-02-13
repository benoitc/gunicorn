#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for control socket client."""

import os
import socket
import tempfile
import threading

import pytest

from gunicorn.ctl.client import (
    ControlClient,
    ControlClientError,
    parse_command,
)
from gunicorn.ctl.protocol import ControlProtocol, make_response


class TestControlClientInit:
    """Tests for ControlClient initialization."""

    def test_init_attributes(self):
        """Test that client is initialized with correct attributes."""
        client = ControlClient("/tmp/test.sock", timeout=60.0)

        assert client.socket_path == "/tmp/test.sock"
        assert client.timeout == 60.0
        assert client._sock is None
        assert client._request_id == 0


class TestControlClientConnect:
    """Tests for ControlClient connection."""

    def test_connect_nonexistent_socket(self):
        """Test connecting to non-existent socket."""
        client = ControlClient("/nonexistent/socket.sock")

        with pytest.raises(ControlClientError) as exc_info:
            client.connect()

        assert "Failed to connect" in str(exc_info.value)

    def test_connect_success(self):
        """Test successful connection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "test.sock")

            # Create a listening socket
            server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server_sock.bind(socket_path)
            server_sock.listen(1)

            try:
                client = ControlClient(socket_path)
                client.connect()

                assert client._sock is not None
                client.close()
            finally:
                server_sock.close()

    def test_connect_already_connected(self):
        """Test that connect is idempotent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "test.sock")

            server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server_sock.bind(socket_path)
            server_sock.listen(1)

            try:
                client = ControlClient(socket_path)
                client.connect()
                first_sock = client._sock
                client.connect()  # Should not create new connection

                assert client._sock is first_sock
                client.close()
            finally:
                server_sock.close()


class TestControlClientClose:
    """Tests for ControlClient close."""

    def test_close_idempotent(self):
        """Test that close can be called multiple times."""
        client = ControlClient("/tmp/test.sock")
        client.close()
        client.close()  # Should not raise

    def test_close_clears_socket(self):
        """Test that close clears the socket."""
        client = ControlClient("/tmp/test.sock")
        client._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.close()

        assert client._sock is None


class TestControlClientContextManager:
    """Tests for context manager functionality."""

    def test_context_manager_connection_error(self):
        """Test context manager with connection error."""
        client = ControlClient("/nonexistent/socket.sock")

        with pytest.raises(ControlClientError):
            with client:
                pass

    def test_context_manager_success(self):
        """Test successful context manager usage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "test.sock")

            server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server_sock.bind(socket_path)
            server_sock.listen(1)

            try:
                with ControlClient(socket_path) as client:
                    assert client._sock is not None

                # After context manager exits, socket should be closed
                assert client._sock is None
            finally:
                server_sock.close()


class TestControlClientSendCommand:
    """Tests for send_command functionality."""

    def test_send_command_success(self):
        """Test successful command send."""
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "test.sock")

            server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server_sock.bind(socket_path)
            server_sock.listen(1)

            response_data = {"workers": [], "count": 0}
            response_sent = threading.Event()

            def server_handler():
                conn, _ = server_sock.accept()
                try:
                    msg = ControlProtocol.read_message(conn)
                    resp = make_response(msg["id"], response_data)
                    ControlProtocol.write_message(conn, resp)
                    response_sent.set()
                finally:
                    conn.close()

            server_thread = threading.Thread(target=server_handler)
            server_thread.start()

            try:
                client = ControlClient(socket_path, timeout=5.0)
                result = client.send_command("show workers")

                assert result == response_data
                client.close()
            finally:
                response_sent.wait(timeout=2.0)
                server_thread.join(timeout=2.0)
                server_sock.close()

    def test_send_command_error_response(self):
        """Test handling error response."""
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "test.sock")

            server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server_sock.bind(socket_path)
            server_sock.listen(1)

            def server_handler():
                conn, _ = server_sock.accept()
                try:
                    msg = ControlProtocol.read_message(conn)
                    resp = {
                        "id": msg["id"],
                        "status": "error",
                        "error": "Unknown command",
                    }
                    ControlProtocol.write_message(conn, resp)
                finally:
                    conn.close()

            server_thread = threading.Thread(target=server_handler)
            server_thread.start()

            try:
                client = ControlClient(socket_path, timeout=5.0)

                with pytest.raises(ControlClientError) as exc_info:
                    client.send_command("invalid command")

                assert "Unknown command" in str(exc_info.value)
                client.close()
            finally:
                server_thread.join(timeout=2.0)
                server_sock.close()

    def test_send_command_auto_connect(self):
        """Test that send_command auto-connects if not connected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "test.sock")

            server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server_sock.bind(socket_path)
            server_sock.listen(1)

            def server_handler():
                conn, _ = server_sock.accept()
                try:
                    msg = ControlProtocol.read_message(conn)
                    resp = make_response(msg["id"], {})
                    ControlProtocol.write_message(conn, resp)
                finally:
                    conn.close()

            server_thread = threading.Thread(target=server_handler)
            server_thread.start()

            try:
                client = ControlClient(socket_path, timeout=5.0)
                # Don't call connect() explicitly
                result = client.send_command("help")

                assert isinstance(result, dict)
                client.close()
            finally:
                server_thread.join(timeout=2.0)
                server_sock.close()


class TestParseCommand:
    """Tests for command parsing."""

    def test_parse_simple_command(self):
        """Test parsing simple command."""
        cmd, args = parse_command("show workers")
        assert cmd == "show workers"
        assert args == []

    def test_parse_command_with_args(self):
        """Test parsing command with arguments."""
        cmd, args = parse_command("worker add 2")
        assert cmd == "worker add"
        assert args == ["2"]

    def test_parse_command_with_multiple_args(self):
        """Test parsing command with multiple arguments."""
        cmd, args = parse_command("worker kill 12345")
        assert cmd == "worker kill"
        assert args == ["12345"]

    def test_parse_empty_command(self):
        """Test parsing empty command."""
        cmd, args = parse_command("")
        assert cmd == ""
        assert args == []

    def test_parse_command_quoted(self):
        """Test parsing command with quoted arguments."""
        cmd, args = parse_command('worker kill "12345"')
        assert cmd == "worker kill"
        assert args == ["12345"]
