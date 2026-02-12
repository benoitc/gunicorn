#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Dirty Arbiters - Separate process pool for long-running operations.

Dirty Arbiters provide a separate process pool for executing long-running,
blocking operations (AI model loading, heavy computation) without blocking
HTTP workers. Inspired by Erlang's dirty schedulers.

Key Properties:
- Completely separate from HTTP workers - can be killed/restarted independently
- Stateful - loaded resources persist in dirty worker memory
- Message-passing IPC via Unix sockets with JSON serialization
- Explicit execute() API (no hidden IPC)
- Asyncio-based for clean concurrent handling and future streaming support
"""

from .errors import (
    DirtyError,
    DirtyTimeoutError,
    DirtyConnectionError,
    DirtyWorkerError,
    DirtyAppError,
    DirtyAppNotFoundError,
    DirtyProtocolError,
)

from .app import DirtyApp

from .client import (
    DirtyClient,
    get_dirty_client,
    get_dirty_client_async,
    set_dirty_socket_path,
    close_dirty_client,
    close_dirty_client_async,
)

# Stash (shared state between workers)
from . import stash
from .stash import (
    StashClient,
    StashTable,
    StashError,
    StashTableNotFoundError,
    StashKeyNotFoundError,
)

# Internal imports used by gunicorn core (not part of public API)
from .arbiter import DirtyArbiter

__all__ = [
    # Errors
    "DirtyError",
    "DirtyTimeoutError",
    "DirtyConnectionError",
    "DirtyWorkerError",
    "DirtyAppError",
    "DirtyAppNotFoundError",
    "DirtyProtocolError",
    # App base class
    "DirtyApp",
    # Client
    "DirtyClient",
    "get_dirty_client",
    "get_dirty_client_async",
    "close_dirty_client",
    "close_dirty_client_async",
    # Stash (shared state)
    "stash",
    "StashClient",
    "StashTable",
    "StashError",
    "StashTableNotFoundError",
    "StashKeyNotFoundError",
    # Internal (used by gunicorn core)
    "DirtyArbiter",
    "set_dirty_socket_path",
]
