#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from enum import IntEnum
import ipaddress
import re
import socket
import struct

from gunicorn.http.body import ChunkedReader, LengthReader, EOFReader, Body
from gunicorn.http.errors import (
    InvalidHeader, InvalidHeaderName, NoMoreData,
    InvalidRequestLine, InvalidRequestMethod, InvalidHTTPVersion,
    LimitRequestLine, LimitRequestHeaders,
    UnsupportedTransferCoding, ObsoleteFolding,
)
from gunicorn.http.errors import InvalidProxyLine, InvalidProxyHeader, ForbiddenProxyRequest
from gunicorn.http.errors import InvalidSchemeHeaders
from gunicorn.util import bytes_to_str, split_request_uri


# PROXY protocol v2 constants
PP_V2_SIGNATURE = b"\x0D\x0A\x0D\x0A\x00\x0D\x0A\x51\x55\x49\x54\x0A"


class PPCommand(IntEnum):
    """PROXY protocol v2 commands."""
    LOCAL = 0x0
    PROXY = 0x1


class PPFamily(IntEnum):
    """PROXY protocol v2 address families."""
    UNSPEC = 0x0
    INET = 0x1   # IPv4
    INET6 = 0x2  # IPv6
    UNIX = 0x3


class PPProtocol(IntEnum):
    """PROXY protocol v2 transport protocols."""
    UNSPEC = 0x0
    STREAM = 0x1  # TCP
    DGRAM = 0x2   # UDP


MAX_REQUEST_LINE = 8190
MAX_HEADERS = 32768
DEFAULT_MAX_HEADERFIELD_SIZE = 8190

# verbosely on purpose, avoid backslash ambiguity
RFC9110_5_6_2_TOKEN_SPECIALS = r"!#$%&'*+-.^_`|~"
TOKEN_RE = re.compile(r"[%s0-9a-zA-Z]+" % (re.escape(RFC9110_5_6_2_TOKEN_SPECIALS)))
METHOD_BADCHAR_RE = re.compile("[a-z#]")
# usually 1.0 or 1.1 - RFC9112 permits restricting to single-digit versions
VERSION_RE = re.compile(r"HTTP/(\d)\.(\d)")
RFC9110_5_5_INVALID_AND_DANGEROUS = re.compile(r"[\0\r\n]")


def _ip_in_allow_list(ip_str, allow_list, networks):
    """Check if IP address is in the allow list.

    Args:
        ip_str: The IP address string to check
        allow_list: The original allow list (strings, may contain "*")
        networks: Pre-computed ipaddress.ip_network objects from config
    """
    if '*' in allow_list:
        return True
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    for network in networks:
        if ip in network:
            return True
    return False


