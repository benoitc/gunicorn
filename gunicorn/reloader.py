# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.
# pylint: disable=no-else-continue

import os
import os.path
import re
import sys
import time
import threading

COMPILED_EXT_RE = re.compile(r'py[co]$')


class Reloader(threading.Thread):
    def __init__(self, extra_files=None, interval=1, callback=None):
        super().__init__()
        self.daemon = True
        self._extra_files = set(extra_files or ())
        self._interval = interval
        self._callback = callback

    def add_extra_file(self, filename):
        self._extra_files.add(filename)

    def get_files(self):
        fnames = [
            COMPILED_EXT_RE.sub('py', module.__file__)
            for module in tuple(sys.modules.values())
            if getattr(module, '__file__', None)
        ]

        fnames.extend(self._extra_files)

        return fnames

    def run(self):
        mtimes = {}
        while True:
            for filename in self.get_files():
                try:
                    mtime = os.stat(filename).st_mtime
                except OSError:
                    continue
                old_time = mtimes.get(filename)
                if old_time is None:
                    mtimes[filename] = mtime
                    continue
                elif mtime > old_time:
                    if self._callback:
                        self._callback(filename)
            time.sleep(self._interval)


has_inotify = False
try:
    if not sys.platform.startswith('linux'):
        raise ImportError("The inotify mechanism is only supported on Linux")
    import inotify  # pylint: disable=unused-import
    has_inotify = True
except ImportError:
    pass

if has_inotify:
    from gunicorn.ginotify import InotifyReloader
else:
    class InotifyReloader(object):
        def __init__(self, extra_files=None, callback=None):
            raise ImportError('You must have the inotify module installed on '
                              'a linux platform to use the inotify reloader')


preferred_reloader = InotifyReloader if has_inotify else Reloader

reloader_engines = {
    'auto': preferred_reloader,
    'poll': Reloader,
    'inotify': InotifyReloader,
}
