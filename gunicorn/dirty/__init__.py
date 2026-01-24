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

from .protocol import (
    DirtyProtocol,
    make_request,
    make_response,
    make_error_response,
)

from .app import (
    DirtyApp,
    load_dirty_app,
    load_dirty_apps,
)

from .worker import DirtyWorker
from .arbiter import DirtyArbiter
from .client import (
    DirtyClient,
    get_dirty_client,
    get_dirty_client_async,
    set_dirty_socket_path,
    get_dirty_socket_path,
    close_dirty_client,
    close_dirty_client_async,
)

__all__ = [
    # Errors
    "DirtyError",
    "DirtyTimeoutError",
    "DirtyConnectionError",
    "DirtyWorkerError",
    "DirtyAppError",
    "DirtyAppNotFoundError",
    "DirtyProtocolError",
    # Protocol
    "DirtyProtocol",
    "make_request",
    "make_response",
    "make_error_response",
    # App
    "DirtyApp",
    "load_dirty_app",
    "load_dirty_apps",
    # Worker
    "DirtyWorker",
    # Arbiter
    "DirtyArbiter",
    # Client
    "DirtyClient",
    "get_dirty_client",
    "get_dirty_client_async",
    "set_dirty_socket_path",
    "get_dirty_socket_path",
    "close_dirty_client",
    "close_dirty_client_async",
]
