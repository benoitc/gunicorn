# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
HTTP/2 support for Gunicorn.

This module provides HTTP/2 protocol support using the hyper-h2 library.
HTTP/2 requires TLS with ALPN negotiation.
"""

H2_MIN_VERSION = (4, 1, 0)

_h2_available = None
_h2_version = None


def is_http2_available():
    """Check if HTTP/2 support is available.

    Returns:
        bool: True if the h2 library is installed with minimum required version.
    """
    global _h2_available, _h2_version  # pylint: disable=global-statement

    if _h2_available is not None:
        return _h2_available

    try:
        import h2
        version_str = getattr(h2, '__version__', '0.0.0')
        version_parts = tuple(int(x) for x in version_str.split('.')[:3])
        _h2_version = version_parts
        _h2_available = version_parts >= H2_MIN_VERSION
    except ImportError:
        _h2_available = False
        _h2_version = None

    return _h2_available


def get_h2_version():
    """Get the installed h2 library version.

    Returns:
        tuple: Version tuple (major, minor, patch) or None if not installed.
    """
    if _h2_version is None:
        is_http2_available()  # Populate _h2_version
    return _h2_version


def get_http2_connection_class():
    """Get the HTTP2ServerConnection class if h2 is available.

    Returns:
        HTTP2ServerConnection class, or raises HTTP2NotAvailable
    """
    if not is_http2_available():
        from .errors import HTTP2NotAvailable
        raise HTTP2NotAvailable()
    from .connection import HTTP2ServerConnection
    return HTTP2ServerConnection


def get_async_http2_connection_class():
    """Get the AsyncHTTP2Connection class if h2 is available.

    Returns:
        AsyncHTTP2Connection class, or raises HTTP2NotAvailable
    """
    if not is_http2_available():
        from .errors import HTTP2NotAvailable
        raise HTTP2NotAvailable()
    from .async_connection import AsyncHTTP2Connection
    return AsyncHTTP2Connection


__all__ = [
    'is_http2_available',
    'get_h2_version',
    'get_http2_connection_class',
    'get_async_http2_connection_class',
    'H2_MIN_VERSION',
]
