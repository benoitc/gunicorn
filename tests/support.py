import functools
import sys
import unittest
import platform
from wsgiref.validate import validator

HOST = "127.0.0.1"


def create_app(name="World", count=1):
    message = (('Hello, %s!\n' % name) * count).encode("utf8")
    length = str(len(message))

    @validator
    def app(environ, start_response):
        """Simplest possible application object"""

        status = '200 OK'

        response_headers = [
            ('Content-type', 'text/plain'),
            ('Content-Length', length),
        ]
        start_response(status, response_headers)
        return iter([message])

    return app


app = application = create_app()
none_app = None


def error_factory():
    raise TypeError("inner")


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
