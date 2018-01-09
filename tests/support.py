import functools
import sys
import unittest
import platform
from wsgiref.validate import validator

HOST = "127.0.0.1"


@validator
def app(environ, start_response):
    """Simplest possible application object"""

    data = b'Hello, World!\n'
    status = '200 OK'

    response_headers = [
        ('Content-type', 'text/plain'),
        ('Content-Length', str(len(data))),
    ]
    start_response(status, response_headers)
    return iter([data])


def requires_mac_ver(*min_version):
    """Decorator raising SkipTest if the OS is Mac OS X and the OS X
    version if less than min_version.

    For example, @requires_mac_ver(10, 5) raises SkipTest if the OS X version
    is lesser than 10.5.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            if sys.platform == 'darwin':
                version_txt = platform.mac_ver()[0]
                try:
                    version = tuple(map(int, version_txt.split('.')))
                except ValueError:
                    pass
                else:
                    if version < min_version:
                        min_version_txt = '.'.join(map(str, min_version))
                        raise unittest.SkipTest(
                            "Mac OS X %s or higher required, not %s"
                            % (min_version_txt, version_txt))
            return func(*args, **kw)
        wrapper.min_version = min_version
        return wrapper
    return decorator

try:
    from types import SimpleNamespace  # pylint: disable=unused-import
except ImportError:
    class SimpleNamespace(object):
        def __init__(self, **kwargs):
            vars(self).update(kwargs)

        def __repr__(self):
            keys = sorted(vars(self))
            items = ("{}={!r}".format(k, vars(self)[k]) for k in keys)
            return "{}({})".format(type(self).__name__, ", ".join(items))

        def __eq__(self, other):
            return vars(self) == vars(other)
