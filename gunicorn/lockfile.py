# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import os

from gunicorn import util

if os.name == 'nt':
    import msvcrt

    def _lock(fd):
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)


    def _unlock(fd):
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            return False
        return True

else:
    import fcntl

    def _lock(fd):
        fcntl.lockf(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)


    def _unlock(fd):
        try:
            fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except:
            print("no unlock")
            return False

        return True


class LockFile(object):
    """Manage a LOCK file"""

    def __init__(self, fname):
        self.fname = fname
        fdir = os.path.dirname(self.fname)
        if fdir and not os.path.isdir(fdir):
            raise RuntimeError("%s doesn't exist. Can't create lock file." % fdir)
        self._lockfile = open(self.fname, 'w+b')
        # set permissions to -rw-r--r--
        os.chmod(self.fname, 420)
        self._locked = False

    def lock(self):
        _lock(self._lockfile.fileno())
        self._locked = True

    def unlock(self):
        if not self.locked():
            return

        if _unlock(self._lockfile.fileno()):
            self._lockfile.close()
            util.unlink(self.fname)
            self._lockfile = None
            self._locked = False

    def locked(self):
        return self._lockfile is not None and self._locked

    def name(self):
        return self.fname
