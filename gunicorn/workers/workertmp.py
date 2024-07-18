# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import multiprocessing
import time


class WorkerTmp(object):
    def __init__(self):
        self._val = multiprocessing.Value('d', lock=False)

    def notify(self):
        self._val.value = time.monotonic()

    def last_update(self):
        return self._val.value
