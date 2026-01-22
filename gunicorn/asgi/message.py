#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Async version of gunicorn/http/message.py for ASGI workers.

Reuses the parsing logic from the sync version, adapted for async I/O.
"""

import io
import re
import socket

from gunicorn.http.errors import (
    InvalidHeader, InvalidHeaderName, NoMoreData,
    InvalidRequestLine, InvalidRequestMethod, InvalidHTTPVersion,
    LimitRequestLine, LimitRequestHeaders,
    UnsupportedTransferCoding, ObsoleteFolding,
    InvalidProxyLine, ForbiddenProxyRequest,
    InvalidSchemeHeaders,
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
        buf = io.BytesIO()
        await self._get_data(buf, stop=True)

        # Get request line
        line, rbuf = await self._read_line(buf, self.limit_request_line)

        # Proxy protocol
        if self._proxy_protocol(bytes_to_str(line)):
            # Get next request line
            buf = io.BytesIO()
            buf.write(rbuf)
            line, rbuf = await self._read_line(buf, self.limit_request_line)

        self._parse_request_line(line)
        buf = io.BytesIO()
        buf.write(rbuf)

        # Headers
        data = buf.getvalue()

        while True:
            idx = data.find(b"\r\n\r\n")
            done = data[:2] == b"\r\n"

            if idx < 0 and not done:
                await self._get_data(buf)
                data = buf.getvalue()
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

    async def _get_data(self, buf, stop=False):
        """Read data from unreader into buffer."""
        data = await self.unreader.read()
        if not data:
            if stop:
                raise StopIteration()
            raise NoMoreData(buf.getvalue())
        buf.write(data)

    async def _read_line(self, buf, limit=0):
        """Read a line from the buffer/stream."""
        data = buf.getvalue()

        while True:
            idx = data.find(b"\r\n")
            if idx >= 0:
                if idx > limit > 0:
                    raise LimitRequestLine(idx, limit)
                break
            if len(data) - 2 > limit > 0:
                raise LimitRequestLine(len(data), limit)
            await self._get_data(buf)
            data = buf.getvalue()

        return (data[:idx], data[idx + 2:])

    def _proxy_protocol(self, line):
        """Detect, check and parse proxy protocol."""
        if not self.cfg.proxy_protocol:
            return False

        if self.req_number != 1:
            return False

        if not line.startswith("PROXY"):
            return False

        self._proxy_protocol_access_check()
        self._parse_proxy_protocol(line)

        return True

    def _proxy_protocol_access_check(self):
        """Check if proxy protocol is allowed from this peer."""
        if ("*" not in self.cfg.proxy_allow_ips and
            isinstance(self.peer_addr, tuple) and
                self.peer_addr[0] not in self.cfg.proxy_allow_ips):
            raise ForbiddenProxyRequest(self.peer_addr[0])

    def _parse_proxy_protocol(self, line):
        """Parse proxy protocol header line."""
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
        elif ('*' in cfg.forwarded_allow_ips or
              not isinstance(self.peer_addr, tuple)
              or self.peer_addr[0] in cfg.forwarded_allow_ips):
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
