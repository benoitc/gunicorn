import sys

from gunicorn.glogging import LazyWriter


def test_lazywriter_isatty():
    orig = sys.stdout
    sys.stdout = LazyWriter('test.log')
    try:
        sys.stdout.isatty()
    except AttributeError:
        raise AssertionError("LazyWriter has no attribute 'isatty'")
    sys.stdout = orig
