# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import os
import tempfile

class WorkerTmp(object):

    def __init__(self):
        self._tmp = tempfile.TemporaryFile(prefix="wgunicorn-")
        self.spinner = 0

    def notify(self): 
        try:
            self.spinner = (self.spinner+1) % 2
            os.fchmod(self._tmp.fileno(), self.spinner)
        except AttributeError:
            # python < 2.6
            self._tmp.truncate(0)
            os.write(self._tmp.fileno(), "X")

    def fileno(self):
        return self._tmp.fileno()
       
    def close(self):
        return self._tmp.close()
