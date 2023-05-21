# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.
import ipaddress
import re
import socket
import struct
from enum import IntEnum

from gunicorn.http.body import ChunkedReader, LengthReader, EOFReader, Body
from gunicorn.http.errors import (
    InvalidHeader, InvalidHeaderName, NoMoreData,
    InvalidRequestLine, InvalidRequestMethod, InvalidHTTPVersion,
    LimitRequestLine, LimitRequestHeaders,
)
from gunicorn.http.errors import InvalidProxyHeader, InvalidProxyLine
from gunicorn.http.errors import ForbiddenProxyRequest, InvalidSchemeHeaders
from gunicorn.util import bytes_to_str, split_request_uri

MAX_REQUEST_LINE = 8190
MAX_HEADERS = 32768
DEFAULT_MAX_HEADERFIELD_SIZE = 8190

HEADER_RE = re.compile(r"[\x00-\x1F\x7F()<>@,;:\[\]={} \t\\\"]")
METH_RE = re.compile(r"[A-Z0-9$-_.]{3,20}")
VERSION_RE = re.compile(r"HTTP/(\d+)\.(\d+)")


class PPCommand(IntEnum):
    LOCAL = 0x00
    PROXY = 0x01


class PPProtocol(IntEnum):
    UNSPEC = 0x00
    TCPv4 = 0x11
    UDPv4 = 0x12
    TCPv6 = 0x21
    UDPv6 = 0x22
    STREAM_UNIX = 0x31
    DGRAM_UNIX = 0x32


