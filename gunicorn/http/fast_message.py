#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Fast HTTP request parsing using gunicorn_h1c.

This module provides FastRequest, a drop-in replacement for Request that
uses the high-performance gunicorn_h1c parser (picohttpparser with SIMD).
"""

from gunicorn.http.body import ChunkedReader, LengthReader, Body
from gunicorn.http.errors import (
    InvalidHeader, InvalidHeaderName,
    InvalidRequestLine, InvalidRequestMethod, InvalidHTTPVersion,
    LimitRequestLine, LimitRequestHeaders,
    UnsupportedTransferCoding,
    ExpectationFailed,
)
from gunicorn.http.errors import ForbiddenProxyRequest
from gunicorn.http.errors import InvalidSchemeHeaders
from gunicorn.http.message import (
    Request, Message, _ip_in_allow_list,
    PP_V2_SIGNATURE, MAX_REQUEST_LINE, MAX_HEADERS, DEFAULT_MAX_HEADERFIELD_SIZE,
    TOKEN_RE, METHOD_BADCHAR_RE, VERSION_RE, RFC9110_5_5_INVALID_AND_DANGEROUS,
)
from gunicorn.http.parser import Parser
from gunicorn.http.fast_parser import get_h1c_module
from gunicorn.util import bytes_to_str, split_request_uri


class FastRequest(Request):
    """HTTP Request using the fast gunicorn_h1c parser.

    This class overrides the parse() method to use the high-performance
    C-based parser while preserving all validation and compatibility
    with the standard Request class.
    """

    def parse(self, unreader):
        """Parse HTTP request using the fast C parser."""
        h1c = get_h1c_module()
        buf = bytearray()
        self._read_into(unreader, buf, stop=True)

        # Handle proxy protocol if enabled and this is the first request
        mode = self.cfg.proxy_protocol
        if mode != "off" and self.req_number == 1:
            buf = self._handle_proxy_protocol(unreader, buf, mode)

        # Use fast parser to find end of headers
        # We need to accumulate enough data for a complete request
        while True:
            # Check for end of headers
            idx = buf.find(b"\r\n\r\n")
            if idx >= 0:
                break

            # Check limits
            if len(buf) > self.max_buffer_headers:
                raise LimitRequestHeaders("max buffer headers")

            self._read_into(unreader, buf)

        # Now we have complete headers, use fast parser
        header_end = idx + 4
        header_data = bytes(buf[:header_end])

        try:
            result = h1c.parse_request(header_data)
        except Exception as e:
            # Fast parser failed, raise appropriate error
            raise InvalidRequestLine(str(e))

        if result is None:
            raise InvalidRequestLine("Incomplete request")

        # Extract parsed values
        # gunicorn_h1c returns: method, path, minor_version, headers, consumed
        method = result['method']
        path = result['path']
        minor_version = result['minor_version']
        headers = result['headers']

        # Validate and set method
        self.method = method if isinstance(method, str) else method.decode('latin-1')

        if not self.cfg.permit_unconventional_http_method:
            if METHOD_BADCHAR_RE.search(self.method):
                raise InvalidRequestMethod(self.method)
            if not 3 <= len(self.method) <= 20:
                raise InvalidRequestMethod(self.method)
        if not TOKEN_RE.fullmatch(self.method):
            raise InvalidRequestMethod(self.method)
        if self.cfg.casefold_http_method:
            self.method = self.method.upper()

        # Validate and set URI
        self.uri = path if isinstance(path, str) else path.decode('latin-1')

        if len(self.uri) == 0:
            raise InvalidRequestLine("Empty URI")

        # Check request line limit (approximate - fast parser doesn't expose exact line length)
        request_line_len = len(self.method) + 1 + len(self.uri) + 10  # " HTTP/1.X"
        if request_line_len > self.limit_request_line > 0:
            raise LimitRequestLine(request_line_len, self.limit_request_line)

        try:
            parts = split_request_uri(self.uri)
        except ValueError:
            raise InvalidRequestLine(self.uri)
        self.path = parts.path or ""
        self.query = parts.query or ""
        self.fragment = parts.fragment or ""

        # Set version from minor_version (assumes HTTP/1.x)
        self.version = (1, minor_version)
        if not (1, 0) <= self.version < (2, 0):
            if not self.cfg.permit_unconventional_http_version:
                raise InvalidHTTPVersion(self.version)

        # Process headers
        self.headers = self._process_fast_headers(headers)

        # Return remaining data after headers
        return bytes(buf[header_end:])

    def _read_into(self, unreader, buf, stop=False):
        """Read data from unreader and append to bytearray buffer."""
        data = unreader.read()
        if not data:
            if stop:
                raise StopIteration()
            from gunicorn.http.errors import NoMoreData
            raise NoMoreData(bytes(buf))
        buf.extend(data)

    def _process_fast_headers(self, raw_headers):
        """Process headers from fast parser, applying all validations.

        Args:
            raw_headers: List of (name, value) tuples from fast parser.

        Returns:
            list: Processed headers as list of (name, value) string tuples.
        """
        cfg = self.cfg
        headers = []

        # Handle scheme headers
        scheme_header = False
        secure_scheme_headers = {}
        forwarder_headers = []
        if (not isinstance(self.peer_addr, tuple)
              or _ip_in_allow_list(self.peer_addr[0], cfg.forwarded_allow_ips,
                                   cfg.forwarded_allow_networks())):
            secure_scheme_headers = cfg.secure_scheme_headers
            forwarder_headers = cfg.forwarder_headers

        for raw_name, raw_value in raw_headers:
            if len(headers) >= self.limit_request_fields:
                raise LimitRequestHeaders("limit request headers fields")

            # Convert to strings if needed
            name = raw_name if isinstance(raw_name, str) else raw_name.decode('latin-1')
            value = raw_value if isinstance(raw_value, str) else raw_value.decode('latin-1')

            # Strip spaces if configured (dangerous, for compatibility only)
            if self.cfg.strip_header_spaces:
                name = name.rstrip(" \t")

            # Validate header name
            if not TOKEN_RE.fullmatch(name):
                raise InvalidHeaderName(name)

            name = name.upper()
            value = value.strip(" \t")

            # Check header field size limit
            header_length = len(name) + len(value) + 4  # name: value\r\n
            if header_length > self.limit_request_field_size > 0:
                raise LimitRequestHeaders("limit request headers fields size")

            # Validate header value
            if RFC9110_5_5_INVALID_AND_DANGEROUS.search(value):
                raise InvalidHeader(name)

            # Handle Expect header
            if name == "EXPECT":
                if value.lower() == "100-continue":
                    if self.version >= (1, 1):
                        self._expected_100_continue = True
                else:
                    raise ExpectationFailed(value)

            # Handle scheme headers
            if name in secure_scheme_headers:
                secure = value == secure_scheme_headers[name]
                scheme = "https" if secure else "http"
                if scheme_header:
                    if scheme != self.scheme:
                        raise InvalidSchemeHeaders()
                else:
                    scheme_header = True
                    self.scheme = scheme

            # Handle underscore in header names
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

    def set_body_reader(self):
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
            self.body = Body(LengthReader(self.unreader, 0))


class FastRequestParser(Parser):
    """Request parser using the fast gunicorn_h1c parser."""

    mesg_class = FastRequest
