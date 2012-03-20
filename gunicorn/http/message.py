# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import re
import urlparse

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

from gunicorn.http.body import ChunkedReader, LengthReader, EOFReader, Body
from gunicorn.http.errors import InvalidHeader, InvalidHeaderName, NoMoreData, \
InvalidRequestLine, InvalidRequestMethod, InvalidHTTPVersion, \
LimitRequestLine, LimitRequestHeaders

MAX_REQUEST_LINE = 8190
MAX_HEADERS = 32768
MAX_HEADERFIELD_SIZE = 8190

class Message(object):
    def __init__(self, cfg, unreader):
        self.cfg = cfg
        self.unreader = unreader
        self.version = None
        self.headers = []
        self.trailers = []
        self.body = None

        self.hdrre = re.compile("[\x00-\x1F\x7F()<>@,;:\[\]={} \t\\\\\"]")

        # set headers limits
        self.limit_request_fields = max(cfg.limit_request_fields, MAX_HEADERS)
        if self.limit_request_fields <= 0:
            self.limit_request_fields = MAX_HEADERS
        self.limit_request_field_size = max(cfg.limit_request_field_size,
                MAX_HEADERFIELD_SIZE)
        if self.limit_request_field_size <= 0:
            self.limit_request_field_size = MAX_HEADERFIELD_SIZE

        # set max header buffer size
        self.max_buffer_headers = self.limit_request_fields * \
                (self.limit_request_field_size + 2) + 4

        unused = self.parse(self.unreader)
        self.unreader.unread(unused)
        self.set_body_reader()

    def parse(self):
        raise NotImplementedError()

    def parse_headers(self, data):
        headers = []

        # Split lines on \r\n keeping the \r\n on each line
        lines = [line + "\r\n" for line in data.split("\r\n")]

        # Parse headers into key/value pairs paying attention
        # to continuation lines.
        while len(lines):
            if len(headers) > self.limit_request_fields:
                raise LimitRequestHeaders("limit request headers fields")

            # Parse initial header name : value pair.
            curr = lines.pop(0)
            if curr.find(":") < 0:
                raise InvalidHeader(curr.strip())
            name, value = curr.split(":", 1)
            name = name.rstrip(" \t").upper()
            if self.hdrre.search(name):
                raise InvalidHeaderName(name)

            name, value = name.strip(), [value.lstrip()]

            # Consume value continuation lines
            while len(lines) and lines[0].startswith((" ", "\t")):
                value.append(lines.pop(0))
            value = ''.join(value).rstrip()

            headers.append((name, value))
        return headers

    def set_body_reader(self):
        chunked = False
        response_length = None
        for (name, value) in self.headers:
            if name == "CONTENT-LENGTH":
                try:
                    response_length = int(value)
                except ValueError:
                    response_length = None
            elif name == "TRANSFER-ENCODING":
                chunked = value.lower() == "chunked"
            elif name == "SEC-WEBSOCKET-KEY1":
                response_length = 8

            if response_length is not None or chunked:
                break

        if chunked:
            self.body = Body(ChunkedReader(self, self.unreader))
        elif response_length is not None:
            self.body = Body(LengthReader(self.unreader, response_length))
        else:
            self.body = Body(EOFReader(self.unreader))

    def should_close(self):
        for (h, v) in self.headers:
            if h == "CONNECTION":
                v = v.lower().strip()
                if v == "close":
                    return True
                elif v == "keep-alive":
                    return False
                break
        return self.version <= (1, 0)


class Request(Message):
    def __init__(self, cfg, unreader):
        self.methre = re.compile("[A-Z0-9$-_.]{3,20}")
        self.versre = re.compile("HTTP/(\d+).(\d+)")

        self.method = None
        self.uri = None
        self.path = None
        self.query = None
        self.fragment = None

        # get max request line size
        self.limit_request_line = max(cfg.limit_request_line,
                MAX_REQUEST_LINE)
        if self.limit_request_line <= 0:
            self.limit_request_line = MAX_REQUEST_LINE
        super(Request, self).__init__(cfg, unreader)


    def get_data(self, unreader, buf, stop=False):
        data = unreader.read()
        if not data:
            if stop:
                raise StopIteration()
            raise NoMoreData(buf.getvalue())
        buf.write(data)

    def parse(self, unreader):
        buf = StringIO()
        self.get_data(unreader, buf, stop=True)

        # Request line
        data = buf.getvalue()
        while True:
            idx = data.find("\r\n")
            if idx >= 0:
                break
            self.get_data(unreader, buf)
            data = buf.getvalue()

            if len(data) - 2 > self.limit_request_line:
                raise LimitRequestLine(len(data), self.cfg.limit_request_line)

        self.parse_request_line(data[:idx])
        buf = StringIO()
        buf.write(data[idx+2:]) # Skip \r\n

        # Headers
        data = buf.getvalue()
        idx = data.find("\r\n\r\n")

        done = data[:2] == "\r\n"
        while True:
            idx = data.find("\r\n\r\n")
            done = data[:2] == "\r\n"

            if idx < 0 and not done:
                self.get_data(unreader, buf)
                data = buf.getvalue()
                if len(data) > self.max_buffer_headers:
                    raise LimitRequestHeaders("max buffer headers")
            else:
                break

        if done:
            self.unreader.unread(data[2:])
            return ""

        self.headers = self.parse_headers(data[:idx])

        ret = data[idx+4:]
        buf = StringIO()
        return ret

    def parse_request_line(self, line):
        bits = line.split(None, 2)
        if len(bits) != 3:
            raise InvalidRequestLine(line)

        # Method
        if not self.methre.match(bits[0]):
            raise InvalidRequestMethod(bits[0])
        self.method = bits[0].upper()

        # URI
        # When the path starts with //, urlsplit considers it as a
        # relative uri while the RDF says it shouldnt
        # http://www.w3.org/Protocols/rfc2616/rfc2616-sec5.html#sec5.1.2
        # considers it as an absolute url.
        # fix issue #297
        if bits[1].startswith("//"):
            self.uri = bits[1][1:]
        else:
            self.uri = bits[1]

        parts = urlparse.urlsplit(self.uri)
        self.path = parts.path or ""
        self.query = parts.query or ""
        self.fragment = parts.fragment or ""

        # Version
        match = self.versre.match(bits[2])
        if match is None:
            raise InvalidHTTPVersion(bits[2])
        self.version = (int(match.group(1)), int(match.group(2)))

    def set_body_reader(self):
        super(Request, self).set_body_reader()
        if isinstance(self.body.reader, EOFReader):
            self.body = Body(LengthReader(self.unreader, 0))


