#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import io

from gunicorn.http.body import LengthReader, Body
from gunicorn.fastcgi.constants import (
    FCGI_VERSION_1,
    FCGI_BEGIN_REQUEST,
    FCGI_PARAMS,
    FCGI_STDIN,
    FCGI_HEADER_LEN,
    FCGI_RESPONDER,
    FCGI_KEEP_CONN,
    MAX_FCGI_PARAMS,
    FCGI_RECORD_TYPES,
)
from gunicorn.fastcgi.errors import (
    InvalidFastCGIRecord,
    UnsupportedRole,
    ForbiddenFastCGIRequest,
)


class FastCGIRequest:
    """FastCGI protocol request parser.

    The FastCGI protocol uses 8-byte record headers:
    - Byte 0: version (1)
    - Byte 1: type (record type)
    - Bytes 2-3: requestId (16-bit big-endian)
    - Bytes 4-5: contentLength (16-bit big-endian)
    - Byte 6: paddingLength
    - Byte 7: reserved

    Request parsing flow:
    1. Read BEGIN_REQUEST record -> extract role, flags, requestId
    2. Read PARAMS records until empty -> accumulate, parse name-value pairs
    3. Read STDIN records until empty -> accumulate as body
    4. Extract method/path/headers from fcgi_vars
    """

    def __init__(self, cfg, unreader, peer_addr, req_number=1):
        self.cfg = cfg
        self.unreader = unreader
        self.peer_addr = peer_addr
        self.remote_addr = peer_addr
        self.req_number = req_number

        # Request attributes (compatible with HTTP Request interface)
        self.method = None
        self.uri = None
        self.path = None
        self.query = None
        self.fragment = ""
        self.version = (1, 1)  # FastCGI is HTTP/1.1 compatible
        self.headers = []
        self.trailers = []
        self.body = None
        self.scheme = "https" if cfg.is_ssl else "http"
        self.must_close = False

        # FastCGI specific
        self.fcgi_vars = {}
        self.request_id = 0
        self.role = FCGI_RESPONDER
        self.flags = 0
        self.keep_conn = False

        # Proxy protocol compatibility
        self.proxy_protocol_info = None

        # Check if the source IP is allowed
        self._check_allowed_ip()

        # Parse the request
        self.parse(self.unreader)
        self.set_body_reader()

    def _check_allowed_ip(self):
        """Verify source IP is in the allowed list."""
        allow_ips = getattr(self.cfg, 'fastcgi_allow_ips', ['127.0.0.1', '::1'])

        # UNIX sockets don't have IP addresses
        if not isinstance(self.peer_addr, tuple):
            return

        # Wildcard allows all
        if '*' in allow_ips:
            return

        if self.peer_addr[0] not in allow_ips:
            raise ForbiddenFastCGIRequest(self.peer_addr[0])

    def force_close(self):
        """Force the connection to close after this request."""
        self.must_close = True

    def parse(self, unreader):
        """Parse FastCGI records to build the request."""
        # Step 1: Read BEGIN_REQUEST record
        self._read_begin_request(unreader)

        # Step 2: Read PARAMS records until empty
        self._read_params(unreader)

        # Step 3: Extract HTTP request info from params
        self._extract_request_info()

        # Note: STDIN is handled by set_body_reader() via the unreader

    def _read_record_header(self, unreader):
        """Read and parse an 8-byte FastCGI record header.

        Returns:
            tuple: (version, record_type, request_id, content_length, padding_length)
        """
        header = self._read_exact(unreader, FCGI_HEADER_LEN)
        if len(header) < FCGI_HEADER_LEN:
            raise InvalidFastCGIRecord("incomplete header")

        version = header[0]
        record_type = header[1]
        request_id = int.from_bytes(header[2:4], 'big')
        content_length = int.from_bytes(header[4:6], 'big')
        padding_length = header[6]
        # header[7] is reserved

        if version != FCGI_VERSION_1:
            raise InvalidFastCGIRecord("unsupported version: %d" % version)

        return version, record_type, request_id, content_length, padding_length

    def _read_record_content(self, unreader, content_length, padding_length):
        """Read record content and padding.

        Returns:
            bytes: The content (padding is discarded)
        """
        content = b""
        if content_length > 0:
            content = self._read_exact(unreader, content_length)
            if len(content) < content_length:
                raise InvalidFastCGIRecord("incomplete content")

        # Discard padding
        if padding_length > 0:
            padding = self._read_exact(unreader, padding_length)
            if len(padding) < padding_length:
                raise InvalidFastCGIRecord("incomplete padding")

        return content

    def _read_begin_request(self, unreader):
        """Read and parse the BEGIN_REQUEST record."""
        _, record_type, request_id, content_length, padding_length = \
            self._read_record_header(unreader)

        if record_type != FCGI_BEGIN_REQUEST:
            raise InvalidFastCGIRecord(
                "expected BEGIN_REQUEST, got %s" %
                FCGI_RECORD_TYPES.get(record_type, record_type)
            )

        if content_length < 8:
            raise InvalidFastCGIRecord("BEGIN_REQUEST content too short")

        content = self._read_record_content(unreader, content_length, padding_length)

        # Parse BEGIN_REQUEST body: role (2 BE), flags (1), reserved (5)
        self.request_id = request_id
        self.role = int.from_bytes(content[0:2], 'big')
        self.flags = content[2]
        self.keep_conn = bool(self.flags & FCGI_KEEP_CONN)

        # Only RESPONDER role is supported
        if self.role != FCGI_RESPONDER:
            raise UnsupportedRole(self.role)

    def _read_params(self, unreader):
        """Read PARAMS records until empty record received."""
        params_data = io.BytesIO()

        while True:
            _, record_type, request_id, content_length, padding_length = \
                self._read_record_header(unreader)

            if record_type != FCGI_PARAMS:
                raise InvalidFastCGIRecord(
                    "expected PARAMS, got %s" %
                    FCGI_RECORD_TYPES.get(record_type, record_type)
                )

            # Verify request_id matches
            if request_id != self.request_id:
                raise InvalidFastCGIRecord(
                    "request_id mismatch: expected %d, got %d" %
                    (self.request_id, request_id)
                )

            # Empty PARAMS record signals end of parameters
            if content_length == 0:
                break

            content = self._read_record_content(unreader, content_length, padding_length)
            params_data.write(content)

        # Parse the accumulated params data
        self._parse_name_value_pairs(params_data.getvalue())

    def _parse_name_value_pairs(self, data):
        """Parse FastCGI name-value pairs from accumulated PARAMS data.

        Name-value pair format:
        - nameLength (1 or 4 bytes)
        - valueLength (1 or 4 bytes)
        - name (nameLength bytes)
        - value (valueLength bytes)

        Length encoding:
        - If high bit is 0: 1-byte length (0-127)
        - If high bit is 1: 4-byte big-endian with high bit cleared
        """
        pos = 0
        param_count = 0

        while pos < len(data):
            if param_count >= MAX_FCGI_PARAMS:
                raise InvalidFastCGIRecord("too many parameters")

            # Read name length
            name_length, pos = self._decode_length(data, pos)

            # Read value length
            value_length, pos = self._decode_length(data, pos)

            # Read name
            if pos + name_length > len(data):
                raise InvalidFastCGIRecord("truncated parameter name")
            name = data[pos:pos + name_length].decode('latin-1')
            pos += name_length

            # Read value
            if pos + value_length > len(data):
                raise InvalidFastCGIRecord("truncated parameter value")
            value = data[pos:pos + value_length].decode('latin-1')
            pos += value_length

            self.fcgi_vars[name] = value
            param_count += 1

    def _decode_length(self, data, pos):
        """Decode a FastCGI variable-length integer.

        Args:
            data: bytes buffer
            pos: current position in buffer

        Returns:
            tuple: (length_value, new_position)
        """
        if pos >= len(data):
            raise InvalidFastCGIRecord("truncated length field")

        byte0 = data[pos]
        if byte0 >> 7 == 0:
            # 1-byte length (0-127)
            return byte0, pos + 1
        else:
            # 4-byte length (high bit cleared)
            if pos + 4 > len(data):
                raise InvalidFastCGIRecord("truncated 4-byte length field")
            length = int.from_bytes(data[pos:pos + 4], 'big') & 0x7FFFFFFF
            return length, pos + 4

    def _read_exact(self, unreader, size):
        """Read exactly size bytes from the unreader."""
        buf = io.BytesIO()
        remaining = size

        while remaining > 0:
            data = unreader.read()
            if not data:
                break
            buf.write(data)
            remaining = size - buf.tell()

        result = buf.getvalue()
        # Put back any extra bytes
        if len(result) > size:
            unreader.unread(result[size:])
            result = result[:size]

        return result

    def _extract_request_info(self):
        """Extract HTTP request info from FastCGI params.

        Header Mapping (CGI/WSGI to HTTP):

        The FastCGI protocol passes HTTP headers using CGI-style environment
        variable naming. This method converts them back to HTTP header format:

        - HTTP_* vars: Strip 'HTTP_' prefix, replace '_' with '-'
          Example: HTTP_X_FORWARDED_FOR -> X-FORWARDED-FOR
          Example: HTTP_ACCEPT_ENCODING -> ACCEPT-ENCODING

        - CONTENT_TYPE: Mapped directly to CONTENT-TYPE header
          (CGI spec excludes HTTP_ prefix for this header)

        - CONTENT_LENGTH: Mapped directly to CONTENT-LENGTH header
          (CGI spec excludes HTTP_ prefix for this header)

        Note: The underscore-to-hyphen conversion is lossy. Headers that
        originally contained underscores (e.g., X_Custom_Header) cannot be
        distinguished from hyphenated headers (X-Custom-Header) after
        passing through nginx/FastCGI. This is a CGI/WSGI specification
        limitation, not specific to this implementation.
        """
        # Method
        self.method = self.fcgi_vars.get('REQUEST_METHOD', 'GET')

        # URI and path
        self.path = self.fcgi_vars.get('PATH_INFO', '/')
        self.query = self.fcgi_vars.get('QUERY_STRING', '')

        # Build URI
        if self.query:
            self.uri = "%s?%s" % (self.path, self.query)
        else:
            self.uri = self.path

        # Scheme
        if self.fcgi_vars.get('HTTPS', '').lower() in ('on', '1', 'true'):
            self.scheme = 'https'
        elif 'wsgi.url_scheme' in self.fcgi_vars:
            self.scheme = self.fcgi_vars['wsgi.url_scheme']

        # Extract HTTP headers from CGI-style vars
        # See docstring above for mapping details
        for key, value in self.fcgi_vars.items():
            if key.startswith('HTTP_'):
                # Convert HTTP_HEADER_NAME to HEADER-NAME
                header_name = key[5:].replace('_', '-')
                self.headers.append((header_name, value))
            elif key == 'CONTENT_TYPE':
                self.headers.append(('CONTENT-TYPE', value))
            elif key == 'CONTENT_LENGTH':
                self.headers.append(('CONTENT-LENGTH', value))

    def set_body_reader(self):
        """Set up the body reader for STDIN data.

        FastCGI STDIN records are read on-demand through the unreader.
        We use a FastCGIBodyReader to handle the record framing.
        """
        content_length = 0

        # Get content length from params
        if 'CONTENT_LENGTH' in self.fcgi_vars:
            try:
                content_length = max(int(self.fcgi_vars['CONTENT_LENGTH']), 0)
            except ValueError:
                content_length = 0

        # Create a body reader that handles FastCGI STDIN records
        body_reader = FastCGIBodyReader(self.unreader, self.request_id, content_length)
        self.body = Body(body_reader)

    def should_close(self):
        """Determine if the connection should be closed after this request."""
        if self.must_close:
            return True

        # FastCGI keep_conn flag determines connection persistence
        if self.keep_conn:
            return False

        # Check HTTP_CONNECTION header as fallback
        connection = self.fcgi_vars.get('HTTP_CONNECTION', '').lower()
        if connection == 'close':
            return True
        elif connection == 'keep-alive':
            return False

        # Default: close connection if keep_conn not set
        return True


