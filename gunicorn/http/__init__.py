#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from gunicorn.http.message import Message, Request
from gunicorn.http.parser import RequestParser


def get_parser(cfg, source, source_addr, http2_connection=False):
    """Get appropriate parser based on protocol config.

    Args:
        cfg: Gunicorn config object
        source: Socket or iterable source
        source_addr: Source address tuple or None
        http2_connection: If True, create HTTP/2 connection handler

    Returns:
        Parser instance (RequestParser, UWSGIParser, or HTTP2ServerConnection)
    """
    # HTTP/2 connection
    if http2_connection:
        from gunicorn.http2.connection import HTTP2ServerConnection
        return HTTP2ServerConnection(cfg, source, source_addr)

    # uWSGI protocol
    protocol = getattr(cfg, 'protocol', 'http')
    if protocol == 'uwsgi':
        from gunicorn.uwsgi.parser import UWSGIParser
        return UWSGIParser(cfg, source, source_addr)

    # Default HTTP/1.x
    return RequestParser(cfg, source, source_addr)


__all__ = ['Message', 'Request', 'RequestParser', 'get_parser']
