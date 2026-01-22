#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import io

from gunicorn.http.body import LengthReader, Body
from gunicorn.uwsgi.errors import (
    InvalidUWSGIHeader,
    UnsupportedModifier,
    ForbiddenUWSGIRequest,
)


# Maximum number of variables to prevent DoS
MAX_UWSGI_VARS = 1000


class UWSGIRequest:
    """uWSGI protocol request parser.

    The uWSGI protocol uses a 4-byte binary header:
    - Byte 0: modifier1 (packet type, 0 = WSGI request)
    - Bytes 1-2: datasize (16-bit little-endian, size of vars block)
    - Byte 3: modifier2 (additional flags, typically 0)

    After the header:
    1. Vars block (datasize bytes): Key-value pairs containing WSGI environ
       - Each pair: 2-byte key_size (LE) + key + 2-byte val_size (LE) + value
    2. Request body (determined by CONTENT_LENGTH in vars)
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
        self.version = (1, 1)  # uWSGI is HTTP/1.1 compatible
        self.headers = []
        self.trailers = []
        self.body = None
        self.scheme = "https" if cfg.is_ssl else "http"
        self.must_close = False

        # uWSGI specific
        self.uwsgi_vars = {}
        self.modifier1 = 0
        self.modifier2 = 0

        # Proxy protocol compatibility
        self.proxy_protocol_info = None

        # Check if the source IP is allowed
        self._check_allowed_ip()

        # Parse the request
        unused = self.parse(self.unreader)
        self.unreader.unread(unused)
        self.set_body_reader()

    def _check_allowed_ip(self):
        """Verify source IP is in the allowed list."""
        allow_ips = getattr(self.cfg, 'uwsgi_allow_ips', ['127.0.0.1', '::1'])

        # UNIX sockets don't have IP addresses
        if not isinstance(self.peer_addr, tuple):
            return

        # Wildcard allows all
        if '*' in allow_ips:
            return

        if self.peer_addr[0] not in allow_ips:
            raise ForbiddenUWSGIRequest(self.peer_addr[0])

    def force_close(self):
        """Force the connection to close after this request."""
        self.must_close = True

    def parse(self, unreader):
        """Parse uWSGI packet header and vars block."""
        # Read the 4-byte header
        header = self._read_exact(unreader, 4)
        if len(header) < 4:
            raise InvalidUWSGIHeader("incomplete header")

        self.modifier1 = header[0]
        datasize = int.from_bytes(header[1:3], 'little')
        self.modifier2 = header[3]

        # Only modifier1=0 (WSGI request) is supported
        if self.modifier1 != 0:
            raise UnsupportedModifier(self.modifier1)

        # Read the vars block
        if datasize > 0:
            vars_data = self._read_exact(unreader, datasize)
            if len(vars_data) < datasize:
                raise InvalidUWSGIHeader("incomplete vars block")
            self._parse_vars(vars_data)

        # Extract HTTP request info from vars
        self._extract_request_info()

        return b""

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

    def _parse_vars(self, data):
        """Parse uWSGI vars block into key-value pairs.

        Format: key_size (2 bytes LE) + key + val_size (2 bytes LE) + value
        """
        pos = 0
        var_count = 0

        while pos < len(data):
            if var_count >= MAX_UWSGI_VARS:
                raise InvalidUWSGIHeader("too many variables")

            # Key size (2 bytes, little-endian)
            if pos + 2 > len(data):
                raise InvalidUWSGIHeader("truncated key size")
            key_size = int.from_bytes(data[pos:pos + 2], 'little')
            pos += 2

            # Key
            if pos + key_size > len(data):
                raise InvalidUWSGIHeader("truncated key")
            key = data[pos:pos + key_size].decode('latin-1')
            pos += key_size

            # Value size (2 bytes, little-endian)
            if pos + 2 > len(data):
                raise InvalidUWSGIHeader("truncated value size")
            val_size = int.from_bytes(data[pos:pos + 2], 'little')
            pos += 2

            # Value
            if pos + val_size > len(data):
                raise InvalidUWSGIHeader("truncated value")
            value = data[pos:pos + val_size].decode('latin-1')
            pos += val_size

            self.uwsgi_vars[key] = value
            var_count += 1

    def _extract_request_info(self):
        """Extract HTTP request info from uWSGI vars.

        Header Mapping (CGI/WSGI to HTTP):

        The uWSGI protocol passes HTTP headers using CGI-style environment
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
        passing through nginx/uWSGI. This is a CGI/WSGI specification
        limitation, not specific to this implementation.
        """
        # Method
        self.method = self.uwsgi_vars.get('REQUEST_METHOD', 'GET')

        # URI and path
        self.path = self.uwsgi_vars.get('PATH_INFO', '/')
        self.query = self.uwsgi_vars.get('QUERY_STRING', '')

        # Build URI
        if self.query:
            self.uri = "%s?%s" % (self.path, self.query)
        else:
            self.uri = self.path

        # Scheme
        if self.uwsgi_vars.get('HTTPS', '').lower() in ('on', '1', 'true'):
            self.scheme = 'https'
        elif 'wsgi.url_scheme' in self.uwsgi_vars:
            self.scheme = self.uwsgi_vars['wsgi.url_scheme']

        # Extract HTTP headers from CGI-style vars
        # See docstring above for mapping details
        for key, value in self.uwsgi_vars.items():
            if key.startswith('HTTP_'):
                # Convert HTTP_HEADER_NAME to HEADER-NAME
                header_name = key[5:].replace('_', '-')
                self.headers.append((header_name, value))
            elif key == 'CONTENT_TYPE':
                self.headers.append(('CONTENT-TYPE', value))
            elif key == 'CONTENT_LENGTH':
                self.headers.append(('CONTENT-LENGTH', value))

    def set_body_reader(self):
        """Set up the body reader based on CONTENT_LENGTH."""
        content_length = 0

        # Get content length from vars
        if 'CONTENT_LENGTH' in self.uwsgi_vars:
            try:
                content_length = max(int(self.uwsgi_vars['CONTENT_LENGTH']), 0)
            except ValueError:
                content_length = 0

        self.body = Body(LengthReader(self.unreader, content_length))

    def should_close(self):
        """Determine if the connection should be closed after this request."""
        if self.must_close:
            return True

        # Check HTTP_CONNECTION header
        connection = self.uwsgi_vars.get('HTTP_CONNECTION', '').lower()
        if connection == 'close':
            return True
        elif connection == 'keep-alive':
            return False

        # Default to keep-alive for HTTP/1.1
        return False