class RequestState:
    """State for a single FastCGI request during multiplexed parsing.

    Tracks the accumulated data for a request until it's complete.
    """

    def __init__(self, request_id, role, flags):
        self.request_id = request_id
        self.role = role
        self.flags = flags
        self.keep_conn = bool(flags & FCGI_KEEP_CONN)

        # Accumulated data
        self.params_data = io.BytesIO()
        self.stdin_data = io.BytesIO()

        # Completion flags
        self.params_complete = False
        self.stdin_complete = False

    def add_params(self, data):
        """Add PARAMS data. Empty data signals completion."""
        if not data:
            self.params_complete = True
        else:
            self.params_data.write(data)

    def add_stdin(self, data):
        """Add STDIN data. Empty data signals completion."""
        if not data:
            self.stdin_complete = True
        else:
            self.stdin_data.write(data)

    def is_ready(self):
        """Check if the request is complete and ready to process."""
        return self.params_complete and self.stdin_complete

    def get_params_data(self):
        """Get accumulated params data."""
        return self.params_data.getvalue()

    def get_stdin_data(self):
        """Get accumulated stdin data."""
        return self.stdin_data.getvalue()


class FastCGIConnectionState:
    """Tracks multiple concurrent FastCGI requests on a single connection.

    Used for multiplexing support where multiple requests can be interleaved
    on the same connection. Records are dispatched by requestId.

    Usage:
        state = FastCGIConnectionState()
        while True:
            record = read_record(unreader)
            state.handle_record(record)
            for request_id in state.get_ready_requests():
                req_state = state.pop_request(request_id)
                # Process req_state
    """

    def __init__(self, cfg, peer_addr):
        self.cfg = cfg
        self.peer_addr = peer_addr
        self.requests = {}  # requestId -> RequestState
        self._check_allowed_ip()

    def _check_allowed_ip(self):
        """Verify source IP is in the allowed list."""
        allow_ips = getattr(self.cfg, 'fastcgi_allow_ips', ['127.0.0.1', '::1'])

        # UNIX sockets don't have IP addresses
        if not isinstance(self.peer_addr, tuple):
            return

        # Wildcard allows all
        if '*' in allow_ips:
            return

        if self.peer_addr[0] not in allow_ips:
            raise ForbiddenFastCGIRequest(self.peer_addr[0])

    def begin_request(self, request_id, role, flags):
        """Handle a BEGIN_REQUEST record.

        Args:
            request_id: The request ID
            role: FastCGI role (must be RESPONDER)
            flags: FastCGI flags

        Raises:
            UnsupportedRole: If role is not RESPONDER
            InvalidFastCGIRecord: If request_id already exists
        """
        if role != FCGI_RESPONDER:
            raise UnsupportedRole(role)

        if request_id in self.requests:
            raise InvalidFastCGIRecord(
                "duplicate request_id: %d" % request_id
            )

        self.requests[request_id] = RequestState(request_id, role, flags)

    def add_params(self, request_id, data):
        """Add PARAMS data for a request.

        Args:
            request_id: The request ID
            data: Parameter data (empty signals end)

        Raises:
            InvalidFastCGIRecord: If request_id not found
        """
        if request_id not in self.requests:
            raise InvalidFastCGIRecord(
                "unknown request_id for PARAMS: %d" % request_id
            )
        self.requests[request_id].add_params(data)

    def add_stdin(self, request_id, data):
        """Add STDIN data for a request.

        Args:
            request_id: The request ID
            data: Body data (empty signals end)

        Raises:
            InvalidFastCGIRecord: If request_id not found
        """
        if request_id not in self.requests:
            raise InvalidFastCGIRecord(
                "unknown request_id for STDIN: %d" % request_id
            )
        self.requests[request_id].add_stdin(data)

    def get_ready_requests(self):
        """Get list of request IDs that are complete and ready to process.

        Returns:
            list: Request IDs with complete params and stdin
        """
        return [
            req_id for req_id, state in self.requests.items()
            if state.is_ready()
        ]

    def pop_request(self, request_id):
        """Remove and return a request state.

        Args:
            request_id: The request ID to pop

        Returns:
            RequestState: The request state

        Raises:
            KeyError: If request_id not found
        """
        return self.requests.pop(request_id)

    def has_pending_requests(self):
        """Check if there are any pending requests."""
        return bool(self.requests)

    def build_request(self, req_state, unreader, req_number=1):
        """Build a FastCGIRequest from a completed RequestState.

        Args:
            req_state: The RequestState with accumulated data
            unreader: The unreader for body reading
            req_number: Request number for logging

        Returns:
            FastCGIRequest: The parsed request
        """
        return FastCGIRequestFromState(
            self.cfg, req_state, unreader, self.peer_addr, req_number
        )


