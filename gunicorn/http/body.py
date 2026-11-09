#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import io
import re
import sys

from gunicorn.http.errors import (NoMoreData, ChunkMissingTerminator,
                                  InvalidChunkSize, InvalidChunkExtension,
                                  InvalidHeader, LimitRequestHeaders)

# RFC 9112 section 7.1.1, everything from the first ";" of a chunk size line:
#   chunk-ext = *( BWS ";" BWS chunk-ext-name [ BWS "=" BWS chunk-ext-val ] )
#   chunk-ext-name = token; chunk-ext-val = token / quoted-string
# with token and quoted-string from RFC 9110 section 5.6.2 and 5.6.4.
_TOKEN = rb"[!#$%&'*+\-.^_`|~0-9A-Za-z]+"
_QUOTED_STRING = rb'"(?:[\t !#-\[\]-~\x80-\xff]|\\[\t -~\x80-\xff])*"'
CHUNK_EXT_RE = re.compile(
    rb"(?:[ \t]*;[ \t]*" + _TOKEN
    + rb"(?:[ \t]*=[ \t]*(?:" + _TOKEN + rb"|" + _QUOTED_STRING + rb"))?)*")

#: Largest piece Body.read() asks its reader for in one call.
MAX_READ_STEP = 1024 * 1024

#: Fallbacks when the request carries no header limits of its own.
DEFAULT_MAX_CHUNK_SIZE_LINE = 8190
DEFAULT_MAX_TRAILER_SECTION = 8190 * 32


class ChunkedReader:
    def __init__(self, req, unreader):
        self.req = req
        self.parser = self.parse_chunked(unreader)
        self.buf = io.BytesIO()
        # A chunk-size line is a few hex digits plus optional extensions, and
        # a trailer section is a header block. Both are read a socket buffer
        # at a time while looking for their terminator, so both need a bound:
        # without one a peer can make a worker read and scan for as long as it
        # cares to send, and the request never reaches the application.
        self.limit_chunk_size_line = getattr(
            req, "limit_request_field_size", 0) or DEFAULT_MAX_CHUNK_SIZE_LINE
        self.limit_trailer_section = getattr(
            req, "max_buffer_headers", 0) or DEFAULT_MAX_TRAILER_SECTION

    def read(self, size):
        if not isinstance(size, int):
            raise TypeError("size must be an integer type")
        if size < 0:
            raise ValueError("Size must be positive.")
        if size == 0:
            return b""

        if self.parser:
            while self.buf.tell() < size:
                try:
                    self.buf.write(next(self.parser))
                except StopIteration:
                    self.parser = None
                    break

        data = self.buf.getvalue()
        ret, rest = data[:size], data[size:]
        self.buf = io.BytesIO()
        self.buf.write(rest)
        return ret

    def parse_trailers(self, unreader, data):
        buf = bytearray(data)

        idx = buf.find(b"\r\n\r\n")
        done = buf[:2] == b"\r\n"
        while idx < 0 and not done:
            if len(buf) > self.limit_trailer_section:
                raise LimitRequestHeaders("limit request trailer section size")
            # RFC 9112 section 2.2: trailer lines end with CRLF too.
            if buf.count(b"\n") != buf.count(b"\r\n"):
                raise InvalidHeader("bare LF as line terminator")
            # Only the last three bytes can start a terminator that the next
            # read completes, so the scan resumes there instead of running
            # over the whole buffer again.
            searched = max(0, len(buf) - 3)
            try:
                self.read_into(unreader, buf)
            except NoMoreData:
                # RFC 9112 7.1.2: the last chunk (0 CRLF) must be followed by
                # a CRLF-terminated trailer section. Hitting EOF before that
                # means the chunked body was truncated, not cleanly ended.
                raise ChunkMissingTerminator(b"") from None
            idx = buf.find(b"\r\n\r\n", searched)
            done = buf[:2] == b"\r\n"
        if done:
            unreader.unread(bytes(buf[2:]))
            return b""
        # Hand back what follows the trailers before checking them, so a bad
        # trailer does not also lose bytes read ahead from the socket.
        unreader.unread(bytes(buf[idx + 4:]))
        self.req.trailers = self.req.parse_headers(bytes(buf[:idx]), from_trailer=True)

    def parse_chunked(self, unreader):
        (size, rest) = self.parse_chunk_size(unreader)
        while size > 0:
            while size > len(rest):
                size -= len(rest)
                yield rest
                # The chunk header said how many bytes follow: let the socket
                # read up to that much at once instead of 8 KiB per recv().
                # Never more, so a read does not cross the end of the chunk.
                rest = unreader.read(None, read_ahead=size)
                if not rest:
                    raise NoMoreData()
            yield rest[:size]
            # Remove \r\n after chunk
            rest = rest[size:]
            while len(rest) < 2:
                new_data = unreader.read()
                if not new_data:
                    break
                rest += new_data
            if rest[:2] != b'\r\n':
                raise ChunkMissingTerminator(rest[:2])
            (size, rest) = self.parse_chunk_size(unreader, data=rest[2:])

    def parse_chunk_size(self, unreader, data=None):
        buf = bytearray(data) if data else bytearray()

        idx = buf.find(b"\r\n")
        while idx < 0:
            if len(buf) > self.limit_chunk_size_line:
                raise InvalidChunkSize(
                    b"line over %d bytes with no terminator" % self.limit_chunk_size_line)
            # Only the last byte can start a terminator that the next read
            # completes, so the scan resumes there instead of running over
            # the whole buffer again.
            searched = max(0, len(buf) - 1)
            self.read_into(unreader, buf)
            idx = buf.find(b"\r\n", searched)

        line, rest_chunk = bytes(buf[:idx]), bytes(buf[idx + 2:])

        # RFC9112 7.1.1: BWS before chunk-ext - but ONLY then
        chunk_size, *chunk_ext = line.split(b";", 1)
        if chunk_ext:
            # RFC 9112: chunk-ext must not contain bare CR
            if b'\r' in chunk_ext[0]:
                raise InvalidChunkExtension("bare CR not allowed")
            chunk_size = chunk_size.rstrip(b" \t")
        if any(n not in b"0123456789abcdefABCDEF" for n in chunk_size):
            raise InvalidChunkSize(chunk_size)
        if len(chunk_size) == 0:
            raise InvalidChunkSize(chunk_size)
        # The size first, so a bad size is reported as such.
        if chunk_ext and not CHUNK_EXT_RE.fullmatch(b";" + chunk_ext[0]):
            raise InvalidChunkExtension("invalid chunk extension")
        chunk_size = int(chunk_size, 16)

        if chunk_size == 0:
            self.parse_trailers(unreader, rest_chunk)
            return (0, None)
        return (chunk_size, rest_chunk)

    def get_data(self, unreader, buf):
        data = unreader.read()
        if not data:
            raise NoMoreData()
        buf.write(data)

    def read_into(self, unreader, buf):
        """Append one socket read to a bytearray, without copying it."""
        data = unreader.read()
        if not data:
            raise NoMoreData()
        buf += data


