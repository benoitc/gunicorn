# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import io
import sys

from gunicorn.http.unreader import IterUnreader
from gunicorn.http.errors import (NoMoreData, ChunkMissingTerminator,
                                  InvalidChunkSize)


class ChunkedReader(object):
    def __init__(self, req, unreader):
        self.req = req
        self.source = IterUnreader(self.parse_chunked())
        self.unreader = unreader

    def read(self, size):
        if not isinstance(size, int):
            raise TypeError("size must be an integral type")
        if size < 0:
            raise ValueError("Size must be positive.")
        return self.source.read(size)

    def parse_trailers(self):
        current_line = self.unreader.readline()
        if not current_line:
            raise NoMoreData()
        if current_line[:2] == b'\r\n':
            return b''
        buf = io.BytesIO()
        while True:
            buf.write(current_line)
            next_line = self.unreader.readline()
            if not next_line:
                raise NoMoreData()
            if current_line.endswith(b'\r\n') and next_line == b'\r\n':
                break
            current_line = next_line
        self.req.trailers = self.req.parse_headers(buf.getvalue()[:-2])

    def parse_chunked(self):
        size = self.parse_chunk_size()
        while size > 0:
            chunk = self.unreader.read(size)
            if len(chunk) < size:
                raise NoMoreData()
            yield chunk
            crlf = self.unreader.read(2)
            if crlf != b'\r\n':
                raise ChunkMissingTerminator(crlf)
            size = self.parse_chunk_size()

    def parse_chunk_size(self):
        line = self.unreader.readline()
        if not line or not line.endswith(b'\r\n'):
            raise NoMoreData()
        chunk_size = line.split(b";", 1)[0].strip()
        try:
            chunk_size = int(chunk_size, 16)
        except ValueError:
            raise InvalidChunkSize(chunk_size)
        if chunk_size == 0:
            try:
                self.parse_trailers()
            except NoMoreData:
                pass
            return 0
        return chunk_size


class LengthReader(object):
    def __init__(self, unreader, length):
        self.unreader = unreader
        self.length = length

    def read(self, size):
        if not isinstance(size, int):
            raise TypeError("size must be an integral type")

        size = min(self.length, size)
        if size < 0:
            raise ValueError("Size must be positive.")

        ret = self.unreader.read(size)
        self.length -= len(ret)
        return ret


class EOFReader(object):
    def __init__(self, unreader):
        self.unreader = unreader
        self.finished = False

    def read(self, size):
        if not isinstance(size, int):
            raise TypeError("size must be an integral type")
        if size < 0:
            raise ValueError("Size must be positive.")

        if self.finished:
            return self.unreader.read()
        ret = self.unreader.read(size)
        if not ret and size != 0:
            self.finished = True
        return ret


class Body(object):
    def __init__(self, reader):
        self.reader = reader
        self.buf = io.BytesIO()

    def __iter__(self):
        return self

    def __next__(self):
        ret = self.readline()
        if not ret:
            raise StopIteration()
        return ret

    next = __next__

    def getsize(self, size):
        if size is None:
            return sys.maxsize
        elif not isinstance(size, int):
            raise TypeError("size must be an integral type")
        elif size < 0:
            return sys.maxsize
        return size

    def read(self, size=None):
        size = self.getsize(size)
        if size == 0:
            return b""

        if size < self.buf.tell():
            data = self.buf.getvalue()
            ret, rest = data[:size], data[size:]
            self.buf = io.BytesIO()
            self.buf.write(rest)
            return ret

        while size > self.buf.tell():
            data = self.reader.read(1024)
            if not data:
                break
            self.buf.write(data)

        data = self.buf.getvalue()
        ret, rest = data[:size], data[size:]
        self.buf = io.BytesIO()
        self.buf.write(rest)
        return ret

    def readline(self, size=None):
        size = self.getsize(size)
        if size == 0:
            return b""

        data = self.buf.getvalue()
        self.buf = io.BytesIO()

        ret = []
        while 1:
            idx = data.find(b"\n", 0, size)
            idx = idx + 1 if idx >= 0 else size if len(data) >= size else 0
            if idx:
                ret.append(data[:idx])
                self.buf.write(data[idx:])
                break

            ret.append(data)
            size -= len(data)
            data = self.reader.read(min(1024, size))
            if not data:
                break

        return b"".join(ret)

    def readlines(self, size=None):
        ret = []
        data = self.read()
        while data:
            pos = data.find(b"\n")
            if pos < 0:
                ret.append(data)
                data = b""
            else:
                line, data = data[:pos + 1], data[pos + 1:]
                ret.append(line)
        return ret
