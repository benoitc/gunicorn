# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import ctypes
import ctypes.util
import errno
import os
import sys

if sys.version_info >= (2, 6):
    _libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    _sendfile = _libc.sendfile
else:
    _sendfile = None

if _sendfile:
    if sys.platform == 'darwin':
        # MacOS X - int sendfile(int fd, int s, off_t offset, off_t *len,
        #                    struct sf_hdtr *hdtr, int flags);

        _sendfile.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                              ctypes.POINTER(ctypes.c_uint64), ctypes.c_voidp,
                              ctypes.c_int]

        def sendfile(fileno, sockno, offset, nbytes):
            _nbytes = ctypes.c_uint64(nbytes)
            result = _sendfile(fileno, sockno, offset, _nbytes, None, 0)
            if result == -1:
                e = ctypes.get_errno()
                if e == errno.EAGAIN and _nbytes.value:
                    return _nbytes.value
                raise OSError(e, os.strerror(e))
            return _nbytes.value

    elif sys.platform == 'linux2':
        # Linux - size_t sendfile(int out_fd, int in_fd, off_t *offset,
        #                         size_t count);

        _sendfile.argtypes = [ctypes.c_int, ctypes.c_int,
                              ctypes.POINTER(ctypes.c_uint64), ctypes.c_size_t]

        def sendfile(fileno, sockno, offset, nbytes):
            _offset = ctypes.c_uint64(offset)
            result = _sendfile(sockno, fileno, _offset, nbytes)
            if result == -1:
                e = ctypes.get_errno()
                raise OSError(e, os.strerror(e))
            return result

    else:
        sendfile = None
else:
  sendfile = None