class LengthReader:
    def __init__(self, unreader, length):
        self.unreader = unreader
        self.length = length

    def read(self, size):
        if not isinstance(size, int):
            raise TypeError("size must be an integral type")

        size = min(self.length, size)
        if size < 0:
            raise ValueError("Size must be positive.")
        if size == 0:
            return b""

        # The unreader reads until it holds `size` bytes and keeps anything
        # beyond for later. It may read ahead up to the end of the body, so an
        # application reading 64 KiB at a time still gets large recv() calls.
        ret = self.unreader.read(size, read_ahead=self.length)
        self.length -= size
        return ret


class EOFReader:
    def __init__(self, unreader):
        self.unreader = unreader
        self.buf = io.BytesIO()
        self.finished = False

    def read(self, size):
        if not isinstance(size, int):
            raise TypeError("size must be an integral type")
        if size < 0:
            raise ValueError("Size must be positive.")
        if size == 0:
            return b""

        if self.finished:
            data = self.buf.getvalue()
            ret, rest = data[:size], data[size:]
            self.buf = io.BytesIO()
            self.buf.write(rest)
            return ret

        data = self.unreader.read()
        while data:
            self.buf.write(data)
            if self.buf.tell() > size:
                break
            data = self.unreader.read()

        if not data:
            self.finished = True

        data = self.buf.getvalue()
        ret, rest = data[:size], data[size:]
        self.buf = io.BytesIO()
        self.buf.write(rest)
        return ret


class Body:
    def __init__(self, reader):
        self.reader = reader
        self.buf = io.BytesIO()
        # Set when reading the body raised: where the next request starts on
        # the connection is then unknown, so it must not be reused.
        self.failed = False

    def _read_reader(self, size):
        try:
            return self.reader.read(size)
        except Exception:
            self.failed = True
            raise

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

        # Ask the reader for what is still missing, in steps of at most
        # MAX_READ_STEP (and at least 1 KiB, the read-ahead small reads always
        # had). Asking for 1 KiB made LengthReader push the rest of each
        # received chunk back with unread(), copying it again on every turn of
        # this loop; the upper bound keeps the readers' own buffers small when
        # the application reads a large body in one call.
        while size > self.buf.tell():
            step = min(max(1024, size - self.buf.tell()), MAX_READ_STEP)
            data = self._read_reader(step)
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
            data = self._read_reader(min(1024, size))
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
