# -*- coding: utf-8 -
#
# This file is part of gunicorn
# See the NOTICE for more information.

# Copyright (C) 2016  Christian Heimes under Apache License 2

# source code based on https://github.com/tiran/socketfromfd/blob/master/socketfromfd.py
# and https://github.com/python/cpython/blob/master/Modules/socketmodule.c

"""socketfromfd -- create a socket from its file descriptor
This module detect the socket properties.

note: Before python 3.7 auto detecting the socket was not working.
See  https://bugs.python.org/issue28134 for details.
"""

from __future__ import print_function

import ctypes
import os
import socket
import sys
import platform

from .util import find_library

__all__ = ('fromfd',)

_libc_name = find_library('c')
if _libc_name is not None:
    if sys.platform.startswith("aix"):
        member = (
            '(shr_64.o)' if ctypes.sizeof(ctypes.c_voidp) == 8 else '(shr.o)')
        # 0x00040000 correspondes to RTLD_MEMBER, undefined in Python <= 3.6
        dlopen_mode = (ctypes.DEFAULT_MODE | 0x00040000 | os.RTLD_NOW)
        libc = ctypes.CDLL(_libc_name+member,
                           use_errno=True,
                           mode=dlopen_mode)
    else:
        libc = ctypes.CDLL(_libc_name, use_errno=True)
else:
    raise OSError('libc not found')


def _errcheck_errno(result, func, arguments):
    """Raise OSError by errno for -1
    """
    if result == -1:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno))
    return arguments


if platform.system() == 'SunOS':
    _libc_getsockopt = libc._so_getsockopt
    _lib_getsockname = libc._so_getsockname
else:
    _libc_getsockopt = libc.getsockopt
    _libc_getsockname = libc.getsockname


_libc_getsockopt.argtypes = [
    ctypes.c_int,  # int sockfd
    ctypes.c_int,  # int level
    ctypes.c_int,  # int optname
    ctypes.c_void_p,  # void *optval
    ctypes.POINTER(ctypes.c_uint32)  # socklen_t *optlen
]
_libc_getsockopt.restype = ctypes.c_int  # 0: ok, -1: err
_libc_getsockopt.errcheck = _errcheck_errno

class SockAddr(ctypes.Structure):
    _fields_ = [
        ('sa_len', ctypes.c_uint8),
        ('sa_family', ctypes.c_uint8),
        ('sa_data', ctypes.c_char * 14)
    ]


_libc_getsockname.argtypes = [
    ctypes.c_int,
    ctypes.POINTER(SockAddr),
    ctypes.POINTER(ctypes.c_int)
]
_libc_getsockname.restype = ctypes.c_int  # 0: ok, -1: err
_libc_getsockname.errcheck = _errcheck_errno

def _getsockopt(fd, level, optname):
    """Make raw getsockopt() call for int32 optval

    :param fd: socket fd
    :param level: SOL_*
    :param optname: SO_*
    :return: value as int
    """
    optval = ctypes.c_int(0)
    optlen = ctypes.c_uint32(4)
    _libc_getsockopt(fd, level, optname,
                     ctypes.byref(optval), ctypes.byref(optlen))
    return optval.value

def _getsockname(fd):
    sockaddr = SockAddr()
    sockaddrlen = ctypes.c_int(ctypes.sizeof(sockaddr))
    _libc_getsockname(fd, sockaddr, sockaddrlen)
    return sockaddr

def fromfd(fd, keep_fd=True):
    """Create a socket from a file descriptor

    socket domain (family), type and protocol are auto-detected. By default
    the socket uses a dup()ed fd. The original fd can be closed.

    The parameter `keep_fd` influences fd duplication. Under Python 2 the
    fd is still duplicated but the input fd is closed. Under Python 3 and
    with `keep_fd=True`, the new socket object uses the same fd.

    :param fd: socket fd
    :type fd: int
    :param keep_fd: keep input fd
    :type keep_fd: bool
    :return: socket.socket instance
    :raises OSError: for invalid socket fd
    """
    sockaddr = _getsockname(fd)
    family = sockaddr.sa_family
    if hasattr(socket, 'SO_TYPE'):
        typ = _getsockopt(fd, socket.SOL_SOCKET, getattr(socket, 'SO_TYPE'))
    else:
        typ = socket.SOCK_STREAM

    if hasattr(socket, 'SO_PROTOCOL'):
        proto = _getsockopt(fd, socket.SOL_SOCKET, getattr(socket, 'SO_PROTOCOL'))
    else:
        proto = 0
    if keep_fd:
        return socket.fromfd(fd, family, typ, proto)
    else:
        return socket.socket(family, typ, proto, fileno=fd)
