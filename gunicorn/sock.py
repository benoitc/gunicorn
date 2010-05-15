# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import errno
import logging
import os
import socket
import sys
import time

from gunicorn import util

log = logging.getLogger(__name__)

class BaseSocket(object):
    
    def __init__(self, conf, fd=None):
        self.conf = conf
        self.address = conf.address
        if fd is None:
            sock = socket.socket(self.FAMILY, socket.SOCK_STREAM)
        else:
            sock = socket.fromfd(fd, self.FAMILY, socket.SOCK_STREAM)
        self.sock = self.set_options(sock, bound=(fd is not None))
    
    def __str__(self, name):
        return "<socket %d>" % self.sock.fileno()
    
    def __getattr__(self, name):
        return getattr(self.sock, name)
    
    def set_options(self, sock, bound=False):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if not bound:
            self.bind(sock)
        sock.setblocking(0)
        sock.listen(self.conf.backlog)
        
        return sock
        
    def bind(self, sock):
        sock.bind(self.address)

class TCPSocket(BaseSocket):
    
    FAMILY = socket.AF_INET
    
    def __str__(self):
        return "http://%s:%d" % self.sock.getsockname()
    
    def set_options(self, sock, bound=False):
        if hasattr(socket, "TCP_CORK"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_CORK, 1)
        elif hasattr(socket, "TCP_NOPUSH"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NOPUSH, 1)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return super(TCPSocket, self).set_options(sock, bound=bound)

class UnixSocket(BaseSocket):
    
    FAMILY = socket.AF_UNIX
    
    def __init__(self, conf, fd=None):
        if fd is None:
            try:
                os.remove(conf.address)
            except OSError:
                pass
        super(UnixSocket, self).__init__(conf, fd=fd)
    
    def __str__(self):
        return "unix:%s" % self.address
        
    def bind(self, sock):
        old_umask = os.umask(self.conf['umask'])
        sock.bind(self.address)
        util.chown(self.address, self.conf.uid, self.conf.gid)
        os.umask(old_umask)

def create_socket(conf):
    """
    Create a new socket for the given address. If the
    address is a tuple, a TCP socket is created. If it
    is a string, a Unix socket is created. Otherwise
    a TypeError is raised.
    """
    # get it only once
    addr = conf.address
    
    if isinstance(addr, tuple):
        sock_type = TCPSocket
    elif isinstance(addr, basestring):
        sock_type = UnixSocket
    else:
        raise TypeError("Unable to create socket from: %r" % addr)

    if 'GUNICORN_FD' in os.environ:
        fd = int(os.environ.pop('GUNICORN_FD'))
        try:
            return sock_type(conf, fd=fd)
        except socket.error, e:
            if e[0] == errno.ENOTCONN:
                log.error("GUNICORN_FD should refer to an open socket.")
            else:
                raise

    # If we fail to create a socket from GUNICORN_FD
    # we fall through and try and open the socket
    # normally.
    
    for i in range(5):
        try:
            return sock_type(conf)
        except socket.error, e:
            if e[0] == errno.EADDRINUSE:
                log.error("Connection in use: %s" % str(addr))
            if e[0] == errno.EADDRNOTAVAIL:
                log.error("Invalid address: %s" % str(addr))
                sys.exit(1)
            if i < 5:
                log.error("Retrying in 1 second.")
                time.sleep(1)
          
    log.error("Can't connect to %s" % str(addr))
    sys.exit(1)
