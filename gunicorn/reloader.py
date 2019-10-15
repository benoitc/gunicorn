# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

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
        self.setDaemon(True)
        self._extra_files = set(extra_files or ())
        self._extra_files_lock = threading.RLock()
        self._interval = interval
        self._callback = callback

    def add_extra_file(self, filename):
        with self._extra_files_lock:
            self._extra_files.add(filename)

    def get_files(self):
        fnames = [
            COMPILED_EXT_RE.sub('py', module.__file__)
            for module in tuple(sys.modules.values())
            if getattr(module, '__file__', None)
        ]

        with self._extra_files_lock:
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
if sys.platform.startswith('linux'):
    try:
        from inotify.adapters import InotifyTrees
        import inotify.constants
        has_inotify = True
    except ImportError:
        pass


if has_inotify:

    class InotifyReloader(threading.Thread):
        event_mask = (inotify.constants.IN_CREATE | inotify.constants.IN_DELETE
                      | inotify.constants.IN_DELETE_SELF | inotify.constants.IN_MODIFY
                      | inotify.constants.IN_MOVE_SELF | inotify.constants.IN_MOVED_FROM
                      | inotify.constants.IN_MOVED_TO)

        def __init__(self, extra_files=None, callback=None):
            super().__init__()
            self.setDaemon(True)
            self._callback = callback
            self._dirs = set()
            self._watcher = InotifyTrees(mask=self.event_mask)

            for extra_file in extra_files:
                self.add_extra_file(extra_file)

        def add_extra_file(self, filename):
            dirname = os.path.dirname(filename)

            if dirname in self._dirs:
                return

            self._watcher.__load_trees([dirname])
            self._dirs.add(dirname)

        def get_dirs(self):
            fnames = [
                os.path.dirname(COMPILED_EXT_RE.sub('py', module.__file__))
                for module in tuple(sys.modules.values())
                if getattr(module, '__file__', None)
            ]

            return set(fnames)

        def run(self):
            self._dirs = self.get_dirs()

            for dirname in self._dirs:
                self._watcher.__load_trees(dirname)

            for event in self._watcher.event_gen():
                if event is None:
                    continue

                filename = event[3]

                self._callback(filename)

else:

    class InotifyReloader(object):
        def __init__(self, callback=None):
            raise ImportError('You must have the inotify module installed to '
                              'use the inotify reloader')


preferred_reloader = InotifyReloader if has_inotify else Reloader

reloader_engines = {
    'auto': preferred_reloader,
    'poll': Reloader,
    'inotify': InotifyReloader,
}
