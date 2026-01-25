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
import time
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

    def stream(self, app_path, action, *args, **kwargs):
        """
        Stream results from a dirty app action (sync).

        This method returns an iterator that yields chunks from a streaming
        response. Use this for actions that return generators.

        Args:
            app_path: Import path of the dirty app (e.g., 'myapp.ml:MLApp')
            action: Action to call on the app
            *args: Positional arguments
            **kwargs: Keyword arguments

        Yields:
            Chunks of data from the streaming response

        Raises:
            DirtyConnectionError: If connection fails
            DirtyTimeoutError: If operation times out
            DirtyError: If execution fails

        Example::

            for chunk in client.stream("myapp.llm:LLMApp", "generate", prompt):
                print(chunk, end="", flush=True)
        """
        return DirtyStreamIterator(self, app_path, action, args, kwargs)

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

    def stream_async(self, app_path, action, *args, **kwargs):
        """
        Stream results from a dirty app action (async).

        This method returns an async iterator that yields chunks from a
        streaming response. Use this for actions that return generators.

        Args:
            app_path: Import path of the dirty app (e.g., 'myapp.ml:MLApp')
            action: Action to call on the app
            *args: Positional arguments
            **kwargs: Keyword arguments

        Yields:
            Chunks of data from the streaming response

        Raises:
            DirtyConnectionError: If connection fails
            DirtyTimeoutError: If operation times out
            DirtyError: If execution fails

        Example::

            async for chunk in client.stream_async("myapp.llm:LLMApp", "generate", prompt):
                await response.write(chunk)
        """
        return DirtyAsyncStreamIterator(self, app_path, action, args, kwargs)

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
# Stream Iterator classes
# =============================================================================


class DirtyStreamIterator:
    """
    Iterator for streaming responses from dirty workers (sync).

    This class is returned by `DirtyClient.stream()` and yields chunks
    from a streaming response until the end message is received.

    Uses a deadline-based timeout approach:
    - Total stream timeout: limits entire stream duration
    - Idle timeout: limits gap between chunks (defaults to total timeout)
    """

    # Default idle timeout between chunks (seconds)
    DEFAULT_IDLE_TIMEOUT = 30.0

    # Threshold for applying per-read timeout (seconds)
    # When remaining time is above this, use a larger timeout for efficiency
    _TIMEOUT_THRESHOLD = 5.0

    def __init__(self, client, app_path, action, args, kwargs,
                 idle_timeout=None):
        self.client = client
        self.app_path = app_path
        self.action = action
        self.args = args
        self.kwargs = kwargs
        self._started = False
        self._exhausted = False
        self._request_id = None
        self._deadline = None
        self._last_chunk_time = None
        # Idle timeout: max time between chunks
        self._idle_timeout = (
            idle_timeout if idle_timeout is not None
            else min(self.DEFAULT_IDLE_TIMEOUT, client.timeout)
        )

    def __iter__(self):
        return self

    def __next__(self):
        if self._exhausted:
            raise StopIteration

        if not self._started:
            self._start_request()
            self._started = True

        return self._read_next_chunk()

    def _start_request(self):
        """Send the initial request to the arbiter."""
        with self.client._lock:
            if self.client._sock is None:
                self.client.connect()

            # Set deadline for entire stream
            now = time.monotonic()
            self._deadline = now + self.client.timeout
            self._last_chunk_time = now

            self._request_id = str(uuid.uuid4())
            request = make_request(
                self._request_id,
                self.app_path,
                self.action,
                args=self.args,
                kwargs=self.kwargs,
            )
            DirtyProtocol.write_message(self.client._sock, request)

    def _read_next_chunk(self):
        """Read the next message from the stream."""
        with self.client._lock:
            # Check total stream deadline
            now = time.monotonic()
            if now >= self._deadline:
                self._exhausted = True
                raise DirtyTimeoutError(
                    "Stream exceeded total timeout",
                    timeout=self.client.timeout
                )

            remaining = self._deadline - now

            # Set socket timeout based on remaining time
            # Fast path: use larger timeout when plenty of time remains
            if remaining > self._TIMEOUT_THRESHOLD:
                read_timeout = self._TIMEOUT_THRESHOLD
            else:
                read_timeout = min(remaining, self._idle_timeout)

            try:
                self.client._sock.settimeout(read_timeout)
                response = DirtyProtocol.read_message(self.client._sock)
            except socket.timeout:
                # Check which timeout was hit
                now = time.monotonic()
                if now >= self._deadline:
                    self._exhausted = True
                    raise DirtyTimeoutError(
                        "Stream exceeded total timeout",
                        timeout=self.client.timeout
                    )
                idle_duration = now - self._last_chunk_time
                self._exhausted = True
                raise DirtyTimeoutError(
                    f"Timeout waiting for next chunk (idle {idle_duration:.1f}s)",
                    timeout=self._idle_timeout
                )
            except Exception as e:
                self._exhausted = True
                self.client._close_socket()
                raise DirtyConnectionError(f"Communication error: {e}") from e

            # Update last chunk time for idle tracking
            self._last_chunk_time = time.monotonic()

            msg_type = response.get("type")

            # Chunk message - return the data
            if msg_type == DirtyProtocol.MSG_TYPE_CHUNK:
                return response.get("data")

            # End message - stop iteration
            if msg_type == DirtyProtocol.MSG_TYPE_END:
                self._exhausted = True
                raise StopIteration

            # Error message - raise exception
            if msg_type == DirtyProtocol.MSG_TYPE_ERROR:
                self._exhausted = True
                error_info = response.get("error", {})
                raise DirtyError.from_dict(error_info)

            # Regular response - shouldn't happen for streaming, but handle it
            if msg_type == DirtyProtocol.MSG_TYPE_RESPONSE:
                self._exhausted = True
                # Return the result as the only chunk then stop
                raise StopIteration

            # Unknown type
            self._exhausted = True
            raise DirtyError(f"Unknown message type: {msg_type}")


