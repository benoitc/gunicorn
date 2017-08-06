# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

__all__ = ['Reloader', 'reloader_engines']

try:
    from gunicorn._reloader import Reloader
except ImportError:
    class Reloader(object):
        def __init__(self, *args, **kwargs):
            raise RuntimeError('You must have the watchdog module '
                               'installed to use the reloader')

# Note: inotify is an alias for 'auto'
reloader_engines = ('auto', 'poll', 'inotify')
