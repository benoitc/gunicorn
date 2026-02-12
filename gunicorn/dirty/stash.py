#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Stash - Global Shared State for Dirty Workers

Provides simple key-value tables stored in the arbiter process.
All workers can read and write to the same tables.

Usage::

    from gunicorn.dirty import stash

    # Basic operations - table is auto-created on first access
    stash.put("sessions", "user:1", {"name": "Alice", "role": "admin"})
    user = stash.get("sessions", "user:1")
    stash.delete("sessions", "user:1")

    # Dict-like interface
    sessions = stash.table("sessions")
    sessions["user:1"] = {"name": "Alice"}
    user = sessions["user:1"]
    del sessions["user:1"]

    # Query operations
    keys = stash.keys("sessions")
    keys = stash.keys("sessions", pattern="user:*")

    # Table management
    stash.ensure("cache")           # Explicit creation (idempotent)
    stash.clear("sessions")         # Delete all entries
    stash.delete_table("sessions")  # Delete the table itself
    tables = stash.tables()         # List all tables

Declarative usage in DirtyApp::

    class MyApp(DirtyApp):
        stashes = ["sessions", "cache"]  # Auto-created on arbiter start

        def __call__(self, action, *args, **kwargs):
            # Tables are ready to use
            stash.put("sessions", "key", "value")

