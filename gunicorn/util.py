# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license. 
# See the NOTICE for more information.

import errno
import select
import socket
import time

timeout_default = object()

CHUNK_SIZE = (16 * 1024)

MAX_BODY = 1024 * (80 + 32)

weekdayname = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

monthname = [None,
             'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
             'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  
  
def close(sock):
    """ socket.close() doesn't *really* close if 
    there's another reference to it in the TCP/IP stack. 
    (trick from twisted)"""
    try:
        sock.shutdown(2)
    except socket.error:
        pass
    try:
        sock.close()
    except socket.error:
        pass
  
def read_partial(sock, length):
    while True:
        try:
            ret = select.select([sock.fileno()], [], [])
            if ret[0]: break
        except select.error, e:
            if e[0] == errno.EINTR:
                break
            raise
    data = sock.recv(length)
    return data
    
def write(sock, data):
    buf = ""
    buf += data
    while buf:
        try:
            bytes = sock.send(buf)
            if bytes < len(buf):
                buf = buf[bytes:]
                continue
            return len(data)
        except socket.error, e:
            if e[0] in (errno.EWOULDBLOCK, errno.EAGAIN):
                break
            elif e[0] in (errno.EPIPE,):
                continue
            raise
                
def write_nonblock(sock, data):
    while True:
        try:
            ret = select.select([], [sock.fileno()], [], 2.0)
            if ret[1]: break
        except socket.error, e:
            if e[0] == errno.EINTR:
                break
            raise
    write(sock, data)

def import_app(module):
    parts = module.rsplit(":", 1)
    if len(parts) == 1:
        module, obj = module, "application"
    else:
        module, obj = parts[0], parts[1]
    mod = __import__(module)
    parts = module.split(".")
    for p in parts[1:]:
        mod = getattr(mod, p, None)
        if mod is None:
            raise ImportError("Failed to import: %s" % module)
    app = getattr(mod, obj, None)
    if app is None:
        raise ImportError("Failed to find application object: %r" % obj)
    if not callable(app):
        raise TypeError("Application object must be callable.")
    return app
    
    
def http_date(timestamp=None):
    """Return the current date and time formatted for a message header."""
    if timestamp is None:
        timestamp = time.time()
    year, month, day, hh, mm, ss, wd, y, z = time.gmtime(timestamp)
    s = "%s, %02d %3s %4d %02d:%02d:%02d GMT" % (
            weekdayname[wd],
            day, monthname[month], year,
            hh, mm, ss)
    return s
