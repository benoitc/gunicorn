#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Unified HTTP parser interface for ASGI workers.

Provides a common interface for both fast C parser (gunicorn_h1c)
and the pure Python parser, with incremental (push-based) parsing.
"""

import re
import ipaddress
import socket
import struct

from gunicorn.http.errors import (
    InvalidHeader, InvalidHeaderName, NoMoreData,
    InvalidRequestLine, InvalidRequestMethod, InvalidHTTPVersion,
    LimitRequestLine, LimitRequestHeaders,
    UnsupportedTransferCoding, ObsoleteFolding,
    InvalidProxyLine, InvalidProxyHeader, ForbiddenProxyRequest,
    InvalidSchemeHeaders, ExpectationFailed,
)
from gunicorn.http.message import PP_V2_SIGNATURE, PPCommand, PPFamily, PPProtocol
from gunicorn.util import bytes_to_str, split_request_uri

MAX_REQUEST_LINE = 8190
MAX_HEADERS = 32768
DEFAULT_MAX_HEADERFIELD_SIZE = 8190

# Reuse regex patterns
RFC9110_5_6_2_TOKEN_SPECIALS = r"!#$%&'*+-.^_`|~"
TOKEN_RE = re.compile(r"[%s0-9a-zA-Z]+" % (re.escape(RFC9110_5_6_2_TOKEN_SPECIALS)))
METHOD_BADCHAR_RE = re.compile("[a-z#]")
VERSION_RE = re.compile(r"HTTP/(\d)\.(\d)")
RFC9110_5_5_INVALID_AND_DANGEROUS = re.compile(r"[\0\r\n]")


def _ip_in_allow_list(ip_str, allow_list, networks):
    """Check if IP address is in the allow list."""
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


class ParseResult:
    """Result of header parsing.

    Headers are stored as bytes tuples for performance:
    - headers_bytes: list of (name_bytes_lowercase, value_bytes)
    - headers: list of (name_str_uppercase, value_str) for compatibility
    """

    __slots__ = (
        'method', 'uri', 'path', 'query', 'fragment', 'version',
        'headers', 'headers_bytes', 'scheme', 'content_length', 'chunked',
        'keep_alive', 'consumed', 'proxy_protocol_info',
        'must_close', 'expect_100_continue',
    )

    def __init__(self):
        self.method = None
        self.uri = None
        self.path = None
        self.query = None
        self.fragment = None
        self.version = None
        self.headers = []  # (name_str_uppercase, value_str) for compatibility
        self.headers_bytes = []  # (name_bytes_lowercase, value_bytes) for ASGI scope
        self.scheme = "http"
        self.content_length = 0
        self.chunked = False
        self.keep_alive = True
        self.consumed = 0
        self.proxy_protocol_info = None
        self.must_close = False
        self.expect_100_continue = False


class HttpParser:
    """Unified incremental HTTP parser.

    Works with both gunicorn_h1c (fast C extension) and pure Python parsing.
    Designed for push-based parsing where data arrives via data_received().
    """

    # Class-level cache for fast parser availability (import check is expensive)
    _fast_available = None
    _h1c_module = None

    def __init__(self, cfg, peer_addr, is_ssl=False, req_number=1, is_trusted_proxy=False):
        """Initialize the parser.

        Args:
            cfg: gunicorn config object
            peer_addr: client address tuple (host, port)
            is_ssl: whether this is an SSL connection
            req_number: request number on this connection (for proxy protocol)
            is_trusted_proxy: whether peer is in forwarded_allow_ips (pre-computed)
        """
        self.cfg = cfg
        self.peer_addr = peer_addr
        self.is_ssl = is_ssl
        self.req_number = req_number
        self._is_trusted_proxy = is_trusted_proxy
        self._result = None

        # Limits
        self.limit_request_line = cfg.limit_request_line
        if self.limit_request_line < 0 or self.limit_request_line >= MAX_REQUEST_LINE:
            self.limit_request_line = MAX_REQUEST_LINE

        self.limit_request_fields = cfg.limit_request_fields
        if self.limit_request_fields <= 0 or self.limit_request_fields > MAX_HEADERS:
            self.limit_request_fields = MAX_HEADERS

        self.limit_request_field_size = cfg.limit_request_field_size
        if self.limit_request_field_size < 0:
            self.limit_request_field_size = DEFAULT_MAX_HEADERFIELD_SIZE

        max_header_field_size = self.limit_request_field_size or DEFAULT_MAX_HEADERFIELD_SIZE
        self.max_buffer_headers = self.limit_request_fields * (max_header_field_size + 2) + 4

        # Use cached fast parser check (import is expensive, do once per process)
        self._use_fast = self._check_fast_available()

    def _check_fast_available(self):
        """Check if fast C parser is available (cached at class level)."""
        parser_setting = getattr(self.cfg, 'http_parser', 'auto')
        if parser_setting == 'python':
            return False

        # Use class-level cache to avoid repeated import checks
        if HttpParser._fast_available is None:
            try:
                import gunicorn_h1c
                HttpParser._fast_available = True
                HttpParser._h1c_module = gunicorn_h1c
            except ImportError:
                HttpParser._fast_available = False

        if not HttpParser._fast_available and parser_setting == 'fast':
            raise RuntimeError("gunicorn_h1c not installed but http_parser='fast'")

        return HttpParser._fast_available

    def feed(self, buffer):
        """Parse buffer incrementally.

        Args:
            buffer: bytearray containing received data

        Returns:
            ParseResult if headers are complete, None if more data needed

        Raises:
            Various HTTP parsing errors for malformed requests
        """
        if self._use_fast:
            return self._feed_fast(buffer)
        else:
            return self._feed_python(buffer)

    def _feed_fast(self, buffer):
        """Parse using fast C parser with optimized API.

        Uses parse_request_fast() which:
        - Accepts bytearray directly (no bytes() copy)
        - Returns pre-computed content_length, has_chunked, connection_close
        - Returns headers as bytes tuples (no intermediate conversion)
        """
        h1c = HttpParser._h1c_module
        try:
            # Use parse_request_fast - accepts bytearray directly
            req = h1c.parse_request_fast(buffer)

            # Build ParseResult from fast request object
            pr = ParseResult()

            # Method and path (bytes -> str)
            pr.method = bytes_to_str(req.method)
            pr.uri = bytes_to_str(req.path)

            # Parse path/query from URI
            try:
                parts = split_request_uri(pr.uri)
                pr.path = parts.path or ""
                pr.query = parts.query or ""
                pr.fragment = parts.fragment or ""
            except ValueError:
                pr.path = pr.uri
                pr.query = ""
                pr.fragment = ""

            pr.version = (1, req.minor_version)
            pr.consumed = req.consumed

            # Headers - store both bytes (for ASGI scope) and strings (for compatibility)
            # gunicorn_h1c returns headers as (name_bytes, value_bytes)
            headers_bytes = []
            headers_str = []
            for n, v in req.headers:
                # ASGI requires lowercase header names
                headers_bytes.append((n.lower(), v))
                # Compatibility: uppercase string names
                headers_str.append((bytes_to_str(n).upper(), bytes_to_str(v)))
            pr.headers_bytes = headers_bytes
            pr.headers = headers_str

            # Use pre-computed body info from C parser
            pr.content_length = req.content_length if req.content_length >= 0 else 0
            pr.chunked = req.has_chunked

            # connection_close: -1 = not set, 0 = keep-alive, 1 = close
            if req.connection_close == 1:
                pr.must_close = True
                pr.keep_alive = False
            elif req.connection_close == 0:
                pr.must_close = False
                pr.keep_alive = True
            else:
                # Not set - default based on HTTP version
                pr.keep_alive = req.minor_version >= 1
                pr.must_close = False

            pr.scheme = "https" if self.is_ssl else "http"

            # Apply scheme headers for trusted proxies
            if self._is_trusted_proxy:
                self._apply_scheme_headers(pr)

            self._result = pr
            return pr

        except h1c.IncompleteError:
            return None
        except h1c.ParseError as e:
            # Map to gunicorn HTTP errors
            raise InvalidRequestLine(str(e))

    def _feed_python(self, buffer):
        """Parse using pure Python parser."""
        # Handle proxy protocol on first request
        mode = self.cfg.proxy_protocol
        proxy_info = None
        buf_offset = 0

        if mode != "off" and self.req_number == 1:
            # Check for proxy protocol
            if len(buffer) < 12:
                return None  # Need more data

            if mode in ("v2", "auto") and buffer[:12] == PP_V2_SIGNATURE:
                self._proxy_protocol_access_check()
                consumed, proxy_info = self._parse_proxy_v2(buffer)
                if consumed is None:
                    return None  # Need more data
                buf_offset = consumed

            elif mode in ("v1", "auto") and buffer[:6] == b"PROXY ":
                self._proxy_protocol_access_check()
                consumed, proxy_info = self._parse_proxy_v1(buffer)
                if consumed is None:
                    return None  # Need more data
                buf_offset = consumed

        # Find request line
        idx = buffer.find(b"\r\n", buf_offset)
        if idx < 0:
            if len(buffer) - buf_offset > self.limit_request_line:
                raise LimitRequestLine(len(buffer) - buf_offset, self.limit_request_line)
            return None  # Need more data

        line_len = idx - buf_offset
        if line_len > self.limit_request_line:
            raise LimitRequestLine(line_len, self.limit_request_line)

        request_line = bytes(buffer[buf_offset:idx])
        headers_start = idx + 2

        # Find end of headers
        headers_end = buffer.find(b"\r\n\r\n", headers_start)
        if headers_end < 0:
            # Check for empty headers case
            if buffer[headers_start:headers_start + 2] == b"\r\n":
                headers_end = headers_start
            else:
                if len(buffer) - headers_start > self.max_buffer_headers:
                    raise LimitRequestHeaders("max buffer headers")
                return None  # Need more data

        # Parse request line
        pr = ParseResult()
        pr.proxy_protocol_info = proxy_info
        self._parse_request_line(request_line, pr)

        # Parse headers (if any)
        if buffer[headers_start:headers_start + 2] == b"\r\n":
            # Empty headers
            pr.consumed = headers_start + 2
            pr.headers_bytes = []
        else:
            headers_data = bytes(buffer[headers_start:headers_end])
            pr.headers = self._parse_headers(headers_data)
            # Also generate bytes headers for ASGI scope
            pr.headers_bytes = [
                (n.lower().encode('latin-1'), v.encode('latin-1'))
                for n, v in pr.headers
            ]
            pr.consumed = headers_end + 4

        # Set scheme
        pr.scheme = "https" if self.is_ssl else "http"

        # Check for scheme headers from trusted proxy
        self._apply_scheme_headers(pr)

        # Parse body info
        self._parse_body_info(pr)

        # Determine keep-alive
        pr.keep_alive = self._should_keep_alive(pr)

        self._result = pr
        return pr

    def _proxy_protocol_access_check(self):
        """Check if proxy protocol is allowed from this peer."""
        if isinstance(self.peer_addr, tuple):
            if not _ip_in_allow_list(
                self.peer_addr[0],
                self.cfg.proxy_allow_ips,
                self.cfg.proxy_allow_networks()
            ):
                raise ForbiddenProxyRequest(self.peer_addr[0])

    def _parse_proxy_v1(self, buffer):
        """Parse PROXY protocol v1 (text format).

        Returns (consumed, info) or (None, None) if incomplete.
        """
        idx = buffer.find(b"\r\n")
        if idx < 0:
            return None, None

        line = bytes_to_str(bytes(buffer[:idx]))
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

        info = {
            "proxy_protocol": proto,
            "client_addr": s_addr,
            "client_port": s_port,
            "proxy_addr": d_addr,
            "proxy_port": d_port
        }

        return idx + 2, info

    def _parse_proxy_v2(self, buffer):
        """Parse PROXY protocol v2 (binary format).

        Returns (consumed, info) or (None, None) if incomplete.
        """
        if len(buffer) < 16:
            return None, None

        ver_cmd = buffer[12]
        fam_proto = buffer[13]
        length = struct.unpack(">H", bytes(buffer[14:16]))[0]

        version = (ver_cmd & 0xF0) >> 4
        if version != 2:
            raise InvalidProxyHeader("unsupported version %d" % version)

        command = ver_cmd & 0x0F
        if command not in (PPCommand.LOCAL, PPCommand.PROXY):
            raise InvalidProxyHeader("unsupported command %d" % command)

        total_size = 16 + length
        if len(buffer) < total_size:
            return None, None

        if command == PPCommand.LOCAL:
            info = {
                "proxy_protocol": "LOCAL",
                "client_addr": None,
                "client_port": None,
                "proxy_addr": None,
                "proxy_port": None
            }
            return total_size, info

        family = (fam_proto & 0xF0) >> 4
        protocol = fam_proto & 0x0F

        if protocol != PPProtocol.STREAM:
            raise InvalidProxyHeader("only TCP protocol is supported")

        addr_data = bytes(buffer[16:16 + length])

        if family == PPFamily.INET:
            if length < 12:
                raise InvalidProxyHeader("insufficient address data for IPv4")
            s_addr = socket.inet_ntop(socket.AF_INET, addr_data[0:4])
            d_addr = socket.inet_ntop(socket.AF_INET, addr_data[4:8])
            s_port = struct.unpack(">H", addr_data[8:10])[0]
            d_port = struct.unpack(">H", addr_data[10:12])[0]
            proto = "TCP4"

        elif family == PPFamily.INET6:
            if length < 36:
                raise InvalidProxyHeader("insufficient address data for IPv6")
            s_addr = socket.inet_ntop(socket.AF_INET6, addr_data[0:16])
            d_addr = socket.inet_ntop(socket.AF_INET6, addr_data[16:32])
            s_port = struct.unpack(">H", addr_data[32:34])[0]
            d_port = struct.unpack(">H", addr_data[34:36])[0]
            proto = "TCP6"

        elif family == PPFamily.UNSPEC:
            info = {
                "proxy_protocol": "UNSPEC",
                "client_addr": None,
                "client_port": None,
                "proxy_addr": None,
                "proxy_port": None
            }
            return total_size, info

        else:
            raise InvalidProxyHeader("unsupported address family %d" % family)

        info = {
            "proxy_protocol": proto,
            "client_addr": s_addr,
            "client_port": s_port,
            "proxy_addr": d_addr,
            "proxy_port": d_port
        }

        return total_size, info

    def _parse_request_line(self, line_bytes, result):
        """Parse the HTTP request line."""
        bits = [bytes_to_str(bit) for bit in line_bytes.split(b" ", 2)]
        if len(bits) != 3:
            raise InvalidRequestLine(bytes_to_str(line_bytes))

        # Method
        result.method = bits[0]

        if not self.cfg.permit_unconventional_http_method:
            if METHOD_BADCHAR_RE.search(result.method):
                raise InvalidRequestMethod(result.method)
            if not 3 <= len(bits[0]) <= 20:
                raise InvalidRequestMethod(result.method)

        if not TOKEN_RE.fullmatch(result.method):
            raise InvalidRequestMethod(result.method)

        if self.cfg.casefold_http_method:
            result.method = result.method.upper()

        # URI
        result.uri = bits[1]
        if len(result.uri) == 0:
            raise InvalidRequestLine(bytes_to_str(line_bytes))

        try:
            parts = split_request_uri(result.uri)
        except ValueError:
            raise InvalidRequestLine(bytes_to_str(line_bytes))

        result.path = parts.path or ""
        result.query = parts.query or ""
        result.fragment = parts.fragment or ""

        # Version
        match = VERSION_RE.fullmatch(bits[2])
        if match is None:
            raise InvalidHTTPVersion(bits[2])

        result.version = (int(match.group(1)), int(match.group(2)))
        if not (1, 0) <= result.version < (2, 0):
            if not self.cfg.permit_unconventional_http_version:
                raise InvalidHTTPVersion(result.version)

    def _parse_headers(self, data):
        """Parse HTTP headers from raw data."""
        headers = []
        lines = [bytes_to_str(line) for line in data.split(b"\r\n")]
        num_lines = len(lines)
        i = 0

        while i < num_lines:
            if len(headers) >= self.limit_request_fields:
                raise LimitRequestHeaders("limit request headers fields")

            curr = lines[i]
            i += 1
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

            # Handle obsolete folding
            while i < num_lines and lines[i].startswith((" ", "\t")):
                if not self.cfg.permit_obsolete_folding:
                    raise ObsoleteFolding(name)
                curr = lines[i]
                i += 1
                header_length += len(curr) + len("\r\n")
                if header_length > self.limit_request_field_size > 0:
                    raise LimitRequestHeaders("limit request headers fields size")
                value.append(curr.strip("\t "))

            value = " ".join(value)

            if RFC9110_5_5_INVALID_AND_DANGEROUS.search(value):
                raise InvalidHeader(name)

            if header_length > self.limit_request_field_size > 0:
                raise LimitRequestHeaders("limit request headers fields size")

            # Handle underscore in header names
            if "_" in name:
                forwarder_headers = self.cfg.forwarder_headers
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

    def _apply_scheme_headers(self, result):
        """Apply scheme headers from trusted proxy."""
        if not isinstance(self.peer_addr, tuple):
            return

        # Use pre-computed trusted proxy check (avoids IP parsing on every request)
        if not self._is_trusted_proxy:
            return

        secure_scheme_headers = self.cfg.secure_scheme_headers
        scheme_header = False

        for name, value in result.headers:
            if name == "EXPECT":
                if value.lower() == "100-continue":
                    if result.version >= (1, 1):
                        result.expect_100_continue = True
                else:
                    raise ExpectationFailed(value)

            if name in secure_scheme_headers:
                secure = value == secure_scheme_headers[name]
                scheme = "https" if secure else "http"
                if scheme_header:
                    if scheme != result.scheme:
                        raise InvalidSchemeHeaders()
                else:
                    scheme_header = True
                    result.scheme = scheme

    def _parse_body_info(self, result):
        """Parse Content-Length and Transfer-Encoding from headers."""
        chunked = False
        content_length = None

        for name, value in result.headers:
            if name == "CONTENT-LENGTH":
                if content_length is not None:
                    raise InvalidHeader("CONTENT-LENGTH")
                content_length = value

            elif name == "TRANSFER-ENCODING":
                vals = [v.strip() for v in value.split(',')]
                for val in vals:
                    if val.lower() == "chunked":
                        if chunked:
                            raise InvalidHeader("TRANSFER-ENCODING")
                        chunked = True
                    elif val.lower() == "identity":
                        if chunked:
                            raise InvalidHeader("TRANSFER-ENCODING")
                    elif val.lower() in ('compress', 'deflate', 'gzip'):
                        if chunked:
                            raise InvalidHeader("TRANSFER-ENCODING")
                        result.must_close = True
                    else:
                        raise UnsupportedTransferCoding(value)

        if chunked:
            if result.version < (1, 1):
                raise InvalidHeader("TRANSFER-ENCODING")
            if content_length is not None:
                raise InvalidHeader("CONTENT-LENGTH")
            result.chunked = True
            result.content_length = -1
        elif content_length is not None:
            try:
                if str(content_length).isnumeric():
                    result.content_length = int(content_length)
                else:
                    raise InvalidHeader("CONTENT-LENGTH")
            except ValueError:
                raise InvalidHeader("CONTENT-LENGTH")

            if result.content_length < 0:
                raise InvalidHeader("CONTENT-LENGTH")
        else:
            result.content_length = 0

    def _should_keep_alive(self, result):
        """Determine if connection should be kept alive."""
        if result.must_close:
            return False

        for name, value in result.headers:
            if name == "CONNECTION":
                v = value.lower().strip(" \t")
                if v == "close":
                    return False
                elif v == "keep-alive":
                    return True
                break

        return result.version > (1, 0)

    def reset(self):
        """Reset parser state for next request on keep-alive connection."""
        self._result = None
        self.req_number += 1


class FastAsyncRequest:
    """Fast async HTTP request wrapper.

    Wraps a ParseResult from HttpParser and provides async body reading.
    This is a lightweight adapter that allows protocol.py to use the fast
    parser while maintaining compatibility with the existing interface.
    """

    __slots__ = (
        'method', 'uri', 'path', 'query', 'fragment', 'version',
        'headers', 'headers_bytes', 'scheme', 'content_length', 'chunked',
        'must_close', 'proxy_protocol_info',
        '_reader', '_buffer', '_body_remaining', '_body_reader',
        '_expect_100_continue',
    )

    def __init__(self, parse_result, reader, buffer, consumed):
        """Initialize from a ParseResult.

        Args:
            parse_result: ParseResult from HttpParser.feed()
            reader: asyncio.StreamReader for body reading
            buffer: bytearray buffer with remaining data after headers
            consumed: bytes consumed from buffer by parser
        """
        # Copy attributes from ParseResult
        self.method = parse_result.method
        self.uri = parse_result.uri
        self.path = parse_result.path
        self.query = parse_result.query
        self.fragment = parse_result.fragment
        self.version = parse_result.version
        self.headers = parse_result.headers
        self.headers_bytes = parse_result.headers_bytes  # Pre-computed bytes headers
        self.scheme = parse_result.scheme
        self.content_length = parse_result.content_length
        self.chunked = parse_result.chunked
        self.must_close = parse_result.must_close
        self.proxy_protocol_info = parse_result.proxy_protocol_info
        self._expect_100_continue = parse_result.expect_100_continue

        # Body reading state
        self._reader = reader
        # Keep remaining data after headers in buffer
        self._buffer = bytearray(buffer[consumed:])
        if self.chunked:
            self._body_remaining = -1
        elif self.content_length:
            self._body_remaining = self.content_length
        else:
            self._body_remaining = 0
        self._body_reader = None

    def should_close(self):
        """Check if connection should be closed after this request."""
        if self.must_close:
            return True
        for name, value in self.headers:
            if name == "CONNECTION":
                v = value.lower().strip(" \t")
                if v == "close":
                    return True
                elif v == "keep-alive":
                    return False
                break
        return self.version <= (1, 0)

    def get_header(self, name):
        """Get a header value by name (case-insensitive)."""
        name = name.upper()
        for h, v in self.headers:
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

        # First, use data from our buffer
        if self._buffer:
            if len(self._buffer) <= to_read:
                data = bytes(self._buffer)
                self._buffer.clear()
            else:
                data = bytes(self._buffer[:to_read])
                del self._buffer[:to_read]
            self._body_remaining -= len(data)
            return data

        # Read from stream
        try:
            data = await self._reader.read(to_read)
            if data:
                self._body_remaining -= len(data)
            return data
        except Exception:
            return b""

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
            size_line = await self._read_until_crlf()
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
                data = await self._read_data(min(remaining, 8192))
                if not data:
                    raise NoMoreData()
                remaining -= len(data)
                yield data

            # Skip chunk terminating CRLF
            crlf = await self._read_data(2)
            if crlf != b"\r\n":
                # May have partial read
                while len(crlf) < 2:
                    more = await self._read_data(2 - len(crlf))
                    if not more:
                        break
                    crlf += more

    async def _read_data(self, size):
        """Read data from buffer or stream."""
        if self._buffer:
            if len(self._buffer) <= size:
                data = bytes(self._buffer)
                self._buffer.clear()
                return data
            else:
                data = bytes(self._buffer[:size])
                del self._buffer[:size]
                return data
        try:
            return await self._reader.read(size)
        except Exception:
            return b""

    async def _read_until_crlf(self):
        """Read bytes until CRLF."""
        result = bytearray()
        while True:
            # Check buffer first
            if self._buffer:
                idx = self._buffer.find(b"\r\n")
                if idx >= 0:
                    result.extend(self._buffer[:idx])
                    del self._buffer[:idx + 2]
                    return bytes(result)
                result.extend(self._buffer)
                self._buffer.clear()

            # Read more data
            try:
                data = await self._reader.read(64)
            except Exception:
                break
            if not data:
                break
            idx = data.find(b"\r\n")
            if idx >= 0:
                result.extend(data[:idx])
                # Put remaining data back in buffer
                remaining = data[idx + 2:]
                if remaining:
                    self._buffer.extend(remaining)
                return bytes(result)
            result.extend(data)

        return bytes(result)

    async def _skip_trailers(self):
        """Skip trailer headers after chunked body."""
        while True:
            line = await self._read_until_crlf()
            if not line:
                return

    async def drain_body(self):
        """Drain any unread body data."""
        while True:
            data = await self.read_body(8192)
            if not data:
                break
