#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Fast HTTP parser utilities using gunicorn_h1c.

This module provides factory functions to select between the pure Python
HTTP parser and the fast C-based parser (gunicorn_h1c).
"""

# Cached import state
_h1c_available = None
_h1c_module = None


def _check_h1c_available():
    """Check if gunicorn_h1c is available and cache the result."""
    global _h1c_available, _h1c_module
    if _h1c_available is None:
        try:
            import gunicorn_h1c
            _h1c_module = gunicorn_h1c
            _h1c_available = True
        except ImportError:
            _h1c_available = False
    return _h1c_available


def is_fast_parser_available():
    """Check if the fast HTTP parser is available.

    Returns:
        bool: True if gunicorn_h1c is installed and available.
    """
    return _check_h1c_available()


def get_h1c_module():
    """Get the gunicorn_h1c module.

    Returns:
        module: The gunicorn_h1c module if available, None otherwise.
    """
    _check_h1c_available()
    return _h1c_module


def get_request_class(cfg, async_mode=False):
    """Get the appropriate Request class based on configuration.

    Args:
        cfg: Gunicorn config object with http_parser setting.
        async_mode: If True, return async Request class for ASGI workers.

    Returns:
        class: FastRequest/FastAsyncRequest if fast parser is enabled,
               otherwise Request/AsyncRequest.

    Raises:
        RuntimeError: If http_parser='fast' but gunicorn_h1c is not installed.
    """
    http_parser = getattr(cfg, 'http_parser', 'auto')

    if http_parser == 'python':
        # Always use pure Python parser
        if async_mode:
            from gunicorn.asgi.message import AsyncRequest
            return AsyncRequest
        else:
            from gunicorn.http.message import Request
            return Request

    if http_parser == 'fast':
        # Require fast parser
        if not _check_h1c_available():
            raise RuntimeError(
                "Fast HTTP parser requested (--http-parser=fast) but "
                "gunicorn_h1c is not installed. Install with: "
                "pip install gunicorn[fast-parser]"
            )

    # 'auto' or 'fast' with module available
    if _check_h1c_available():
        if async_mode:
            from gunicorn.asgi.fast_message import FastAsyncRequest
            return FastAsyncRequest
        else:
            from gunicorn.http.fast_message import FastRequest
            return FastRequest

    # 'auto' fallback to pure Python
    if async_mode:
        from gunicorn.asgi.message import AsyncRequest
        return AsyncRequest
    else:
        from gunicorn.http.message import Request
        return Request


def get_parser_class(cfg):
    """Get the appropriate Parser class based on configuration.

    This is used by the WSGI workers that use RequestParser.

    Args:
        cfg: Gunicorn config object with http_parser setting.

    Returns:
        class: FastRequestParser if fast parser is enabled,
               otherwise RequestParser.
    """
    http_parser = getattr(cfg, 'http_parser', 'auto')

    if http_parser == 'python':
        from gunicorn.http.parser import RequestParser
        return RequestParser

    if http_parser == 'fast':
        if not _check_h1c_available():
            raise RuntimeError(
                "Fast HTTP parser requested (--http-parser=fast) but "
                "gunicorn_h1c is not installed. Install with: "
                "pip install gunicorn[fast-parser]"
            )

    # 'auto' or 'fast' with module available
    if _check_h1c_available():
        from gunicorn.http.fast_message import FastRequestParser
        return FastRequestParser

    # 'auto' fallback
    from gunicorn.http.parser import RequestParser
    return RequestParser


def parse_to_wsgi_environ(data, server=None, client=None, url_scheme="http"):
    """Parse HTTP request and return WSGI environ dict directly from C.

    Args:
        data: Raw HTTP request bytes
        server: (host, port) tuple or None
        client: (host, port) tuple or None
        url_scheme: URL scheme string ("http" or "https")

    Returns:
        dict: WSGI environ dict with _consumed key for bytes consumed

    Raises:
        RuntimeError: If gunicorn_h1c is not available
    """
    if not _check_h1c_available():
        raise RuntimeError("gunicorn_h1c not available")
    return _h1c_module.parse_to_wsgi_environ(
        data, server=server, client=client, url_scheme=url_scheme
    )


def parse_to_asgi_scope(data, server=None, client=None, scheme="http", root_path=""):
    """Parse HTTP request and return ASGI scope dict directly from C.

    Args:
        data: Raw HTTP request bytes
        server: (host, port) tuple or None
        client: (host, port) tuple or None
        scheme: URL scheme string ("http" or "https")
        root_path: ASGI root_path

    Returns:
        dict: ASGI scope dict with _consumed key for bytes consumed

    Raises:
        RuntimeError: If gunicorn_h1c is not available
    """
    if not _check_h1c_available():
        raise RuntimeError("gunicorn_h1c not available")
    return _h1c_module.parse_to_asgi_scope(
        data, server=server, client=client, scheme=scheme, root_path=root_path
    )