class FastCGIRequestFromState(FastCGIRequest):
    """FastCGI request built from pre-parsed RequestState.

    Used in multiplexing mode where records have already been accumulated
    by FastCGIConnectionState.
    """

    def __init__(self, cfg, req_state, unreader, peer_addr, req_number=1):
        # Don't call parent __init__ - we'll initialize manually
        self.cfg = cfg
        self.unreader = unreader
        self.peer_addr = peer_addr
        self.remote_addr = peer_addr
        self.req_number = req_number

        # Request attributes (compatible with HTTP Request interface)
        self.method = None
        self.uri = None
        self.path = None
        self.query = None
        self.fragment = ""
        self.version = (1, 1)
        self.headers = []
        self.trailers = []
        self.body = None
        self.scheme = "https" if cfg.is_ssl else "http"
        self.must_close = False

        # FastCGI specific - copy from state
        self.fcgi_vars = {}
        self.request_id = req_state.request_id
        self.role = req_state.role
        self.flags = req_state.flags
        self.keep_conn = req_state.keep_conn

        # Proxy protocol compatibility
        self.proxy_protocol_info = None

        # Parse the accumulated data
        self._parse_name_value_pairs(req_state.get_params_data())
        self._extract_request_info()

        # Set up body from accumulated stdin data
        stdin_data = req_state.get_stdin_data()
        self.body = Body(BufferedBodyReader(stdin_data))


