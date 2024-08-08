# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import os
import os.path
import re
import sys
import threading

from inotify.adapters import Inotify
import inotify.constants


COMPILED_EXT_RE = re.compile(r'py[co]$')


class InotifyReloader(threading.Thread):
    event_mask = (inotify.constants.IN_CREATE | inotify.constants.IN_DELETE
                  | inotify.constants.IN_DELETE_SELF | inotify.constants.IN_MODIFY
                  | inotify.constants.IN_MOVE_SELF | inotify.constants.IN_MOVED_FROM
                  | inotify.constants.IN_MOVED_TO)

    def __init__(self, extra_files=None, callback=None):
        super().__init__()
        self.daemon = True
        self._callback = callback
        self._dirs = set()
        self._watcher = Inotify()

        for extra_file in extra_files:
            self.add_extra_file(extra_file)

    def add_extra_file(self, filename):
        dirname = os.path.dirname(filename)

        if dirname in self._dirs:
            return

        self._watcher.add_watch(dirname, mask=self.event_mask)
        self._dirs.add(dirname)

    def get_dirs(self):
        fnames = [
            os.path.dirname(os.path.abspath(COMPILED_EXT_RE.sub('py', module.__file__)))
            for module in tuple(sys.modules.values())
            if getattr(module, '__file__', None)
        ]

        return set(fnames)

    def run(self):
        self._dirs = self.get_dirs()

        for dirname in self._dirs:
            if os.path.isdir(dirname):
                self._watcher.add_watch(dirname, mask=self.event_mask)

        for event in self._watcher.event_gen():
            if event is None:
                continue

            filename = event[3]

            self._callback(filename)
