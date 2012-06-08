# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import re
import urlparse
from socket import inet_pton, AF_INET, AF_INET6
import socket
from errno import ENOTCONN

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

from gunicorn.http.unreader import SocketUnreader
from gunicorn.http.body import ChunkedReader, LengthReader, EOFReader, Body
from gunicorn.http.errors import InvalidHeader, InvalidHeaderName, NoMoreData, \
InvalidRequestLine, InvalidRequestMethod, InvalidHTTPVersion, \
LimitRequestLine, LimitRequestHeaders, InvalidProxyLine, ForbiddenProxyRequest

MAX_REQUEST_LINE = 8190
MAX_HEADERS = 32768
MAX_HEADERFIELD_SIZE = 8190

class Message(object):
    def __init__(self, cfg, unreader, parser=None):
        self.cfg = cfg
        self.unreader = unreader
        self.version = None
        self.headers = []
        self.trailers = []
        self.body = None
        self.parser = parser

        self.hdrre = re.compile("[\x00-\x1F\x7F()<>@,;:\[\]={} \t\\\\\"]")

        # set headers limits
        self.limit_request_fields = cfg.limit_request_fields
        if (self.limit_request_fields <= 0
            or self.limit_request_fields > MAX_HEADERS):
            self.limit_request_fields = MAX_HEADERS
        self.limit_request_field_size = cfg.limit_request_field_size
        if (self.limit_request_field_size < 0
            or self.limit_request_field_size > MAX_HEADERFIELD_SIZE):
            self.limit_request_field_size = MAX_HEADERFIELD_SIZE

        # set max header buffer size
        max_header_field_size = self.limit_request_field_size or MAX_HEADERFIELD_SIZE
        self.max_buffer_headers = self.limit_request_fields * \
            (max_header_field_size + 2) + 4

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
            if len(headers) >= self.limit_request_fields:
                raise LimitRequestHeaders("limit request headers fields")

            # Parse initial header name : value pair.
            curr = lines.pop(0)
            header_length = len(curr)
            if curr.find(":") < 0:
                raise InvalidHeader(curr.strip())
            name, value = curr.split(":", 1)
            name = name.rstrip(" \t").upper()
            if self.hdrre.search(name):
                raise InvalidHeaderName(name)

            name, value = name.strip(), [value.lstrip()]

            # Consume value continuation lines
            while len(lines) and lines[0].startswith((" ", "\t")):
                curr = lines.pop(0)
                header_length += len(curr)
                if header_length > self.limit_request_field_size > 0:
                    raise LimitRequestHeaders("limit request headers "
                            + "fields size")
                value.append(curr)
            value = ''.join(value).rstrip()

            if header_length > self.limit_request_field_size > 0:
                raise LimitRequestHeaders("limit request headers fields size")
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
    def __init__(self, cfg, unreader, parser):
        self.methre = re.compile("[A-Z0-9$-_.]{3,20}")
        self.versre = re.compile("HTTP/(\d+).(\d+)")

        self.method = None
        self.uri = None
        self.path = None
        self.query = None
        self.fragment = None

        # get max request line size
        self.limit_request_line = cfg.limit_request_line
        if (self.limit_request_line < 0
            or self.limit_request_line >= MAX_REQUEST_LINE):
            self.limit_request_line = MAX_REQUEST_LINE
        super(Request, self).__init__(cfg, unreader, parser)

    def get_data(self, unreader, buf, stop=False):
        data = unreader.read()
        if not data:
            if stop:
                raise StopIteration()
            raise NoMoreData(buf.getvalue())
        buf.write(data)

    def _read_request_line(self, unreader, buf):
        data = buf.getvalue()
        while True:
            idx = data.find("\r\n")
            if idx >= 0:
                break
            self.get_data(unreader, buf)
            data = buf.getvalue()

            if len(data) - 2 > self.limit_request_line > 0:
                raise LimitRequestLine(len(data), self.limit_request_line)

        return (data[:idx], # request line
                data[idx + 2:]) #  residue in the buffer, skip \r\n

    def parse(self, unreader):
        buf = StringIO()
        self.get_data(unreader, buf, stop=True)

        # Request line
        line, rbuf = self._read_request_line(unreader, buf)

        # check proxy protocol
        if self.cfg.autoproxy and self.parser.req_count == 1 \
            and line.startswith("PROXY"):

            # check for allow list
            if isinstance(self.unreader, SocketUnreader):
                try:
                    remote_host = self.unreader.sock.getpeername()[0]
                except socket.error as e:
                    if e[0] == ENOTCONN:
                        raise ForbiddenProxyRequest("host disconnected")
                    raise

                if remote_host not in self.cfg.proxy_hosts.split():
                    raise ForbiddenProxyRequest(remote_host)

            self.parse_proxy_protocol(line)
            buf = StringIO()
            buf.write(rbuf)
            line, rbuf = self._read_request_line(unreader, buf)

        self.parse_request_line(line)
        buf = StringIO()
        buf.write(rbuf)

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

        ret = data[idx + 4:]
        buf = StringIO()
        return ret

    def parse_proxy_protocol(self, line):
        bits = line.split()

        if len(bits) != 6:
            raise InvalidProxyLine(line)

        # Extract data
        proto = bits[1]
        s_addr = bits[2]
        d_addr = bits[3]
        try:
            s_port = int(bits[4])
            d_port = int(bits[5])
        except ValueError:
            raise InvalidProxyLine(line)

        # Validation
        if proto not in ["TCP4", "TCP6", "UNKNOWN"]:
            raise InvalidProxyLine(line)
        if proto == "TCP4":
            try:
                inet_pton(AF_INET, s_addr)
                inet_pton(AF_INET, d_addr)
            except Exception:
                raise InvalidProxyLine(line)
        elif proto == "TCP6":
            try:
                inet_pton(AF_INET6, s_addr)
                inet_pton(AF_INET6, d_addr)
            except Exception:
                raise InvalidProxyLine(line)
        if (65535 <= s_port < 0) or (65535 <= d_port <= 0):
            raise InvalidProxyLine(line)

        # Set data
        self.parser.client_info.update({
            "proxy_mode": proto,
            "client_addr": s_addr,
            "client_port": s_port,
            "proxy_addr": d_addr,
            "proxy_port": d_port
        })

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


