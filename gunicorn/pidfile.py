# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

from __future__ import with_statement

import errno
import os
import tempfile


def set_pidfile(pid, path, oldpath=None):
    oldpid = valid_pidfile(path)
    if oldpid:
        if oldpath is not None and path == oldpath and \
                oldpid == os.getpid():
            return path
        raise RuntimeError("Already running on PID %s " \
                    "(or pid file '%s' is stale)" % (os.getpid(), path))
                    
    if oldpath:    
        unlink_pidfile(pid, path)

    # write pidfile
    fd, fname = tempfile.mkstemp(dir=os.path.dirname(path))
    os.write(fd, "%s\n" % pid)
    os.rename(fname, path)
    os.close(fd)
    return path
    
def unlink_pidfile(pid, path):
    """ delete pidfile"""
    try:
        with open(path, "r") as f:
            pid1 =  int(f.read() or 0)
            
        if pid1 == pid:
            os.unlink(path)
    except:
        pass
    
def valid_pidfile(path):
    """ Validate pidfile and make it stale if needed"""
    try:
        with open(path, "r") as f:
            wpid = int(f.read() or 0)

            if wpid <= 0: return None
 
            try:
                os.kill(wpid, 0)
                return wpid
            except OSError, e:
                if e[0] == errno.ESRCH:
                    return
                raise
    except IOError, e:
        if e[0] == errno.ENOENT:
            return
        raise