Note: Tables are stored in the arbiter process and are ephemeral.
If the arbiter restarts, all data is lost.
"""

import threading
import uuid

from .errors import DirtyError
from .protocol import (
    DirtyProtocol,
    STASH_OP_PUT,
    STASH_OP_GET,
    STASH_OP_DELETE,
    STASH_OP_KEYS,
    STASH_OP_CLEAR,
    STASH_OP_INFO,
    STASH_OP_ENSURE,
    STASH_OP_DELETE_TABLE,
    STASH_OP_TABLES,
    STASH_OP_EXISTS,
    make_stash_message,
)


class StashError(DirtyError):
    """Base exception for stash operations."""


class StashTableNotFoundError(StashError):
    """Raised when a table does not exist."""

    def __init__(self, table_name):
        self.table_name = table_name
        super().__init__(f"Stash table not found: {table_name}")


class StashKeyNotFoundError(StashError):
    """Raised when a key does not exist in a table."""

    def __init__(self, table_name, key):
        self.table_name = table_name
        self.key = key
        super().__init__(f"Key not found in {table_name}: {key}")


class StashClient:
    """
    Client for stash operations.

    Communicates with the arbiter which stores all tables in memory.
    """

    def __init__(self, socket_path, timeout=30.0):
        """
        Initialize the stash client.

        Args:
            socket_path: Path to the dirty arbiter's Unix socket
            timeout: Default timeout for operations in seconds
        """
        self.socket_path = socket_path
        self.timeout = timeout
        self._sock = None
        self._lock = threading.Lock()

    def _get_request_id(self):
        """Generate a unique request ID."""
        return str(uuid.uuid4())

    def _connect(self):
        """Establish connection to arbiter."""
        import socket
        if self._sock is not None:
            return

        try:
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._sock.settimeout(self.timeout)
            self._sock.connect(self.socket_path)
        except (socket.error, OSError) as e:
            self._sock = None
            raise StashError(f"Failed to connect to arbiter: {e}") from e

    def _close(self):
        """Close the connection."""
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def _execute(self, op, table, key=None, value=None, pattern=None):
        """
        Execute a stash operation.

        Args:
            op: Operation code (STASH_OP_*)
            table: Table name
            key: Optional key
            value: Optional value
            pattern: Optional pattern for keys operation

        Returns:
            Result from the operation
        """
        with self._lock:
            if self._sock is None:
                self._connect()

            request_id = self._get_request_id()
            message = make_stash_message(
                request_id, op, table,
                key=key, value=value, pattern=pattern
            )

            try:
                DirtyProtocol.write_message(self._sock, message)
                response = DirtyProtocol.read_message(self._sock)

                msg_type = response.get("type")
                if msg_type == DirtyProtocol.MSG_TYPE_RESPONSE:
                    return response.get("result")
                elif msg_type == DirtyProtocol.MSG_TYPE_ERROR:
                    error_info = response.get("error", {})
                    error_type = error_info.get("error_type", "StashError")
                    error_msg = error_info.get("message", "Unknown error")

                    if error_type == "StashTableNotFoundError":
                        raise StashTableNotFoundError(table)
                    if error_type == "StashKeyNotFoundError":
                        raise StashKeyNotFoundError(table, key)
                    raise StashError(error_msg)
                else:
                    raise StashError(f"Unexpected response type: {msg_type}")

            except Exception as e:
                self._close()
                if isinstance(e, StashError):
                    raise
                raise StashError(f"Stash operation failed: {e}") from e

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def put(self, table, key, value):
        """
        Store a value in a table.

        The table is automatically created if it doesn't exist.

        Args:
            table: Table name
            key: Key to store under
            value: Value to store (must be serializable)
        """
        self._execute(STASH_OP_PUT, table, key=key, value=value)

    def get(self, table, key, default=None):
        """
        Retrieve a value from a table.

        Args:
            table: Table name
            key: Key to retrieve
            default: Default value if key not found

        Returns:
            The stored value, or default if not found
        """
        try:
            return self._execute(STASH_OP_GET, table, key=key)
        except StashKeyNotFoundError:
            return default

    def delete(self, table, key):
        """
        Delete a key from a table.

        Args:
            table: Table name
            key: Key to delete

        Returns:
            True if key was deleted, False if it didn't exist
        """
        return self._execute(STASH_OP_DELETE, table, key=key)

    def keys(self, table, pattern=None):
        """
        Get all keys in a table, optionally filtered by pattern.

        Args:
            table: Table name
            pattern: Optional glob pattern (e.g., "user:*")

        Returns:
            List of keys
        """
        return self._execute(STASH_OP_KEYS, table, pattern=pattern)

    def clear(self, table):
        """
        Delete all entries in a table.

        Args:
            table: Table name
        """
        self._execute(STASH_OP_CLEAR, table)

    def info(self, table):
        """
        Get information about a table.

        Args:
            table: Table name

        Returns:
            Dict with table info (size, etc.)
        """
        return self._execute(STASH_OP_INFO, table)

    def ensure(self, table):
        """
        Ensure a table exists (create if not exists).

        This is idempotent - calling it multiple times is safe.

        Args:
            table: Table name
        """
        self._execute(STASH_OP_ENSURE, table)

    def exists(self, table, key=None):
        """
        Check if a table or key exists.

        Args:
            table: Table name
            key: Optional key to check within the table

        Returns:
            True if exists, False otherwise
        """
        return self._execute(STASH_OP_EXISTS, table, key=key)

    def delete_table(self, table):
        """
        Delete an entire table.

        Args:
            table: Table name
        """
        self._execute(STASH_OP_DELETE_TABLE, table)

    def tables(self):
        """
        List all tables.

        Returns:
            List of table names
        """
        return self._execute(STASH_OP_TABLES, "")

    def table(self, name):
        """
        Get a dict-like interface to a table.

        Args:
            name: Table name

        Returns:
            StashTable instance
        """
        return StashTable(self, name)

    def close(self):
        """Close the client connection."""
        with self._lock:
            self._close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class StashTable:
    """
    Dict-like interface to a stash table.

    Example::

        sessions = stash.table("sessions")
        sessions["user:1"] = {"name": "Alice"}
        user = sessions["user:1"]
        del sessions["user:1"]

        # Iteration
        for key in sessions:
            print(key, sessions[key])
    """

    def __init__(self, client, name):
        self._client = client
        self._name = name

    @property
    def name(self):
        """Table name."""
        return self._name

    def __getitem__(self, key):
        result = self._client.get(self._name, key)
        if result is None:
            # Check if key actually exists with None value
            if not self._client.exists(self._name, key):
                raise KeyError(key)
        return result

    def __setitem__(self, key, value):
        self._client.put(self._name, key, value)

    def __delitem__(self, key):
        if not self._client.delete(self._name, key):
            raise KeyError(key)

    def __contains__(self, key):
        return self._client.exists(self._name, key)

    def __iter__(self):
        return iter(self._client.keys(self._name))

    def __len__(self):
        info = self._client.info(self._name)
        return info.get("size", 0)

    def get(self, key, default=None):
        """Get value with default."""
        return self._client.get(self._name, key, default)

    def keys(self, pattern=None):
        """Get all keys, optionally filtered by pattern."""
        return self._client.keys(self._name, pattern=pattern)

    def clear(self):
        """Delete all entries."""
        self._client.clear(self._name)

    def items(self):
        """Iterate over (key, value) pairs."""
        for key in self._client.keys(self._name):
            yield key, self._client.get(self._name, key)

    def values(self):
        """Iterate over values."""
        for key in self._client.keys(self._name):
            yield self._client.get(self._name, key)


# =============================================================================
# Global stash instance (module-level API)
# =============================================================================

# Thread-local storage for stash clients
_thread_local = threading.local()

# Global socket path
_stash_socket_path = None


def set_stash_socket_path(path):
    """Set the global stash socket path (called during initialization)."""
    global _stash_socket_path  # pylint: disable=global-statement
    _stash_socket_path = path


def get_stash_socket_path():
    """Get the stash socket path."""
    import os
    if _stash_socket_path is None:
        # Check environment variable
        path = os.environ.get('GUNICORN_DIRTY_SOCKET')
        if path:
            return path
        raise StashError(
            "Stash socket path not configured. "
            "Make sure dirty_workers > 0 and dirty_apps are configured."
        )
    return _stash_socket_path


def _get_client():
    """Get or create a thread-local stash client."""
    client = getattr(_thread_local, 'stash_client', None)
    if client is None:
        socket_path = get_stash_socket_path()
        client = StashClient(socket_path)
        _thread_local.stash_client = client
    return client


# Module-level functions that use the thread-local client

def put(table, key, value):
    """Store a value in a table."""
    _get_client().put(table, key, value)


def get(table, key, default=None):
    """Retrieve a value from a table."""
    return _get_client().get(table, key, default)


def delete(table, key):
    """Delete a key from a table."""
    return _get_client().delete(table, key)


def keys(table, pattern=None):
    """Get all keys in a table."""
    return _get_client().keys(table, pattern)


def clear(table):
    """Delete all entries in a table."""
    _get_client().clear(table)


def info(table):
    """Get information about a table."""
    return _get_client().info(table)


def ensure(table):
    """Ensure a table exists."""
    _get_client().ensure(table)


def exists(table, key=None):
    """Check if a table or key exists."""
    return _get_client().exists(table, key)


def delete_table(table):
    """Delete an entire table."""
    _get_client().delete_table(table)


def tables():
    """List all tables."""
    return _get_client().tables()


def table(name):
    """Get a dict-like interface to a table."""
    return _get_client().table(name)
