#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for dirty client module."""

import asyncio
import os
import socket
import tempfile
import threading
import pytest

from gunicorn.dirty.client import (
    DirtyClient,
    get_dirty_client,
    get_dirty_socket_path,
    set_dirty_socket_path,
    close_dirty_client,
    _thread_local,
)
from gunicorn.dirty.errors import DirtyConnectionError, DirtyError
from gunicorn.dirty.protocol import DirtyProtocol, make_response


class TestDirtyClientInit:
    """Tests for DirtyClient initialization."""

    def test_init_attributes(self):
        """Test that client is initialized with correct attributes."""
        client = DirtyClient("/tmp/test.sock", timeout=60.0)

        assert client.socket_path == "/tmp/test.sock"
        assert client.timeout == 60.0
        assert client._sock is None
        assert client._reader is None
        assert client._writer is None


class TestDirtyClientSync:
    """Tests for sync API."""

    def test_connect_nonexistent_socket(self):
        """Test connecting to non-existent socket."""
        client = DirtyClient("/nonexistent/socket.sock")

        with pytest.raises(DirtyConnectionError) as exc_info:
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
                client = DirtyClient(socket_path)
                client.connect()

                assert client._sock is not None
                client.close()
            finally:
                server_sock.close()

    def test_close_idempotent(self):
        """Test that close can be called multiple times."""
        client = DirtyClient("/tmp/test.sock")
        client.close()
        client.close()  # Should not raise


class TestDirtyClientAsync:
    """Tests for async API."""

    @pytest.mark.asyncio
    async def test_connect_async_nonexistent_socket(self):
        """Test async connecting to non-existent socket."""
        client = DirtyClient("/nonexistent/socket.sock", timeout=1.0)

        with pytest.raises(DirtyConnectionError):
            await client.connect_async()

    @pytest.mark.asyncio
    async def test_close_async_idempotent(self):
        """Test that close_async can be called multiple times."""
        client = DirtyClient("/tmp/test.sock")
        await client.close_async()
        await client.close_async()  # Should not raise


class TestDirtyClientContextManagers:
    """Tests for context manager functionality."""

    def test_sync_context_manager_connection_error(self):
        """Test sync context manager with connection error."""
        client = DirtyClient("/nonexistent/socket.sock")

        with pytest.raises(DirtyConnectionError):
            with client:
                pass

    @pytest.mark.asyncio
    async def test_async_context_manager_connection_error(self):
        """Test async context manager with connection error."""
        client = DirtyClient("/nonexistent/socket.sock", timeout=1.0)

        with pytest.raises(DirtyConnectionError):
            async with client:
                pass