class Message(object):
    def __init__(self, cfg, unreader, peer_addr):
        self.cfg = cfg
        self.unreader = unreader
        self.peer_addr = peer_addr
        self.remote_addr = peer_addr
        self.version = None
        self.headers = []
        self.trailers = []
        self.body = None
        self.scheme = "https" if cfg.is_ssl else "http"

        # set headers limits
        self.limit_request_fields = cfg.limit_request_fields
        if (self.limit_request_fields <= 0
                or self.limit_request_fields > MAX_HEADERS):
            self.limit_request_fields = MAX_HEADERS
        self.limit_request_field_size = cfg.limit_request_field_size
        if self.limit_request_field_size < 0:
            self.limit_request_field_size = DEFAULT_MAX_HEADERFIELD_SIZE

        # set max header buffer size
        max_header_field_size = self.limit_request_field_size or DEFAULT_MAX_HEADERFIELD_SIZE
        self.max_buffer_headers = self.limit_request_fields * \
            (max_header_field_size + 2) + 4

        unused = self.parse(self.unreader)
        self.unreader.unread(unused)
        self.set_body_reader()

    def parse(self, unreader):
        raise NotImplementedError()

    def parse_headers(self, data):
        cfg = self.cfg
        headers = []

        # Split lines on \r\n keeping the \r\n on each line
        lines = [bytes_to_str(line) + "\r\n" for line in data.split(b"\r\n")]

        # handle scheme headers
        scheme_header = False
        secure_scheme_headers = {}
        if ('*' in cfg.forwarded_allow_ips or
            not isinstance(self.peer_addr, tuple)
                or self.peer_addr[0] in cfg.forwarded_allow_ips):
            secure_scheme_headers = cfg.secure_scheme_headers

        # Parse headers into key/value pairs paying attention
        # to continuation lines.
        while lines:
            if len(headers) >= self.limit_request_fields:
                raise LimitRequestHeaders("limit request headers fields")

            # Parse initial header name : value pair.
            curr = lines.pop(0)
            header_length = len(curr)
            if curr.find(":") < 0:
                raise InvalidHeader(curr.strip())
            name, value = curr.split(":", 1)
            if self.cfg.strip_header_spaces:
                name = name.rstrip(" \t").upper()
            else:
                name = name.upper()
            if HEADER_RE.search(name):
                raise InvalidHeaderName(name)

            name, value = name.strip(), [value.lstrip()]

            # Consume value continuation lines
            while lines and lines[0].startswith((" ", "\t")):
                curr = lines.pop(0)
                header_length += len(curr)
                if header_length > self.limit_request_field_size > 0:
                    raise LimitRequestHeaders("limit request headers "
                                              "fields size")
                value.append(curr)
            value = ''.join(value).rstrip()

            if header_length > self.limit_request_field_size > 0:
                raise LimitRequestHeaders("limit request headers fields size")

            if name in secure_scheme_headers:
                secure = value == secure_scheme_headers[name]
                scheme = "https" if secure else "http"
                if scheme_header:
                    if scheme != self.scheme:
                        raise InvalidSchemeHeaders()
                else:
                    scheme_header = True
                    self.scheme = scheme

            headers.append((name, value))

        return headers

    def set_body_reader(self):
        chunked = False
        content_length = None

        for (name, value) in self.headers:
            if name == "CONTENT-LENGTH":
                if content_length is not None:
                    raise InvalidHeader("CONTENT-LENGTH", req=self)
                content_length = value
            elif name == "TRANSFER-ENCODING":
                if value.lower() == "chunked":
                    chunked = True

        if chunked:
            self.body = Body(ChunkedReader(self, self.unreader))
        elif content_length is not None:
            try:
                content_length = int(content_length)
            except ValueError:
                raise InvalidHeader("CONTENT-LENGTH", req=self)

            if content_length < 0:
                raise InvalidHeader("CONTENT-LENGTH", req=self)

            self.body = Body(LengthReader(self.unreader, content_length))
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
    def __init__(self, cfg, unreader, peer_addr, req_number=1):
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

        self.req_number = req_number
        self.proxy_protocol_info = None
        super().__init__(cfg, unreader, peer_addr)

    def get_data(self, unreader, buffer, stop=False):
        data = unreader.read()
        if not data:
            if stop:
                raise StopIteration()
            raise NoMoreData(bytes(buffer))
        buffer.extend(data)

    def parse(self, unreader):
        buffer = bytearray()
        self.get_data(unreader, buffer, stop=True)

        # proxy protocol
        self.proxy_protocol(unreader, buffer)

        # get request line
        line = self.read_line(unreader, buffer, self.limit_request_line)
        self.parse_request_line(line)

        # Headers
        while True:
            idx = buffer.find(b"\r\n\r\n")
            done = buffer[:2] == b"\r\n"

            if idx < 0 and not done:
                self.get_data(unreader, buffer)
                if len(buffer) > self.max_buffer_headers:
                    raise LimitRequestHeaders("max buffer headers")
            else:
                break

        if done:
            self.unreader.unread(buffer[2:])
            return b""

        self.headers = self.parse_headers(buffer[:idx])

        # Body
        ret = buffer[idx + 4:]
        buffer = None
        return ret

    def read_line(self, unreader, buffer, limit=0):
        while True:
            idx = buffer.find(b"\r\n")
            if idx >= 0:
                # check if the request line is too large
                if idx > limit > 0:
                    raise LimitRequestLine(idx, limit)
                break
            if len(buffer) - 2 > limit > 0:
                raise LimitRequestLine(len(buffer), limit)
            self.get_data(unreader, buffer)

        result = buffer[:idx]   # request line
        buffer[:] = buffer[idx + 2:]  # residue in the buffer, skip \r\n
        return result

    def read_bytes(self, unreader, buffer, size):
        while True:
            bytes_read = len(buffer)
            if bytes_read >= size:
                break
            self.get_data(unreader, buffer)

        result, buffer[:] = buffer[:size], buffer[size:]
        return result

    def proxy_protocol(self, unreader, buffer):
        """Detect, check and parse proxy protocol.

        :raises: ForbiddenProxyRequest, InvalidProxyLine.
        """
        if not self.cfg.proxy_protocol:
            return

        if self.req_number != 1:
            return

        data = self.read_bytes(unreader, buffer, 5)
        if data == b"PROXY":
            self.proxy_protocol_access_check()
            line = self.read_line(unreader, buffer, self.limit_request_line)
            self.parse_proxy_protocol_v1(bytes_to_str(data + line))
            return

        elif data == b"\x0D\x0A\x0D\x0A\x00":  # Potentially proxy protocol v2
            data += self.read_bytes(unreader, buffer, 7)
            if data == b"\x0D\x0A\x0D\x0A\x00\x0D\x0A\x51\x55\x49\x54\x0A":
                self.proxy_protocol_access_check()
                self.parse_proxy_protocol_v2(unreader, buffer)
                return

        # Restore the buffer, this is a normal request
        buffer[:] = data + buffer

    def proxy_protocol_access_check(self):
        # check in allow list
        if ("*" not in self.cfg.proxy_allow_ips and
            isinstance(self.peer_addr, tuple) and
                self.peer_addr[0] not in self.cfg.proxy_allow_ips):
            raise ForbiddenProxyRequest(self.peer_addr[0])

    def parse_proxy_protocol_v1(self, line):
        bits = line.split()

        if len(bits) != 6:
            raise InvalidProxyLine(line)

        # Extract data
        proto = bits[1]
        s_addr = bits[2]
        d_addr = bits[3]

        # Validation
        if proto not in ["TCP4", "TCP6"]:
            raise InvalidProxyLine("protocol '%s' not supported" % proto)
        if proto == "TCP4":
            try:
                socket.inet_pton(socket.AF_INET, s_addr)
                socket.inet_pton(socket.AF_INET, d_addr)
            except socket.error:
                raise InvalidProxyLine(line)
        elif proto == "TCP6":
            try:
                socket.inet_pton(socket.AF_INET6, s_addr)
                socket.inet_pton(socket.AF_INET6, d_addr)
            except socket.error:
                raise InvalidProxyLine(line)

        try:
            s_port = int(bits[4])
            d_port = int(bits[5])
        except ValueError:
            raise InvalidProxyLine("invalid port %s" % line)

        if not ((0 <= s_port <= 65535) and (0 <= d_port <= 65535)):
            raise InvalidProxyLine("invalid port %s" % line)

        # Set data
        self.proxy_protocol_info = {
            "proxy_protocol": proto,
            "client_addr": s_addr,
            "client_port": s_port,
            "proxy_addr": d_addr,
            "proxy_port": d_port
        }

    def parse_proxy_protocol_v2(self, unreader, buffer):
        data = self.read_bytes(unreader, buffer, 4)
        ver_cmd, fam, length = struct.unpack("!BBH", data)
        if ver_cmd & 0xF0 != 0x20:
            raise InvalidProxyHeader("invalid version %r" % data)
        if ver_cmd & 0xF not in {PPCommand.LOCAL, PPCommand.PROXY}:
            raise InvalidProxyHeader("unsupported command %r" % data)

        body = self.read_bytes(unreader, buffer, length)
        if ver_cmd & 0xF == PPCommand.LOCAL:
            return  # LOCAL command, do not change source addr

        if fam == PPProtocol.TCPv4:
            proto = "TCP4"
            fmt = "!IIHH"
            ip_class = ipaddress.IPv4Address
        elif fam == PPProtocol.TCPv6:
            proto = "TCP6"
            fmt = "!16s16sHH"
            ip_class = ipaddress.IPv6Address
        else:
            raise InvalidProxyHeader("unsupported protocol %r" % body)

        try:
            s_addr, d_addr, s_port, d_port = struct.unpack(fmt, body)
        except struct.error as e:
            raise InvalidProxyHeader("cannot unpack %r: %s" % (body, e))
        s_addr = str(ip_class(s_addr))
        d_addr = str(ip_class(d_addr))

        if not ((0 <= s_port <= 65535) and (0 <= d_port <= 65535)):
            raise InvalidProxyHeader("invalid port %r" % body)

        self.proxy_protocol_info = {
            "proxy_protocol": proto,
            "client_addr": s_addr,
            "client_port": s_port,
            "proxy_addr": d_addr,
            "proxy_port": d_port
        }

    def parse_request_line(self, line_bytes):
        bits = [bytes_to_str(bit) for bit in line_bytes.split(None, 2)]
        if len(bits) != 3:
            raise InvalidRequestLine(bytes_to_str(line_bytes))

        # Method
        if not METH_RE.match(bits[0]):
            raise InvalidRequestMethod(bits[0])
        self.method = bits[0].upper()

        # URI
        self.uri = bits[1]

        try:
            parts = split_request_uri(self.uri)
        except ValueError:
            raise InvalidRequestLine(bytes_to_str(line_bytes))
        self.path = parts.path or ""
        self.query = parts.query or ""
        self.fragment = parts.fragment or ""

        # Version
        match = VERSION_RE.match(bits[2])
        if match is None:
            raise InvalidHTTPVersion(bits[2])
        self.version = (int(match.group(1)), int(match.group(2)))

    def set_body_reader(self):
        super().set_body_reader()
        if isinstance(self.body.reader, EOFReader):
            self.body = Body(LengthReader(self.unreader, 0))
