#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
HTTP parser for ASGI workers.

Provides callback-based parsing using either the fast C parser (gunicorn_h1c)
or the pure Python PythonProtocol fallback.
"""


class ParseError(Exception):
    """Error raised during HTTP parsing."""
    pass


class PythonProtocol:
    """Callback-based HTTP/1.1 parser (pure Python fallback).

    Mirrors H1CProtocol interface for seamless switching between
    the C extension and pure Python implementations.

    Callbacks:
        on_message_begin: () -> None - Called when request starts
        on_url: (url: bytes) -> None - Called with request URL/path
        on_header: (name: bytes, value: bytes) -> None - Called for each header
        on_headers_complete: () -> bool - Called when headers done (return True to skip body)
        on_body: (chunk: bytes) -> None - Called with body data chunks
        on_message_complete: () -> None - Called when request is complete
    """

    __slots__ = (
        '_on_message_begin', '_on_url', '_on_header',
        '_on_headers_complete', '_on_body', '_on_message_complete',
        '_state', '_buffer', '_headers_list',
        'method', 'path', 'http_version', 'headers',
        'content_length', 'is_chunked', 'should_keep_alive', 'is_complete',
        '_body_remaining', '_skip_body',
        '_chunk_state', '_chunk_size', '_chunk_remaining',
    )

    def __init__(
        self,
        on_message_begin=None,
        on_url=None,
        on_header=None,
        on_headers_complete=None,
        on_body=None,
        on_message_complete=None,
    ):
        self._on_message_begin = on_message_begin
        self._on_url = on_url
        self._on_header = on_header
        self._on_headers_complete = on_headers_complete
        self._on_body = on_body
        self._on_message_complete = on_message_complete

        # Parser state: request_line, headers, body, chunked_size, chunked_data, complete
        self._state = 'request_line'
        self._buffer = bytearray()
        self._headers_list = []

        # Request info (populated during parsing)
        self.method = None
        self.path = None
        self.http_version = None
        self.headers = []
        self.content_length = None
        self.is_chunked = False
        self.should_keep_alive = True
        self.is_complete = False

        # Body state
        self._body_remaining = 0
        self._skip_body = False

        # Chunked transfer state
        self._chunk_state = 'size'  # size, data, trailer
        self._chunk_size = 0
        self._chunk_remaining = 0

    def feed(self, data):
        """Process data, fire callbacks synchronously.

        Args:
            data: bytes or bytearray of incoming data

        Raises:
            ParseError: If the HTTP request is malformed
        """
        self._buffer.extend(data)

        while self._buffer:
            if self._state == 'request_line':
                if not self._parse_request_line():
                    break
            elif self._state == 'headers':
                if not self._parse_headers():
                    break
            elif self._state == 'body':
                if not self._parse_body():
                    break
            elif self._state == 'chunked':
                if not self._parse_chunked_body():
                    break
            else:
                break

    def reset(self):
        """Reset for next request (keepalive)."""
        self._state = 'request_line'
        self._buffer.clear()
        self._headers_list = []
        self.method = None
        self.path = None
        self.http_version = None
        self.headers = []
        self.content_length = None
        self.is_chunked = False
        self.should_keep_alive = True
        self.is_complete = False
        self._body_remaining = 0
        self._skip_body = False
        self._chunk_state = 'size'
        self._chunk_size = 0
        self._chunk_remaining = 0

    def _parse_request_line(self):
        """Parse request line, return True if complete."""
        idx = self._buffer.find(b'\r\n')
        if idx == -1:
            return False

        line = bytes(self._buffer[:idx])
        del self._buffer[:idx + 2]

        # Parse: METHOD PATH HTTP/x.y
        parts = line.split(b' ', 2)
        if len(parts) != 3:
            raise ParseError("Invalid request line")

        self.method = parts[0]
        self.path = parts[1]

        # Parse version
        version = parts[2]
        if version == b'HTTP/1.1':
            self.http_version = (1, 1)
        elif version == b'HTTP/1.0':
            self.http_version = (1, 0)
        else:
            raise ParseError("Unsupported HTTP version")

        if self._on_message_begin:
            self._on_message_begin()
        if self._on_url:
            self._on_url(self.path)

        self._state = 'headers'
        return True

    def _parse_headers(self):
        """Parse headers, return True if headers are complete."""
        while True:
            idx = self._buffer.find(b'\r\n')
            if idx == -1:
                return False

            line = bytes(self._buffer[:idx])
            del self._buffer[:idx + 2]

            if not line:
                # Empty line = end of headers
                self._finalize_headers()
                return True

            # Parse header
            colon = line.find(b':')
            if colon == -1:
                raise ParseError("Invalid header")

            name = line[:colon].strip().lower()
            value = line[colon + 1:].strip()

            self._headers_list.append((name, value))

            if self._on_header:
                self._on_header(name, value)

    def _finalize_headers(self):
        """Called when all headers received."""
        self.headers = self._headers_list

        # Extract content-length and chunked
        for name, value in self.headers:
            if name == b'content-length':
                self.content_length = int(value)
                self._body_remaining = self.content_length
            elif name == b'transfer-encoding':
                self.is_chunked = b'chunked' in value.lower()
            elif name == b'connection':
                val = value.lower()
                if b'close' in val:
                    self.should_keep_alive = False
                elif b'keep-alive' in val:
                    self.should_keep_alive = True

        # HTTP/1.0 defaults to close
        if self.http_version == (1, 0) and self.should_keep_alive:
            # Only keep-alive if explicitly requested
            has_keepalive = any(
                name == b'connection' and b'keep-alive' in value.lower()
                for name, value in self.headers
            )
            if not has_keepalive:
                self.should_keep_alive = False

        if self._on_headers_complete:
            self._skip_body = self._on_headers_complete()

        # Determine next state
        if self._skip_body:
            self._state = 'complete'
            self.is_complete = True
            if self._on_message_complete:
                self._on_message_complete()
        elif self.is_chunked:
            self._state = 'chunked'
            self._chunk_state = 'size'
        elif self.content_length and self.content_length > 0:
            self._state = 'body'
        else:
            # No body
            self._state = 'complete'
            self.is_complete = True
            if self._on_message_complete:
                self._on_message_complete()

    def _parse_body(self):
        """Parse Content-Length delimited body."""
        if not self._buffer or self._body_remaining <= 0:
            return False

        chunk_size = min(len(self._buffer), self._body_remaining)
        chunk = bytes(self._buffer[:chunk_size])
        del self._buffer[:chunk_size]
        self._body_remaining -= chunk_size

        if self._on_body:
            self._on_body(chunk)

        if self._body_remaining <= 0:
            self._state = 'complete'
            self.is_complete = True
            if self._on_message_complete:
                self._on_message_complete()

        return True

    def _parse_chunked_body(self):
        """Parse chunked transfer encoding."""
        while self._buffer:
            if self._chunk_state == 'size':
                # Looking for chunk size line
                idx = self._buffer.find(b'\r\n')
                if idx == -1:
                    return False

                size_line = bytes(self._buffer[:idx])
                del self._buffer[:idx + 2]

                # Handle chunk extensions (e.g., "5;ext=value")
                semicolon = size_line.find(b';')
                if semicolon != -1:
                    size_line = size_line[:semicolon].strip()

                try:
                    self._chunk_size = int(size_line, 16)
                except ValueError:
                    raise ParseError("Invalid chunk size")

                if self._chunk_size == 0:
                    # Final chunk - skip trailers
                    self._chunk_state = 'trailer'
                else:
                    self._chunk_remaining = self._chunk_size
                    self._chunk_state = 'data'

            elif self._chunk_state == 'data':
                # Reading chunk data
                if not self._buffer:
                    return False

                to_read = min(len(self._buffer), self._chunk_remaining)
                chunk = bytes(self._buffer[:to_read])
                del self._buffer[:to_read]
                self._chunk_remaining -= to_read

                if self._on_body:
                    self._on_body(chunk)

                if self._chunk_remaining == 0:
                    # Need to consume trailing CRLF
                    self._chunk_state = 'crlf'

            elif self._chunk_state == 'crlf':
                # Skip CRLF after chunk data
                if len(self._buffer) < 2:
                    return False
                del self._buffer[:2]  # Skip \r\n
                self._chunk_state = 'size'

            elif self._chunk_state == 'trailer':
                # Skip trailer headers
                idx = self._buffer.find(b'\r\n')
                if idx == -1:
                    return False

                line = bytes(self._buffer[:idx])
                del self._buffer[:idx + 2]

                if not line:
                    # Empty line = end of trailers
                    self._state = 'complete'
                    self.is_complete = True
                    if self._on_message_complete:
                        self._on_message_complete()
                    return True

        return False


class CallbackRequest:
    """Request object built from callback parser state.

    Works with both H1CProtocol (C extension) and PythonProtocol.
    """

    __slots__ = (
        'method', 'uri', 'path', 'query', 'fragment', 'version',
        'headers', 'headers_bytes', 'scheme',
        'content_length', 'chunked', 'must_close',
        'proxy_protocol_info', '_expect_100_continue',
    )

    def __init__(self):
        self.method = None
        self.uri = None
        self.path = None
        self.query = None
        self.fragment = None
        self.version = None
        self.headers = []
        self.headers_bytes = []
        self.scheme = "http"
        self.content_length = 0
        self.chunked = False
        self.must_close = False
        self.proxy_protocol_info = None
        self._expect_100_continue = False

    @classmethod
    def from_parser(cls, parser, is_ssl=False):
        """Build request from callback parser state.

        Args:
            parser: H1CProtocol or PythonProtocol instance
            is_ssl: Whether connection is SSL/TLS

        Returns:
            CallbackRequest instance
        """
        req = cls()
        req.method = parser.method.decode('ascii')

        # Parse path and query from URL
        raw_path = parser.path
        if b'?' in raw_path:
            path_part, query_part = raw_path.split(b'?', 1)
            req.path = path_part.decode('latin-1')
            req.query = query_part.decode('latin-1')
        else:
            req.path = raw_path.decode('latin-1')
            req.query = ''

        req.uri = raw_path.decode('latin-1')
        req.fragment = ''
        req.version = parser.http_version

        # Headers - store both bytes (for ASGI scope) and strings (for compatibility)
        req.headers_bytes = list(parser.headers)
        req.headers = [
            (n.decode('latin-1').upper(), v.decode('latin-1'))
            for n, v in parser.headers
        ]

        req.scheme = 'https' if is_ssl else 'http'
        req.content_length = parser.content_length or 0
        req.chunked = parser.is_chunked
        req.must_close = not parser.should_keep_alive

        # Check for Expect: 100-continue
        for name, value in parser.headers:
            if name == b'expect' and value.lower() == b'100-continue':
                req._expect_100_continue = True
                break

        return req

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