class TestDirtyClientHelpers:
    """Tests for helper functions."""

    def test_set_get_socket_path(self):
        """Test setting and getting socket path."""
        original = os.environ.get('GUNICORN_DIRTY_SOCKET')

        try:
            set_dirty_socket_path("/tmp/dirty.sock")
            assert get_dirty_socket_path() == "/tmp/dirty.sock"
        finally:
            set_dirty_socket_path(None)
            if original:
                os.environ['GUNICORN_DIRTY_SOCKET'] = original

    def test_get_socket_path_from_env(self):
        """Test getting socket path from environment."""
        original = os.environ.get('GUNICORN_DIRTY_SOCKET')

        try:
            set_dirty_socket_path(None)
            os.environ['GUNICORN_DIRTY_SOCKET'] = "/env/dirty.sock"
            assert get_dirty_socket_path() == "/env/dirty.sock"
        finally:
            set_dirty_socket_path(None)
            if original:
                os.environ['GUNICORN_DIRTY_SOCKET'] = original
            else:
                os.environ.pop('GUNICORN_DIRTY_SOCKET', None)

    def test_get_socket_path_not_configured(self):
        """Test error when socket path not configured."""
        original = os.environ.get('GUNICORN_DIRTY_SOCKET')

        try:
            set_dirty_socket_path(None)
            os.environ.pop('GUNICORN_DIRTY_SOCKET', None)

            with pytest.raises(DirtyError) as exc_info:
                get_dirty_socket_path()
            assert "not configured" in str(exc_info.value)
        finally:
            if original:
                os.environ['GUNICORN_DIRTY_SOCKET'] = original

    def test_get_dirty_client_thread_local(self):
        """Test that get_dirty_client returns thread-local client."""
        original = os.environ.get('GUNICORN_DIRTY_SOCKET')

        try:
            set_dirty_socket_path("/tmp/test.sock")

            # Clean up any existing client
            close_dirty_client()

            client1 = get_dirty_client()
            client2 = get_dirty_client()

            # Should return same instance in same thread
            assert client1 is client2

            close_dirty_client()
        finally:
            set_dirty_socket_path(None)
            if original:
                os.environ['GUNICORN_DIRTY_SOCKET'] = original

    def test_get_dirty_client_different_threads(self):
        """Test that different threads get different clients."""
        original = os.environ.get('GUNICORN_DIRTY_SOCKET')
        clients = []

        try:
            set_dirty_socket_path("/tmp/test.sock")

            def get_client():
                clients.append(get_dirty_client())
                close_dirty_client()

            # Clean up main thread client
            close_dirty_client()

            t1 = threading.Thread(target=get_client)
            t2 = threading.Thread(target=get_client)

            t1.start()
            t2.start()
            t1.join()
            t2.join()

            # Different threads should get different clients
            assert len(clients) == 2
            assert clients[0] is not clients[1]
        finally:
            set_dirty_socket_path(None)
            if original:
                os.environ['GUNICORN_DIRTY_SOCKET'] = original

    def test_close_dirty_client(self):
        """Test closing thread-local client."""
        original = os.environ.get('GUNICORN_DIRTY_SOCKET')

        try:
            set_dirty_socket_path("/tmp/test.sock")

            client = get_dirty_client()
            close_dirty_client()

            # Should be able to get a new client
            client2 = get_dirty_client()
            assert client2 is not client

            close_dirty_client()
        finally:
            set_dirty_socket_path(None)
            if original:
                os.environ['GUNICORN_DIRTY_SOCKET'] = original


class TestDirtyClientResponseHandling:
    """Tests for response handling."""

    def test_handle_response_success(self):
        """Test handling successful response."""
        client = DirtyClient("/tmp/test.sock")
        response = make_response("test-id", {"data": "value"})

        result = client._handle_response(response)
        assert result == {"data": "value"}

    def test_handle_response_error(self):
        """Test handling error response."""
        client = DirtyClient("/tmp/test.sock")
        response = {
            "type": DirtyProtocol.MSG_TYPE_ERROR,
            "id": "test-id",
            "error": {
                "error_type": "DirtyError",
                "message": "Test error",
                "details": {},
            },
        }

        with pytest.raises(DirtyError) as exc_info:
            client._handle_response(response)
        assert "Test error" in str(exc_info.value)

    def test_handle_response_unknown_type(self):
        """Test handling unknown response type."""
        client = DirtyClient("/tmp/test.sock")
        response = {
            "type": "unknown",
            "id": "test-id",
        }

        with pytest.raises(DirtyError) as exc_info:
            client._handle_response(response)
        assert "Unknown response type" in str(exc_info.value)


class TestDirtyClientExecute:
    """Tests for execute functionality with mock sockets."""

    def test_execute_with_socket_pair(self):
        """Test execute using a socket pair to simulate server."""
        import threading

        with tempfile.TemporaryDirectory() as tmpdir:
            socket_path = os.path.join(tmpdir, "test.sock")

            # Create server socket
            server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server_sock.bind(socket_path)
            server_sock.listen(1)

            response_sent = threading.Event()

            def server_handler():
                conn, _ = server_sock.accept()
                try:
                    # Read request
                    msg = DirtyProtocol.read_message(conn)
                    # Send response
                    resp = make_response(msg["id"], {"result": "success"})
                    DirtyProtocol.write_message(conn, resp)
                    response_sent.set()
                finally:
                    conn.close()

            server_thread = threading.Thread(target=server_handler)
            server_thread.start()

            try:
                client = DirtyClient(socket_path, timeout=5.0)
                result = client.execute("test:App", "action", "arg1", key="value")
                assert result == {"result": "success"}
                client.close()
            finally:
                response_sent.wait(timeout=2.0)
                server_thread.join(timeout=2.0)
                server_sock.close()

    def test_close_socket_clears_sock(self):
        """Test that _close_socket clears the socket."""
        client = DirtyClient("/tmp/test.sock")
        # Simulate having a socket
        client._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client._close_socket()
        assert client._sock is None
