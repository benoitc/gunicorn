# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

from __future__ import with_statement

import errno
import os
import tempfile


class Pidfile(object):
    
    def __init__(self, path):
        self.path = path
        self.pid = None
        
    def create(self, pid):
        oldpid = self.validate()
        if oldpid:
            if oldpid == os.getpid():
                return
            raise RuntimeError("Already running on PID %s " \
                "(or pid file '%s' is stale)" % (os.getpid(), self.path))

        self.pid = pid
        
        # write pidfile
        fd, fname = tempfile.mkstemp(dir=os.path.dirname(self.path))
        os.write(fd, "%s\n" % self.pid)
        os.rename(fname, self.path)
        os.close(fd)
        
    def rename(self, path):
        self.unlink()
        self.path = path
        self.create(self.pid)
        
    def unlink(self):
        """ delete pidfile"""
        try:
            with open(self.path, "r") as f:
                pid1 =  int(f.read() or 0)

            if pid1 == self.pid:
                os.unlink(self.path)
        except:
            pass
       
    def validate(self):
        """ Validate pidfile and make it stale if needed"""
        try:
            with open(self.path, "r") as f:
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