class BufferedBodyReader:
    """Body reader for pre-buffered data.

    Used when body data has already been accumulated (multiplexing mode).
    """

    def __init__(self, data):
        self.buffer = io.BytesIO(data)
        self.length = len(data)

    def read(self, size=None):
        """Read up to size bytes from the buffered data."""
        if size is None:
            return self.buffer.read()
        return self.buffer.read(size)


class FastCGIBodyReader:
    """Reader for FastCGI STDIN records.

    Reads STDIN records from the unreader and provides the body content.
    Handles the FastCGI record framing transparently.
    """

    def __init__(self, unreader, request_id, content_length):
        self.unreader = unreader
        self.request_id = request_id
        self.content_length = content_length
        self.bytes_read = 0
        self.buffer = b""
        self.eof = False

    def read(self, size=None):
        """Read up to size bytes from the body."""
        if self.eof:
            return b""

        # Determine how much to read
        remaining = self.content_length - self.bytes_read
        if remaining <= 0:
            self.eof = True
            return b""

        if size is None:
            size = remaining
        else:
            size = min(size, remaining)

        result = b""

        while len(result) < size and not self.eof:
            # First use buffered data
            if self.buffer:
                chunk_size = min(len(self.buffer), size - len(result))
                result += self.buffer[:chunk_size]
                self.buffer = self.buffer[chunk_size:]
                continue

            # Need to read more STDIN records
            if not self._read_stdin_record():
                self.eof = True
                break

        self.bytes_read += len(result)
        return result

    def _read_stdin_record(self):
        """Read the next STDIN record.

        Returns:
            bool: True if data was read, False if end of STDIN
        """
        # Read header
        header = self._read_exact(FCGI_HEADER_LEN)
        if len(header) < FCGI_HEADER_LEN:
            return False

        version = header[0]
        record_type = header[1]
        request_id = int.from_bytes(header[2:4], 'big')
        content_length = int.from_bytes(header[4:6], 'big')
        padding_length = header[6]

        if version != FCGI_VERSION_1:
            raise InvalidFastCGIRecord("unsupported version: %d" % version)

        if record_type != FCGI_STDIN:
            raise InvalidFastCGIRecord(
                "expected STDIN, got %s" %
                FCGI_RECORD_TYPES.get(record_type, record_type)
            )

        if request_id != self.request_id:
            raise InvalidFastCGIRecord(
                "request_id mismatch: expected %d, got %d" %
                (self.request_id, request_id)
            )

        # Empty STDIN record signals end of body
        if content_length == 0:
            return False

        # Read content
        content = self._read_exact(content_length)
        if len(content) < content_length:
            raise InvalidFastCGIRecord("incomplete STDIN content")

        # Discard padding
        if padding_length > 0:
            padding = self._read_exact(padding_length)
            if len(padding) < padding_length:
                raise InvalidFastCGIRecord("incomplete STDIN padding")

        self.buffer += content
        return True

    def _read_exact(self, size):
        """Read exactly size bytes from the unreader."""
        buf = io.BytesIO()
        remaining = size

        while remaining > 0:
            data = self.unreader.read()
            if not data:
                break
            buf.write(data)
            remaining = size - buf.tell()

        result = buf.getvalue()
        if len(result) > size:
            self.unreader.unread(result[size:])
            result = result[:size]

        return result