class Message:
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
        self.must_close = False

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

    def force_close(self):
        self.must_close = True

    def parse(self, unreader):
        raise NotImplementedError()

    def parse_headers(self, data, from_trailer=False):
        cfg = self.cfg
        headers = []

        # Split lines on \r\n
        lines = [bytes_to_str(line) for line in data.split(b"\r\n")]

        # handle scheme headers
        scheme_header = False
        secure_scheme_headers = {}
        forwarder_headers = []
        if from_trailer:
            # nonsense. either a request is https from the beginning
            #  .. or we are just behind a proxy who does not remove conflicting trailers
            pass
        elif (not isinstance(self.peer_addr, tuple)
              or _ip_in_allow_list(self.peer_addr[0], cfg.forwarded_allow_ips,
                                   cfg.forwarded_allow_networks())):
            secure_scheme_headers = cfg.secure_scheme_headers
            forwarder_headers = cfg.forwarder_headers

        # Parse headers into key/value pairs paying attention
        # to continuation lines.
        while lines:
            if len(headers) >= self.limit_request_fields:
                raise LimitRequestHeaders("limit request headers fields")

            # Parse initial header name: value pair.
            curr = lines.pop(0)
            header_length = len(curr) + len("\r\n")
            if curr.find(":") <= 0:
                raise InvalidHeader(curr)
            name, value = curr.split(":", 1)
            if self.cfg.strip_header_spaces:
                name = name.rstrip(" \t")
            if not TOKEN_RE.fullmatch(name):
                raise InvalidHeaderName(name)

            # this is still a dangerous place to do this
            #  but it is more correct than doing it before the pattern match:
            # after we entered Unicode wonderland, 8bits could case-shift into ASCII:
            # b"\xDF".decode("latin-1").upper().encode("ascii") == b"SS"
            name = name.upper()

            value = [value.strip(" \t")]

            # Consume value continuation lines..
            while lines and lines[0].startswith((" ", "\t")):
                # .. which is obsolete here, and no longer done by default
                if not self.cfg.permit_obsolete_folding:
                    raise ObsoleteFolding(name)
                curr = lines.pop(0)
                header_length += len(curr) + len("\r\n")
                if header_length > self.limit_request_field_size > 0:
                    raise LimitRequestHeaders("limit request headers "
                                              "fields size")
                value.append(curr.strip("\t "))
            value = " ".join(value)

            if RFC9110_5_5_INVALID_AND_DANGEROUS.search(value):
                raise InvalidHeader(name)

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

            # ambiguous mapping allows fooling downstream, e.g. merging non-identical headers:
            # X-Forwarded-For: 2001:db8::ha:cc:ed
            # X_Forwarded_For: 127.0.0.1,::1
            # HTTP_X_FORWARDED_FOR = 2001:db8::ha:cc:ed,127.0.0.1,::1
            # Only modify after fixing *ALL* header transformations; network to wsgi env
            if "_" in name:
                if name in forwarder_headers or "*" in forwarder_headers:
                    # This forwarder may override our environment
                    pass
                elif self.cfg.header_map == "dangerous":
                    # as if we did not know we cannot safely map this
                    pass
                elif self.cfg.header_map == "drop":
                    # almost as if it never had been there
                    # but still counts against resource limits
                    continue
                else:
                    # fail-safe fallthrough: refuse
                    raise InvalidHeaderName(name)

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
                # T-E can be a list
                # https://datatracker.ietf.org/doc/html/rfc9112#name-transfer-encoding
                vals = [v.strip() for v in value.split(',')]
                for val in vals:
                    if val.lower() == "chunked":
                        # DANGER: transfer codings stack, and stacked chunking is never intended
                        if chunked:
                            raise InvalidHeader("TRANSFER-ENCODING", req=self)
                        chunked = True
                    elif val.lower() == "identity":
                        # does not do much, could still plausibly desync from what the proxy does
                        # safe option: nuke it, its never needed
                        if chunked:
                            raise InvalidHeader("TRANSFER-ENCODING", req=self)
                    elif val.lower() in ('compress', 'deflate', 'gzip'):
                        # chunked should be the last one
                        if chunked:
                            raise InvalidHeader("TRANSFER-ENCODING", req=self)
                        self.force_close()
                    else:
                        raise UnsupportedTransferCoding(value)

        if chunked:
            # two potentially dangerous cases:
            #  a) CL + TE (TE overrides CL.. only safe if the recipient sees it that way too)
            #  b) chunked HTTP/1.0 (always faulty)
            if self.version < (1, 1):
                # framing wonky, see RFC 9112 Section 6.1
                raise InvalidHeader("TRANSFER-ENCODING", req=self)
            if content_length is not None:
                # we cannot be certain the message framing we understood matches proxy intent
                #  -> whatever happens next, remaining input must not be trusted
                raise InvalidHeader("CONTENT-LENGTH", req=self)
            self.body = Body(ChunkedReader(self, self.unreader))
        elif content_length is not None:
            try:
                if str(content_length).isnumeric():
                    content_length = int(content_length)
                else:
                    raise InvalidHeader("CONTENT-LENGTH", req=self)
            except ValueError:
                raise InvalidHeader("CONTENT-LENGTH", req=self)

            if content_length < 0:
                raise InvalidHeader("CONTENT-LENGTH", req=self)

            self.body = Body(LengthReader(self.unreader, content_length))
        else:
            self.body = Body(EOFReader(self.unreader))

    def should_close(self):
        if self.must_close:
            return True
        for (h, v) in self.headers:
            if h == "CONNECTION":
                v = v.lower().strip(" \t")
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

    def get_data(self, unreader, buf, stop=False):
        data = unreader.read()
        if not data:
            if stop:
                raise StopIteration()
            raise NoMoreData(buf.getvalue())
        buf.write(data)

    def parse(self, unreader):
        buf = bytearray()
        self.read_into(unreader, buf, stop=True)

        # Handle proxy protocol if enabled and this is the first request
        mode = self.cfg.proxy_protocol
        if mode != "off" and self.req_number == 1:
            buf = self._handle_proxy_protocol(unreader, buf, mode)

        # Get request line
        line, buf = self.read_line(unreader, buf, self.limit_request_line)

        self.parse_request_line(line)

        # Headers
        data = bytes(buf)

        done = data[:2] == b"\r\n"
        while True:
            idx = data.find(b"\r\n\r\n")
            done = data[:2] == b"\r\n"

            if idx < 0 and not done:
                self.read_into(unreader, buf)
                data = bytes(buf)
                if len(data) > self.max_buffer_headers:
                    raise LimitRequestHeaders("max buffer headers")
            else:
                break

        if done:
            self.unreader.unread(data[2:])
            return b""

        self.headers = self.parse_headers(data[:idx], from_trailer=False)

        ret = data[idx + 4:]
        return ret

    def read_into(self, unreader, buf, stop=False):
        """Read data from unreader and append to bytearray buffer."""
        data = unreader.read()
        if not data:
            if stop:
                raise StopIteration()
            raise NoMoreData(bytes(buf))
        buf.extend(data)

    def read_line(self, unreader, buf, limit=0):
        """Read a line from buffer, returning (line, remaining_buffer)."""
        data = bytes(buf)

        while True:
            idx = data.find(b"\r\n")
            if idx >= 0:
                # check if the request line is too large
                if idx > limit > 0:
                    raise LimitRequestLine(idx, limit)
                break
            if len(data) - 2 > limit > 0:
                raise LimitRequestLine(len(data), limit)
            self.read_into(unreader, buf)
            data = bytes(buf)

        return (data[:idx],  # request line,
                bytearray(data[idx + 2:]))  # residue in the buffer, skip \r\n

    def read_bytes(self, unreader, buf, count):
        """Read exactly count bytes from buffer/unreader."""
        while len(buf) < count:
            self.read_into(unreader, buf)
        return bytes(buf[:count]), bytearray(buf[count:])

    def _handle_proxy_protocol(self, unreader, buf, mode):
        """Handle PROXY protocol detection and parsing.

        Returns the buffer with proxy protocol data consumed.
        """
        # Ensure we have enough data to detect v2 signature (12 bytes)
        while len(buf) < 12:
            self.read_into(unreader, buf)

        # Check for v2 signature first
        if mode in ("v2", "auto") and buf[:12] == PP_V2_SIGNATURE:
            self.proxy_protocol_access_check()
            return self._parse_proxy_protocol_v2(unreader, buf)

        # Check for v1 prefix
        if mode in ("v1", "auto") and buf[:6] == b"PROXY ":
            self.proxy_protocol_access_check()
            return self._parse_proxy_protocol_v1(unreader, buf)

        # Not proxy protocol - return buffer unchanged
        return buf

    def proxy_protocol_access_check(self):
        """Check if proxy protocol is allowed from this peer."""
        if (isinstance(self.peer_addr, tuple) and
                not _ip_in_allow_list(self.peer_addr[0], self.cfg.proxy_allow_ips,
                                      self.cfg.proxy_allow_networks())):
            raise ForbiddenProxyRequest(self.peer_addr[0])

    def _parse_proxy_protocol_v1(self, unreader, buf):
        """Parse PROXY protocol v1 (text format).

        Returns buffer with v1 header consumed.
        """
        # Read until we find \r\n
        data = bytes(buf)
        while b"\r\n" not in data:
            self.read_into(unreader, buf)
            data = bytes(buf)

        idx = data.find(b"\r\n")
        line = bytes_to_str(data[:idx])
        remaining = bytearray(data[idx + 2:])

        bits = line.split(" ")

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
            except OSError:
                raise InvalidProxyLine(line)
        elif proto == "TCP6":
            try:
                socket.inet_pton(socket.AF_INET6, s_addr)
                socket.inet_pton(socket.AF_INET6, d_addr)
            except OSError:
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

        return remaining

    def _parse_proxy_protocol_v2(self, unreader, buf):
        """Parse PROXY protocol v2 (binary format).

        Returns buffer with v2 header consumed.
        """
        # We need at least 16 bytes for the header (12 signature + 4 header)
        while len(buf) < 16:
            self.read_into(unreader, buf)

        # Parse header fields (after 12-byte signature)
        ver_cmd = buf[12]
        fam_proto = buf[13]
        length = struct.unpack(">H", bytes(buf[14:16]))[0]

        # Validate version (high nibble must be 0x2)
        version = (ver_cmd & 0xF0) >> 4
        if version != 2:
            raise InvalidProxyHeader("unsupported version %d" % version)

        # Extract command (low nibble)
        command = ver_cmd & 0x0F
        if command not in (PPCommand.LOCAL, PPCommand.PROXY):
            raise InvalidProxyHeader("unsupported command %d" % command)

        # Ensure we have the complete header
        total_header_size = 16 + length
        while len(buf) < total_header_size:
            self.read_into(unreader, buf)

        # For LOCAL command, no address info is provided
        if command == PPCommand.LOCAL:
            self.proxy_protocol_info = {
                "proxy_protocol": "LOCAL",
                "client_addr": None,
                "client_port": None,
                "proxy_addr": None,
                "proxy_port": None
            }
            return bytearray(buf[total_header_size:])

        # Extract address family and protocol
        family = (fam_proto & 0xF0) >> 4
        protocol = fam_proto & 0x0F

        # We only support TCP (STREAM)
        if protocol != PPProtocol.STREAM:
            raise InvalidProxyHeader("only TCP protocol is supported")

        addr_data = bytes(buf[16:16 + length])

        if family == PPFamily.INET:  # IPv4
            if length < 12:  # 4+4+2+2
                raise InvalidProxyHeader("insufficient address data for IPv4")
            s_addr = socket.inet_ntop(socket.AF_INET, addr_data[0:4])
            d_addr = socket.inet_ntop(socket.AF_INET, addr_data[4:8])
            s_port = struct.unpack(">H", addr_data[8:10])[0]
            d_port = struct.unpack(">H", addr_data[10:12])[0]
            proto = "TCP4"

        elif family == PPFamily.INET6:  # IPv6
            if length < 36:  # 16+16+2+2
                raise InvalidProxyHeader("insufficient address data for IPv6")
            s_addr = socket.inet_ntop(socket.AF_INET6, addr_data[0:16])
            d_addr = socket.inet_ntop(socket.AF_INET6, addr_data[16:32])
            s_port = struct.unpack(">H", addr_data[32:34])[0]
            d_port = struct.unpack(">H", addr_data[34:36])[0]
            proto = "TCP6"

        elif family == PPFamily.UNSPEC:
            # No address info provided with PROXY command
            self.proxy_protocol_info = {
                "proxy_protocol": "UNSPEC",
                "client_addr": None,
                "client_port": None,
                "proxy_addr": None,
                "proxy_port": None
            }
            return bytearray(buf[total_header_size:])

        else:
            raise InvalidProxyHeader("unsupported address family %d" % family)

        # Set data
        self.proxy_protocol_info = {
            "proxy_protocol": proto,
            "client_addr": s_addr,
            "client_port": s_port,
            "proxy_addr": d_addr,
            "proxy_port": d_port
        }

        return bytearray(buf[total_header_size:])

    def parse_request_line(self, line_bytes):
        bits = [bytes_to_str(bit) for bit in line_bytes.split(b" ", 2)]
        if len(bits) != 3:
            raise InvalidRequestLine(bytes_to_str(line_bytes))

        # Method: RFC9110 Section 9
        self.method = bits[0]

        # nonstandard restriction, suitable for all IANA registered methods
        # partially enforced in previous gunicorn versions
        if not self.cfg.permit_unconventional_http_method:
            if METHOD_BADCHAR_RE.search(self.method):
                raise InvalidRequestMethod(self.method)
            if not 3 <= len(bits[0]) <= 20:
                raise InvalidRequestMethod(self.method)
        # standard restriction: RFC9110 token
        if not TOKEN_RE.fullmatch(self.method):
            raise InvalidRequestMethod(self.method)
        # nonstandard and dangerous
        # methods are merely uppercase by convention, no case-insensitive treatment is intended
        if self.cfg.casefold_http_method:
            self.method = self.method.upper()

        # URI
        self.uri = bits[1]

        # Python stdlib explicitly tells us it will not perform validation.
        # https://docs.python.org/3/library/urllib.parse.html#url-parsing-security
        # There are *four* `request-target` forms in rfc9112, none of them can be empty:
        # 1. origin-form, which starts with a slash
        # 2. absolute-form, which starts with a non-empty scheme
        # 3. authority-form, (for CONNECT) which contains a colon after the host
        # 4. asterisk-form, which is an asterisk (`\x2A`)
        # => manually reject one always invalid URI: empty
        if len(self.uri) == 0:
            raise InvalidRequestLine(bytes_to_str(line_bytes))

        try:
            parts = split_request_uri(self.uri)
        except ValueError:
            raise InvalidRequestLine(bytes_to_str(line_bytes))
        self.path = parts.path or ""
        self.query = parts.query or ""
        self.fragment = parts.fragment or ""

        # Version
        match = VERSION_RE.fullmatch(bits[2])
        if match is None:
            raise InvalidHTTPVersion(bits[2])
        self.version = (int(match.group(1)), int(match.group(2)))
        if not (1, 0) <= self.version < (2, 0):
            # if ever relaxing this, carefully review Content-Encoding processing
            if not self.cfg.permit_unconventional_http_version:
                raise InvalidHTTPVersion(self.version)

    def set_body_reader(self):
        super().set_body_reader()
        if isinstance(self.body.reader, EOFReader):
            self.body = Body(LengthReader(self.unreader, 0))
