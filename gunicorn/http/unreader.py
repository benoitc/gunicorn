# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import os

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

# Classes that can undo reading data from
# a given type of data source.

class Unreader(object):
    def __init__(self):
        self.buf = StringIO()

    def chunk(self):
        raise NotImplementedError()

    def read(self, size=None):
        if size is not None and not isinstance(size, (int, long)):
            raise TypeError("size parameter must be an int or long.")
        if size == 0:
            return ""
        if size < 0:
            size = None

        self.buf.seek(0, os.SEEK_END)

        if size is None and self.buf.tell():
            ret = self.buf.getvalue()
            self.buf.truncate(0)
            return ret
        if size is None:
            return self.chunk()

        while self.buf.tell() < size:
            chunk = self.chunk()
            if not len(chunk):
                ret = self.buf.getvalue()
                self.buf.truncate(0)
                return ret
            self.buf.write(chunk)
        data = self.buf.getvalue()
        self.buf.truncate(0)
        self.buf.write(data[size:])
        return data[:size]

    def unread(self, data):
        self.buf.seek(0, os.SEEK_END)
        self.buf.write(data)

class SocketUnreader(Unreader):
    def __init__(self, sock, max_chunk=8192):
        super(SocketUnreader, self).__init__()
        self.sock = sock
        self.mxchunk = max_chunk

    def chunk(self):
        return self.sock.recv(self.mxchunk)

class IterUnreader(Unreader):
    def __init__(self, iterable):
        super(IterUnreader, self).__init__()
        self.iter = iter(iterable)

    def chunk(self):
        if not self.iter:
            return ""
        try:
            return self.iter.next()
        except StopIteration:
            self.iter = None
            return ""
