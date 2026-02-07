#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Async version of gunicorn/http/message.py for ASGI workers.

Reuses the parsing logic from the sync version, adapted for async I/O.
"""

import io
import ipaddress
import re
import socket
import struct

from gunicorn.http.errors import (
    ExpectationFailed,
    InvalidHeader, InvalidHeaderName, NoMoreData,
    InvalidRequestLine, InvalidRequestMethod, InvalidHTTPVersion,
    LimitRequestLine, LimitRequestHeaders,
    UnsupportedTransferCoding, ObsoleteFolding,
    InvalidProxyLine, InvalidProxyHeader, ForbiddenProxyRequest,
    InvalidSchemeHeaders,
)
from gunicorn.http.message import (
    PP_V2_SIGNATURE, PPCommand, PPFamily, PPProtocol
)
from gunicorn.util import bytes_to_str, split_request_uri

MAX_REQUEST_LINE = 8190
MAX_HEADERS = 32768
DEFAULT_MAX_HEADERFIELD_SIZE = 8190

# Reuse regex patterns from sync version
RFC9110_5_6_2_TOKEN_SPECIALS = r"!#$%&'*+-.^_`|~"
TOKEN_RE = re.compile(r"[%s0-9a-zA-Z]+" % (re.escape(RFC9110_5_6_2_TOKEN_SPECIALS)))
METHOD_BADCHAR_RE = re.compile("[a-z#]")
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


class AsyncRequest:
    """Async HTTP request parser.

    Parses HTTP/1.x requests using async I/O, reusing gunicorn's
    parsing logic where possible.
    """

    def __init__(self, cfg, unreader, peer_addr, req_number=1):
        self.cfg = cfg
        self.unreader = unreader
        self.peer_addr = peer_addr
        self.remote_addr = peer_addr
        self.req_number = req_number

        self.version = None
        self.method = None
        self.uri = None
        self.path = None
        self.query = None
        self.fragment = None
        self.headers = []
        self.trailers = []
        self.scheme = "https" if cfg.is_ssl else "http"
        self.must_close = False
        self._expected_100_continue = False

        self.proxy_protocol_info = None

        # Request line limit
        self.limit_request_line = cfg.limit_request_line
        if (self.limit_request_line < 0
                or self.limit_request_line >= MAX_REQUEST_LINE):
            self.limit_request_line = MAX_REQUEST_LINE

        # Headers limits
        self.limit_request_fields = cfg.limit_request_fields
        if (self.limit_request_fields <= 0
                or self.limit_request_fields > MAX_HEADERS):
            self.limit_request_fields = MAX_HEADERS

        self.limit_request_field_size = cfg.limit_request_field_size
        if self.limit_request_field_size < 0:
            self.limit_request_field_size = DEFAULT_MAX_HEADERFIELD_SIZE

        # Max header buffer size
        max_header_field_size = self.limit_request_field_size or DEFAULT_MAX_HEADERFIELD_SIZE
        self.max_buffer_headers = self.limit_request_fields * \
            (max_header_field_size + 2) + 4

        # Body-related state
        self.content_length = None
        self.chunked = False
        self._body_reader = None
        self._body_remaining = 0

    @classmethod
    async def parse(cls, cfg, unreader, peer_addr, req_number=1):
        """Parse an HTTP request from the stream.

        Args:
            cfg: gunicorn config object
            unreader: AsyncUnreader instance
            peer_addr: client address tuple
            req_number: request number on this connection (for keepalive)

        Returns:
            AsyncRequest: Parsed request object

        Raises:
            NoMoreData: If no data available
            Various parsing errors for malformed requests
        """
        req = cls(cfg, unreader, peer_addr, req_number)
        await req._parse()
        return req

    async def _parse(self):
        """Parse the request from the unreader."""
        buf = bytearray()
        await self._read_into(buf)

        # Handle proxy protocol if enabled and this is the first request
        mode = self.cfg.proxy_protocol
        if mode != "off" and self.req_number == 1:
            buf = await self._handle_proxy_protocol(buf, mode)

        # Get request line
        line, buf = await self._read_line(buf, self.limit_request_line)

        self._parse_request_line(line)

        # Headers
        data = bytes(buf)

        while True:
            idx = data.find(b"\r\n\r\n")
            done = data[:2] == b"\r\n"

            if idx < 0 and not done:
                await self._read_into(buf)
                data = bytes(buf)
                if len(data) > self.max_buffer_headers:
                    raise LimitRequestHeaders("max buffer headers")
            else:
                break

        if done:
            self.unreader.unread(data[2:])
        else:
            self.headers = self._parse_headers(data[:idx], from_trailer=False)
            self.unreader.unread(data[idx + 4:])

        self._set_body_reader()

    async def _read_into(self, buf):
        """Read data from unreader and append to bytearray buffer."""
        data = await self.unreader.read()
        if not data:
            raise NoMoreData(bytes(buf))
        buf.extend(data)

    async def _read_line(self, buf, limit=0):
        """Read a line from buffer, returning (line, remaining_buffer)."""
        data = bytes(buf)

        while True:
            idx = data.find(b"\r\n")
            if idx >= 0:
                if idx > limit > 0:
                    raise LimitRequestLine(idx, limit)
                break
            if len(data) - 2 > limit > 0:
                raise LimitRequestLine(len(data), limit)
            await self._read_into(buf)
            data = bytes(buf)

        return (data[:idx], bytearray(data[idx + 2:]))

    async def _handle_proxy_protocol(self, buf, mode):
        """Handle PROXY protocol detection and parsing.

        Returns the buffer with proxy protocol data consumed.
        """
        # Ensure we have enough data to detect v2 signature (12 bytes)
        while len(buf) < 12:
            await self._read_into(buf)

        # Check for v2 signature first
        if mode in ("v2", "auto") and buf[:12] == PP_V2_SIGNATURE:
            self._proxy_protocol_access_check()
            return await self._parse_proxy_protocol_v2(buf)

        # Check for v1 prefix
        if mode in ("v1", "auto") and buf[:6] == b"PROXY ":
            self._proxy_protocol_access_check()
            return await self._parse_proxy_protocol_v1(buf)

        # Not proxy protocol - return buffer unchanged
        return buf

    def _proxy_protocol_access_check(self):
        """Check if proxy protocol is allowed from this peer."""
        if (isinstance(self.peer_addr, tuple) and
                not _ip_in_allow_list(self.peer_addr[0], self.cfg.proxy_allow_ips,
                                      self.cfg.proxy_allow_networks())):
            raise ForbiddenProxyRequest(self.peer_addr[0])

    async def _parse_proxy_protocol_v1(self, buf):
        """Parse PROXY protocol v1 (text format).

        Returns buffer with v1 header consumed.
        """
        # Read until we find \r\n
        data = bytes(buf)
        while b"\r\n" not in data:
            await self._read_into(buf)
            data = bytes(buf)

        idx = data.find(b"\r\n")
        line = bytes_to_str(data[:idx])
        remaining = bytearray(data[idx + 2:])

        bits = line.split(" ")

        if len(bits) != 6:
            raise InvalidProxyLine(line)

        proto = bits[1]
        s_addr = bits[2]
        d_addr = bits[3]

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

        self.proxy_protocol_info = {
            "proxy_protocol": proto,
            "client_addr": s_addr,
            "client_port": s_port,
            "proxy_addr": d_addr,
            "proxy_port": d_port
        }

        return remaining

    async def _parse_proxy_protocol_v2(self, buf):
        """Parse PROXY protocol v2 (binary format).

        Returns buffer with v2 header consumed.
        """
        # We need at least 16 bytes for the header (12 signature + 4 header)
        while len(buf) < 16:
            await self._read_into(buf)

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
            await self._read_into(buf)

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

    def _parse_request_line(self, line_bytes):
        """Parse the HTTP request line."""
        bits = [bytes_to_str(bit) for bit in line_bytes.split(b" ", 2)]
        if len(bits) != 3:
            raise InvalidRequestLine(bytes_to_str(line_bytes))

        # Method
        self.method = bits[0]

        if not self.cfg.permit_unconventional_http_method:
            if METHOD_BADCHAR_RE.search(self.method):
                raise InvalidRequestMethod(self.method)
            if not 3 <= len(bits[0]) <= 20:
                raise InvalidRequestMethod(self.method)
        if not TOKEN_RE.fullmatch(self.method):
            raise InvalidRequestMethod(self.method)
        if self.cfg.casefold_http_method:
            self.method = self.method.upper()

        # URI
        self.uri = bits[1]

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
            if not self.cfg.permit_unconventional_http_version:
                raise InvalidHTTPVersion(self.version)

    def _parse_headers(self, data, from_trailer=False):
        """Parse HTTP headers from raw data."""
        cfg = self.cfg
        headers = []

        lines = [bytes_to_str(line) for line in data.split(b"\r\n")]

        # Handle scheme headers
        scheme_header = False
        secure_scheme_headers = {}
        forwarder_headers = []
        if from_trailer:
            pass
        elif (not isinstance(self.peer_addr, tuple)
              or _ip_in_allow_list(self.peer_addr[0], cfg.forwarded_allow_ips,
                                   cfg.forwarded_allow_networks())):
            secure_scheme_headers = cfg.secure_scheme_headers
            forwarder_headers = cfg.forwarder_headers

        while lines:
            if len(headers) >= self.limit_request_fields:
                raise LimitRequestHeaders("limit request headers fields")

            curr = lines.pop(0)
            header_length = len(curr) + len("\r\n")
            if curr.find(":") <= 0:
                raise InvalidHeader(curr)
            name, value = curr.split(":", 1)
            if self.cfg.strip_header_spaces:
                name = name.rstrip(" \t")
            if not TOKEN_RE.fullmatch(name):
                raise InvalidHeaderName(name)

            name = name.upper()
            value = [value.strip(" \t")]

            # Consume value continuation lines
            while lines and lines[0].startswith((" ", "\t")):
                if not self.cfg.permit_obsolete_folding:
                    raise ObsoleteFolding(name)
                curr = lines.pop(0)
                header_length += len(curr) + len("\r\n")
                if header_length > self.limit_request_field_size > 0:
                    raise LimitRequestHeaders("limit request headers fields size")
                value.append(curr.strip("\t "))
            value = " ".join(value)

            if RFC9110_5_5_INVALID_AND_DANGEROUS.search(value):
                raise InvalidHeader(name)

            if header_length > self.limit_request_field_size > 0:
                raise LimitRequestHeaders("limit request headers fields size")

            if not from_trailer and name == "EXPECT":
                # https://datatracker.ietf.org/doc/html/rfc9110#section-10.1.1
                # "The Expect field value is case-insensitive."
                if value.lower() == "100-continue":
                    if self.version < (1, 1):
                        # https://datatracker.ietf.org/doc/html/rfc9110#section-10.1.1-12
                        # "A server that receives a 100-continue expectation
                        #  in an HTTP/1.0 request MUST ignore that expectation."
                        pass
                    else:
                        self._expected_100_continue = True
                    # N.B. understood but ignored expect header does not return 417
                else:
                    raise ExpectationFailed(value)

            if name in secure_scheme_headers:
                secure = value == secure_scheme_headers[name]
                scheme = "https" if secure else "http"
                if scheme_header:
                    if scheme != self.scheme:
                        raise InvalidSchemeHeaders()
                else:
                    scheme_header = True
                    self.scheme = scheme

            if "_" in name:
                if name in forwarder_headers or "*" in forwarder_headers:
                    pass
                elif self.cfg.header_map == "dangerous":
                    pass
                elif self.cfg.header_map == "drop":
                    continue
                else:
                    raise InvalidHeaderName(name)

            headers.append((name, value))

        return headers

    def _set_body_reader(self):
        """Determine how to read the request body."""
        chunked = False
        content_length = None

        for (name, value) in self.headers:
            if name == "CONTENT-LENGTH":
                if content_length is not None:
                    raise InvalidHeader("CONTENT-LENGTH", req=self)
                content_length = value
            elif name == "TRANSFER-ENCODING":
                vals = [v.strip() for v in value.split(',')]
                for val in vals:
                    if val.lower() == "chunked":
                        if chunked:
                            raise InvalidHeader("TRANSFER-ENCODING", req=self)
                        chunked = True
                    elif val.lower() == "identity":
                        if chunked:
                            raise InvalidHeader("TRANSFER-ENCODING", req=self)
                    elif val.lower() in ('compress', 'deflate', 'gzip'):
                        if chunked:
                            raise InvalidHeader("TRANSFER-ENCODING", req=self)
                        self.force_close()
                    else:
                        raise UnsupportedTransferCoding(value)

        if chunked:
            if self.version < (1, 1):
                raise InvalidHeader("TRANSFER-ENCODING", req=self)
            if content_length is not None:
                raise InvalidHeader("CONTENT-LENGTH", req=self)
            self.chunked = True
            self.content_length = None
            self._body_remaining = -1
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

            self.content_length = content_length
            self._body_remaining = content_length
        else:
            # No body for requests without Content-Length or Transfer-Encoding
            self.content_length = 0
            self._body_remaining = 0

    def force_close(self):
        """Mark connection for closing after this request."""
        self.must_close = True

    def should_close(self):
        """Check if connection should be closed after this request."""
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

    def get_header(self, name):
        """Get a header value by name (case-insensitive)."""
        name = name.upper()
        for (h, v) in self.headers:
            if h == name:
                return v
        return None

    async def read_body(self, size=8192):
        """Read a chunk of the request body.

        Args:
            size: Maximum bytes to read

        Returns:
            bytes: Body data, empty bytes when body is exhausted
        """
        if self._body_remaining == 0:
            return b""

        if self.chunked:
            return await self._read_chunked_body(size)
        else:
            return await self._read_length_body(size)

    async def _read_length_body(self, size):
        """Read from a length-delimited body."""
        if self._body_remaining <= 0:
            return b""

        to_read = min(size, self._body_remaining)
        data = await self.unreader.read(to_read)
        if data:
            self._body_remaining -= len(data)
        return data

    async def _read_chunked_body(self, size):
        """Read from a chunked body."""
        if self._body_reader is None:
            self._body_reader = self._chunked_body_reader()

        try:
            return await anext(self._body_reader)
        except StopAsyncIteration:
            self._body_remaining = 0
            return b""

    async def _chunked_body_reader(self):
        """Async generator for reading chunked body."""
        while True:
            # Read chunk size line
            size_line = await self._read_chunk_size_line()
            # Parse chunk size (handle extensions)
            chunk_size, *_ = size_line.split(b";", 1)
            if _:
                chunk_size = chunk_size.rstrip(b" \t")

            if any(n not in b"0123456789abcdefABCDEF" for n in chunk_size):
                raise InvalidHeader("Invalid chunk size")
            if len(chunk_size) == 0:
                raise InvalidHeader("Invalid chunk size")

            chunk_size = int(chunk_size, 16)

            if chunk_size == 0:
                # Final chunk - skip trailers and final CRLF
                await self._skip_trailers()
                return

            # Read chunk data
            remaining = chunk_size
            while remaining > 0:
                data = await self.unreader.read(min(remaining, 8192))
                if not data:
                    raise NoMoreData()
                remaining -= len(data)
                yield data

            # Skip chunk terminating CRLF
            crlf = await self.unreader.read(2)
            if crlf != b"\r\n":
                # May have partial read, try to get the rest
                while len(crlf) < 2:
                    more = await self.unreader.read(2 - len(crlf))
                    if not more:
                        break
                    crlf += more
                if crlf != b"\r\n":
                    raise InvalidHeader("Missing chunk terminator")

    async def _read_chunk_size_line(self):
        """Read a chunk size line."""
        buf = io.BytesIO()
        while True:
            data = await self.unreader.read(1)
            if not data:
                raise NoMoreData()
            buf.write(data)
            if buf.getvalue().endswith(b"\r\n"):
                return buf.getvalue()[:-2]

    async def _skip_trailers(self):
        """Skip trailer headers after chunked body."""
        buf = io.BytesIO()
        while True:
            data = await self.unreader.read(1)
            if not data:
                return
            buf.write(data)
            content = buf.getvalue()
            if content.endswith(b"\r\n\r\n"):
                # Could parse trailers here if needed
                return
            if content == b"\r\n":
                return

    async def drain_body(self):
        """Drain any unread body data.

        Should be called before reusing connection for keepalive.
        """
        while True:
            data = await self.read_body(8192)
            if not data:
                break
