
import re

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

from errors import *

class ChunkedReader(object):
    def __init__(self, req, unreader):
        self.req = req
        self.parser = self.parse_chunked(unreader)
        self.buf = StringIO()
    
    def read(self, size=None):
        if size == 0:
            return ""
        if size < 0:
            size = None

        if not self.parser:
            return self.buf.getvalue()

        while size is None or self.buf.tell() < size:
            try:
                self.buf.write(self.parser.next())
            except StopIteration:
                self.parser = None
                break

        if size is None or self.buf.tell() < size:
            ret = self.buf.getvalue()
            self.buf.truncate(0)
            return ret
        
        data = self.buf.getvalue()
        ret, rest = data[:size], data[size:]
        self.buf.truncate(0)
        self.buf.write(rest)
        return ret
    
    def parse_trailers(self, unreader, data):
        buf = StringIO()
        buf.write(data)
        
        idx = buf.getvalue().find("\r\n\r\n")
        done = buf.getvalue()[:2] == "\r\n"
        while idx < 0 and not done:
            self.get_data(unreader, buf)
            idx = buf.getvalue().find("\r\n\r\n")
            done = buf.getvalue()[:2] == "\r\n"
        if done:
            unreader.unread(buf.getvalue()[2:])
            return ""
        self.req.trailers = self.req.parse_headers(buf.getvalue()[:idx])
        unreader.unread(buf.getvalue()[idx+4:])

    def parse_chunked(self, unreader):
        (size, rest) = self.parse_chunk_size(unreader)
        while size > 0:
            while size > len(rest):
                size -= len(rest)
                yield rest
                rest = unreader.read()
                if not rest:
                    raise NoMoreData()
            yield rest[:size]
            # Remove \r\n after chunk
            rest = rest[size:]
            while len(rest) < 2:
                rest += unreader.read()
            if rest[:2] != '\r\n':
                raise ChunkMissingTerminator(rest[:2])
            (size, rest) = self.parse_chunk_size(unreader, data=rest[2:])          

    def parse_chunk_size(self, unreader, data=None):
        buf = StringIO()
        if data is not None:
            buf.write(data)

        idx = buf.getvalue().find("\r\n")
        while idx < 0:
            self.get_data(unreader, buf)
            idx = buf.getvalue().find("\r\n")

        data = buf.getvalue()
        line, rest_chunk = data[:idx], data[idx+2:]
    
        chunk_size = line.split(";", 1)[0].strip()
        try:
            chunk_size = int(chunk_size, 16)
        except ValueError:
            raise InvalidChunkSize(chunk_size)

        if chunk_size == 0:
            self.parse_trailers(unreader, rest_chunk)
            return (0, None)
        return (chunk_size, rest_chunk)

    def get_data(self, unreader, buf):
        data = unreader.read()
        if not data:
            raise NoMoreData()
        buf.write(data)

class LengthReader(object):
    def __init__(self, unreader, length):
        self.unreader = unreader
        self.length = length
    
    def read(self, size=None):
        if size is not None and not isinstance(size, (int, long)):
            raise TypeError("size must be an integral type")

        if size == 0 or self.length <= 0:
            return ""
        if size < 0 or size is None:
            size = self.length
        
        buf = StringIO()
        data = self.unreader.read()
        while data:
            buf.write(data)
            if buf.tell() >= size:
                break
            data = self.unreader.read()
        
        buf = buf.getvalue()
        ret, rest = buf[:size], buf[size:]
        self.unreader.unread(rest)
        self.length -= size
        return ret

class EOFReader(object):
    def __init__(self, unreader):
        self.unreader = unreader
        self.buf = StringIO()
        self.finished = False
    
    def read(self, size=None):
        if size == 0 or self.finished:
            return ""
        if size < 0:
            size = None
        
        data = self.unreader.read()
        while data:
            buf.write(data)
            if size is not None and buf.tell() > size:
                data = buf.getvalue()
                ret, rest = data[:size], data[size:]
                self.buf.truncate(0)
                self.buf.write(rest)
                return ret
            data = self.unreader.read()

        self.finished = True
        ret = self.buf.getvalue()
        self.buf.truncate(0)
        return ret

class Body(object):
    def __init__(self, reader):
        self.reader = reader
        self.buf = StringIO()
    
    def __iter__(self):
        return self
    
    def next(self):
        ret = self.readline()
        if not ret:
            raise StopIteration()
        return ret
    
    def read(self, size=None):
        if size is not None and not isinstance(size, (int, long)):
            raise TypeError("size must be an integral type")

        if size is not None and size < self.buf.tell():
            data = self.buf.getvalue()
            ret, rest = data[:size], data[size:]
            self.buf.truncate(0)
            self.buf.write(rest)
            return ret

        if size > 0:
            size -= self.buf.tell()
        else:
            size = None
        
        ret = self.buf.getvalue() + self.reader.read(size=size)
        self.buf.truncate(0)
        return ret
    
    def readline(self, size=None):
        if size == 0:
            return ""
        if size < 0:
            size = None
        
        idx = -1
        while idx < 0:
            data = self.reader.read(1024)
            if not len(data):
                break
            self.buf.write(data)
            if size is not None and self.buf.tell() > size:
                break
            idx = self.buf.getvalue().find("\r\n")

        if idx < 0 and size is not None:
            idx = size
        elif idx < 0:
            idx = self.buf.tell()
        
        data = self.buf.getvalue()
        ret, rest = data[:idx], data[idx:]
        self.buf.truncate(0)
        self.buf.write(rest)
        return ret
    
    def readlines(self, size=None):
        ret = []
        data = self.read()
        while len(data):
            pos = data.find("\n")
            if pos < 0:
                ret.append(data)
                data = ""
            else:
                line, data = data[:pos+1], data[pos+1:]
                ret.append(line)
        return ret

