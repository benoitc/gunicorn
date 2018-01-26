# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import os.path
import re
import sys

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver


class Reloader(object):

    def __init__(self, extra_files=None, interval=1, callback=None,
                 engine='auto'):
        super(Reloader, self).__init__()
        if engine == 'auto' or engine == 'inotify':
            self._observer = Observer()
        else:
            self._observer = PollingObserver(timeout=interval)
        self._observer.daemon = True
        self._handler = ReloadingEventHandler(callback)
        self._dirs = set()

        if extra_files is not None:
            for filename in extra_files:
                self.add_extra_file(filename)

    def add_extra_file(self, filename):
        dirname = os.path.dirname(filename)
        self._observer.schedule(self._handler, dirname)

    def get_dirs(self):
        fnames = [
            os.path.dirname(re.sub('py[co]$', 'py', module.__file__))
            for module in list(sys.modules.values())
            if hasattr(module, '__file__')
        ]

        return set(fnames)

    def start(self):
        for dirname in self.get_dirs():
            self._observer.schedule(self._handler, dirname)

        self._observer.start()


class ReloadingEventHandler(FileSystemEventHandler):
    def __init__(self, callback=None):
        super(ReloadingEventHandler, self).__init__()
        self._callback = callback

    def on_any_event(self, _event):
        self._callback(_event.src_path)
