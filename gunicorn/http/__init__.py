#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from gunicorn.http.message import Message, Request
from gunicorn.http.parser import RequestParser


def get_parser(cfg, source, source_addr):
    """Get appropriate parser based on protocol config.

    Args:
        cfg: Gunicorn config object
        source: Socket or iterable source
        source_addr: Source address tuple or None

    Returns:
        Parser instance (RequestParser or UWSGIParser)
    """
    protocol = getattr(cfg, 'protocol', 'http')
    if protocol == 'uwsgi':
        from gunicorn.uwsgi.parser import UWSGIParser
        return UWSGIParser(cfg, source, source_addr)
    return RequestParser(cfg, source, source_addr)


__all__ = ['Message', 'Request', 'RequestParser', 'get_parser']
