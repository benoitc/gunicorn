#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Dirty Client

Client for HTTP workers to communicate with the dirty worker pool.
Provides both sync and async APIs.
"""

import asyncio
import contextvars
import os
import socket
import threading
import uuid

from .errors import (
    DirtyConnectionError,
    DirtyError,
    DirtyTimeoutError,
)
from .protocol import (
    DirtyProtocol,
    make_request,
)


class DirtyClient:
    """
    Client for calling dirty workers from HTTP workers.

    Provides both sync and async APIs. The sync API is for traditional
    sync workers (sync, gthread), while the async API is for async
    workers (asgi, gevent, eventlet).
    """

    def __init__(self, socket_path, timeout=30.0):
        """
        Initialize the dirty client.

        Args:
            socket_path: Path to the dirty arbiter's Unix socket
            timeout: Default timeout for operations in seconds
        """
        self.socket_path = socket_path
        self.timeout = timeout
        self._sock = None
        self._reader = None
        self._writer = None
        self._lock = threading.Lock()

    # -------------------------------------------------------------------------
    # Sync API (for sync HTTP workers)
    # -------------------------------------------------------------------------

    def connect(self):
        """
        Establish sync socket connection to arbiter.

        Raises:
            DirtyConnectionError: If connection fails
        """
        if self._sock is not None:
            return

        try:
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._sock.settimeout(self.timeout)
            self._sock.connect(self.socket_path)
        except (socket.error, OSError) as e:
            self._sock = None
            raise DirtyConnectionError(
                f"Failed to connect to dirty arbiter: {e}",
                socket_path=self.socket_path
            ) from e

    def execute(self, app_path, action, *args, **kwargs):
        """
        Execute an action on a dirty app (sync/blocking).

        Args:
            app_path: Import path of the dirty app (e.g., 'myapp.ml:MLApp')
            action: Action to call on the app
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Result from the dirty app action

        Raises:
            DirtyConnectionError: If connection fails
            DirtyTimeoutError: If operation times out
            DirtyError: If execution fails
        """
        with self._lock:
            return self._execute_locked(app_path, action, args, kwargs)

    def _execute_locked(self, app_path, action, args, kwargs):
        """Execute while holding the lock."""
        # Ensure connected
        if self._sock is None:
            self.connect()

        # Build request
        request_id = str(uuid.uuid4())
        request = make_request(
            request_id=request_id,
            app_path=app_path,
            action=action,
            args=args,
            kwargs=kwargs
        )

        try:
            # Send request
            DirtyProtocol.write_message(self._sock, request)

            # Receive response
            response = DirtyProtocol.read_message(self._sock)

            # Handle response
            return self._handle_response(response)
        except socket.timeout:
            self._close_socket()
            raise DirtyTimeoutError(
                "Timeout waiting for dirty app response",
                timeout=self.timeout
            )
        except Exception as e:
            self._close_socket()
            if isinstance(e, DirtyError):
                raise
            raise DirtyConnectionError(f"Communication error: {e}") from e

    def _handle_response(self, response):
        """Handle response message, extracting result or raising error."""
        msg_type = response.get("type")

        if msg_type == DirtyProtocol.MSG_TYPE_RESPONSE:
            return response.get("result")
        elif msg_type == DirtyProtocol.MSG_TYPE_ERROR:
            error_info = response.get("error", {})
            error = DirtyError.from_dict(error_info)
            raise error
        else:
            raise DirtyError(f"Unknown response type: {msg_type}")

    def _close_socket(self):
        """Close the socket connection."""
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def close(self):
        """Close the sync connection."""
        with self._lock:
            self._close_socket()

    # -------------------------------------------------------------------------
    # Async API (for async HTTP workers)
    # -------------------------------------------------------------------------

    async def connect_async(self):
        """
        Establish async connection to arbiter.

        Raises:
            DirtyConnectionError: If connection fails
        """
        if self._writer is not None:
            return

        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_unix_connection(self.socket_path),
                timeout=self.timeout
            )
        except asyncio.TimeoutError:
            raise DirtyTimeoutError(
                "Timeout connecting to dirty arbiter",
                timeout=self.timeout
            )
        except (OSError, ConnectionError) as e:
            raise DirtyConnectionError(
                f"Failed to connect to dirty arbiter: {e}",
                socket_path=self.socket_path
            ) from e

    async def execute_async(self, app_path, action, *args, **kwargs):
        """
        Execute an action on a dirty app (async/non-blocking).

        Args:
            app_path: Import path of the dirty app
            action: Action to call on the app
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Result from the dirty app action

        Raises:
            DirtyConnectionError: If connection fails
            DirtyTimeoutError: If operation times out
            DirtyError: If execution fails
        """
        # Ensure connected
        if self._writer is None:
            await self.connect_async()

        # Build request
        request_id = str(uuid.uuid4())
        request = make_request(
            request_id=request_id,
            app_path=app_path,
            action=action,
            args=args,
            kwargs=kwargs
        )

        try:
            # Send request
            await DirtyProtocol.write_message_async(self._writer, request)

            # Receive response with timeout
            response = await asyncio.wait_for(
                DirtyProtocol.read_message_async(self._reader),
                timeout=self.timeout
            )

            # Handle response
            return self._handle_response(response)
        except asyncio.TimeoutError:
            await self._close_async()
            raise DirtyTimeoutError(
                "Timeout waiting for dirty app response",
                timeout=self.timeout
            )
        except Exception as e:
            await self._close_async()
            if isinstance(e, DirtyError):
                raise
            raise DirtyConnectionError(f"Communication error: {e}") from e

    async def _close_async(self):
        """Close the async connection."""
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

    async def close_async(self):
        """Close the async connection."""
        await self._close_async()

    # -------------------------------------------------------------------------
    # Context managers
    # -------------------------------------------------------------------------

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    async def __aenter__(self):
        await self.connect_async()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close_async()


# =============================================================================
# Thread-local and context-local client management
# =============================================================================

# Thread-local storage for sync workers
_thread_local = threading.local()

# Context var for async workers
_async_client_var: contextvars.ContextVar[DirtyClient] = contextvars.ContextVar(
    'dirty_client'
)

# Global socket path (set by arbiter)
_dirty_socket_path = None


def set_dirty_socket_path(path):
    """Set the global dirty socket path (called during initialization)."""
    global _dirty_socket_path
    _dirty_socket_path = path


def get_dirty_socket_path():
    """Get the dirty socket path."""
    if _dirty_socket_path is None:
        # Check environment variable
        path = os.environ.get('GUNICORN_DIRTY_SOCKET')
        if path:
            return path
        raise DirtyError(
            "Dirty socket path not configured. "
            "Make sure dirty_workers > 0 and dirty_apps are configured."
        )
    return _dirty_socket_path


def get_dirty_client(timeout=30.0) -> DirtyClient:
    """
    Get or create a thread-local sync client.

    This is the recommended way to get a client in sync HTTP workers.

    Args:
        timeout: Timeout for operations in seconds

    Returns:
        DirtyClient: Thread-local client instance

    Example::

        from gunicorn.dirty import get_dirty_client

        def my_view(request):
            client = get_dirty_client()
            result = client.execute("myapp.ml:MLApp", "inference", data)
            return result
    """
    client = getattr(_thread_local, 'dirty_client', None)
    if client is None:
        socket_path = get_dirty_socket_path()
        client = DirtyClient(socket_path, timeout=timeout)
        _thread_local.dirty_client = client
    return client


async def get_dirty_client_async(timeout=30.0) -> DirtyClient:
    """
    Get or create a context-local async client.

    This is the recommended way to get a client in async HTTP workers.

    Args:
        timeout: Timeout for operations in seconds

    Returns:
        DirtyClient: Context-local client instance

    Example::

        from gunicorn.dirty import get_dirty_client_async

        async def my_view(request):
            client = await get_dirty_client_async()
            result = await client.execute_async("myapp.ml:MLApp", "inference", data)
            return result
    """
    try:
        client = _async_client_var.get()
    except LookupError:
        socket_path = get_dirty_socket_path()
        client = DirtyClient(socket_path, timeout=timeout)
        _async_client_var.set(client)
    return client


def close_dirty_client():
    """Close the thread-local client (call on worker exit)."""
    client = getattr(_thread_local, 'dirty_client', None)
    if client is not None:
        client.close()
        _thread_local.dirty_client = None


async def close_dirty_client_async():
    """Close the context-local async client."""
    try:
        client = _async_client_var.get()
        await client.close_async()
    except LookupError:
        pass
