#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import errno
import os
import tempfile

from gunicorn import compat


def _process_runs(pid):
    """Whether pid names a live process.

    os.kill(pid, 0) is the POSIX probe; Windows would terminate the process
    with it, so the kernel gets asked there instead.
    """
    if compat.WINDOWS:
        return compat.pid_running(pid)

    try:
        os.kill(pid, 0)
    except OSError as e:
        if e.args[0] == errno.EPERM:
            # The process exists but belongs to someone else.
            return True
        if e.args[0] == errno.ESRCH:
            return False
        raise
    return True


class Pidfile:
    """\
    Manage a PID file. If a specific name is provided
    it and '"%s.oldpid" % name' will be used. Otherwise
    we create a temp file using os.mkstemp.
    """

    def __init__(self, fname):
        self.fname = fname
        self.pid = None

    def create(self, pid):
        oldpid = self.validate()
        if oldpid:
            if oldpid == os.getpid():
                return
            msg = "Already running on PID %s (or pid file '%s' is stale)"
            raise RuntimeError(msg % (oldpid, self.fname))

        self.pid = pid

        # Write pidfile
        fdir = os.path.dirname(self.fname)
        if fdir and not os.path.isdir(fdir):
            raise RuntimeError("%s doesn't exist. Can't create pidfile." % fdir)
        fd, fname = tempfile.mkstemp(dir=fdir)
        try:
            os.write(fd, ("%s\n" % self.pid).encode('utf-8'))
        finally:
            # Windows cannot rename a file that is still open.
            os.close(fd)
        if self.fname:
            # replace, not rename: the stale file may still be there
            os.replace(fname, self.fname)
        else:
            self.fname = fname

        # set permissions to -rw-r--r--
        os.chmod(self.fname, 420)

    def rename(self, path):
        self.unlink()
        self.fname = path
        self.create(self.pid)

    def unlink(self):
        """ delete pidfile"""
        try:
            with open(self.fname) as f:
                pid1 = int(f.read() or 0)

            if pid1 == self.pid:
                os.unlink(self.fname)
        except Exception:
            pass

    def validate(self):
        """ Validate pidfile and make it stale if needed"""
        if not self.fname:
            return
        try:
            with open(self.fname) as f:
                try:
                    wpid = int(f.read())
                except ValueError:
                    return

                if _process_runs(wpid):
                    return wpid
                return
        except OSError as e:
            if e.args[0] == errno.ENOENT:
                return
            raise
