#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import io
import os

# Classes that can undo reading data from
# a given type of data source.


class Unreader:
    def __init__(self):
        self.buf = io.BytesIO()

    def chunk(self, size_hint=None):
        """Return the next piece of data from the source.

        ``size_hint`` is how many bytes the caller still wants; sources may
        use it to read more at once, never to read past what they hold.
        """
        raise NotImplementedError()

    def take_buffered(self):
        """Return read-ahead already held, without touching the source.

        read() blocks on the source when the buffer is empty, which is wrong
        for a caller that only wants the bytes it has: an Upgrade: h2c
        handshake needs whatever the client pipelined behind the request,
        and must not wait for more.
        """
        data = self.buf.getvalue()
        self.buf = io.BytesIO()
        return data

    def read(self, size=None, read_ahead=None):
        """Read `size` bytes (or the next chunk if None).

        ``read_ahead`` is how many bytes the caller may consume in total from
        here, e.g. what is left of a request body of known length: the source
        may then be asked for up to that much at once, the surplus staying
        buffered. It is never a reason to read past the end of the body.
        """
        if size is not None and not isinstance(size, int):
            raise TypeError("size parameter must be an int or long.")

        if size is not None:
            if size == 0:
                return b""
            if size < 0:
                size = None

        self.buf.seek(0, os.SEEK_END)

        if size is None and self.buf.tell():
            ret = self.buf.getvalue()
            self.buf = io.BytesIO()
            return ret
        if size is None:
            d = self.chunk()
            return d

        while self.buf.tell() < size:
            chunk = self.chunk(max(size, read_ahead or 0) - self.buf.tell())
            if not chunk:
                ret = self.buf.getvalue()
                self.buf = io.BytesIO()
                return ret
            self.buf.write(chunk)
        data = self.buf.getvalue()
        self.buf = io.BytesIO()
        self.buf.write(data[size:])
        return data[:size]

    def unread(self, data):
        rest = self.buf.getvalue()
        self.buf = io.BytesIO()
        self.buf.write(data)
        self.buf.write(rest)


class SocketUnreader(Unreader):
    #: Largest single recv() when the caller says how much it still wants (a
    #: request body of known length). Every recv() releases and re-acquires the
    #: GIL; with CPU-bound threads in the same process, re-acquiring it can take
    #: up to sys.getswitchinterval() (5 ms), so a body read 8 KiB at a time was
    #: slowed down to a few MiB/s.
    max_body_chunk = 1024 * 1024

    def __init__(self, sock, max_chunk=8192):
        super().__init__()
        self.sock = sock
        self.mxchunk = max_chunk

    def chunk(self, size_hint=None):
        size = self.mxchunk
        if size_hint and size_hint > size:
            size = min(size_hint, self.max_body_chunk)
        return self.sock.recv(size)


class IterUnreader(Unreader):
    def __init__(self, iterable):
        super().__init__()
        self.iter = iter(iterable)

    def chunk(self, size_hint=None):
        if not self.iter:
            return b""
        try:
            return next(self.iter)
        except StopIteration:
            self.iter = None
            return b""
