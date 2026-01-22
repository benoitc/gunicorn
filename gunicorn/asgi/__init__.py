#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
ASGI support for gunicorn.

This module provides native ASGI worker support, using gunicorn's own
HTTP parsing infrastructure adapted for async I/O.

Components:
- AsyncUnreader: Async socket reading with pushback buffer
- AsyncRequest: Async HTTP request parser
- ASGIProtocol: asyncio.Protocol implementation for HTTP handling
- WebSocketProtocol: WebSocket protocol handler (RFC 6455)
- LifespanManager: ASGI lifespan protocol support

Usage:
    gunicorn -k asgi myapp:app
"""

from gunicorn.asgi.unreader import AsyncUnreader
from gunicorn.asgi.message import AsyncRequest
from gunicorn.asgi.lifespan import LifespanManager

__all__ = ['AsyncUnreader', 'AsyncRequest', 'LifespanManager']