class DirtyAsyncStreamIterator:
    """
    Async iterator for streaming responses from dirty workers.

    This class is returned by `DirtyClient.stream_async()` and yields chunks
    from a streaming response until the end message is received.

    Uses a deadline-based timeout approach for efficiency:
    - Total stream timeout: limits entire stream duration
    - Idle timeout: limits gap between chunks (defaults to total timeout)

    This avoids the overhead of asyncio.wait_for() on every chunk read.
    """

    # Default idle timeout between chunks (seconds)
    DEFAULT_IDLE_TIMEOUT = 30.0

    def __init__(self, client, app_path, action, args, kwargs,
                 idle_timeout=None):
        self.client = client
        self.app_path = app_path
        self.action = action
        self.args = args
        self.kwargs = kwargs
        self._started = False
        self._exhausted = False
        self._request_id = None
        self._deadline = None
        self._last_chunk_time = None
        # Idle timeout: max time between chunks
        self._idle_timeout = (
            idle_timeout if idle_timeout is not None
            else min(self.DEFAULT_IDLE_TIMEOUT, client.timeout)
        )

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._exhausted:
            raise StopAsyncIteration

        if not self._started:
            await self._start_request()
            self._started = True

        return await self._read_next_chunk()

    async def _start_request(self):
        """Send the initial request to the arbiter."""
        if self.client._writer is None:
            await self.client.connect_async()

        # Set deadline for entire stream
        now = time.monotonic()
        self._deadline = now + self.client.timeout
        self._last_chunk_time = now

        self._request_id = str(uuid.uuid4())
        request = make_request(
            self._request_id,
            self.app_path,
            self.action,
            args=self.args,
            kwargs=self.kwargs,
        )
        await DirtyProtocol.write_message_async(self.client._writer, request)

    # Threshold for applying timeout wrapper (seconds)
    # When remaining time is above this, skip timeout for performance
    _TIMEOUT_THRESHOLD = 5.0

    async def _read_next_chunk(self):
        """Read the next message from the stream."""
        # Calculate remaining time until deadline
        now = time.monotonic()

        # Check total stream deadline
        if now >= self._deadline:
            self._exhausted = True
            raise DirtyTimeoutError(
                "Stream exceeded total timeout",
                timeout=self.client.timeout
            )

        remaining = self._deadline - now

        try:
            # Fast path: skip timeout wrapper when we have plenty of time
            # This avoids asyncio.wait_for() overhead for most chunks
            if remaining > self._TIMEOUT_THRESHOLD:
                response = await DirtyProtocol.read_message_async(
                    self.client._reader
                )
            else:
                # Near deadline: apply timeout protection
                read_timeout = min(remaining, self._idle_timeout)
                response = await asyncio.wait_for(
                    DirtyProtocol.read_message_async(self.client._reader),
                    timeout=read_timeout
                )
        except asyncio.TimeoutError:
            self._exhausted = True
            now = time.monotonic()
            if now >= self._deadline:
                raise DirtyTimeoutError(
                    "Stream exceeded total timeout",
                    timeout=self.client.timeout
                )
            idle_duration = now - self._last_chunk_time
            raise DirtyTimeoutError(
                f"Timeout waiting for next chunk (idle {idle_duration:.1f}s)",
                timeout=self._idle_timeout
            )
        except Exception as e:
            self._exhausted = True
            await self.client._close_async()
            raise DirtyConnectionError(f"Communication error: {e}") from e

        # Update last chunk time for idle tracking
        self._last_chunk_time = time.monotonic()

        msg_type = response.get("type")

        # Chunk message - return the data
        if msg_type == DirtyProtocol.MSG_TYPE_CHUNK:
            return response.get("data")

        # End message - stop iteration
        if msg_type == DirtyProtocol.MSG_TYPE_END:
            self._exhausted = True
            raise StopAsyncIteration

        # Error message - raise exception
        if msg_type == DirtyProtocol.MSG_TYPE_ERROR:
            self._exhausted = True
            error_info = response.get("error", {})
            raise DirtyError.from_dict(error_info)

        # Regular response - shouldn't happen for streaming
        if msg_type == DirtyProtocol.MSG_TYPE_RESPONSE:
            self._exhausted = True
            raise StopAsyncIteration

        # Unknown type
        self._exhausted = True
        raise DirtyError(f"Unknown message type: {msg_type}")


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
    global _dirty_socket_path  # pylint: disable=global-statement
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
