# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

from __future__ import with_statement

import errno
import os
import tempfile

class Pidfile(object):
    
    def __get__(self, instance, cls):
        if instance is None:
            return self
            
        return instance._pidfile
        
    def __set__(self, instance, path):
        if not path:
            return
        pid = self.valid_pidfile(path)
        if pid:
            if instance._pidfile is not None and path == instance._pidfile and \
                    pid == os.getpid():
                return path
            raise RuntimeError("Already running on PID %s " \
                        "(or pid file '%s' is stale)" % (os.getpid(), path))
        if instance._pidfile:    
            self.unlink_pidfile(instance, instance._pidfile)

        # write pidfile
        fd, fname = tempfile.mkstemp(dir=os.path.dirname(path))
        os.write(fd, "%s\n" % instance.pid)
        os.rename(fname, path)
        os.close(fd)
        instance._pidfile = path
        
    def __delete__(self, instance):
        self.unlink_pidfile(instance, instance._pidfile)
        instance._pidfile = None
        
    def unlink_pidfile(self, instance, path):
        """ delete pidfile"""
        try:
            with open(path, "r") as f:
                pid =  int(f.read() or 0)
                
            if pid == instance.pid:
                os.unlink(path)
        except:
            pass
        
    def valid_pidfile(self, path):
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