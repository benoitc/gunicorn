# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
HTTP/2 request wrapper.

Provides a Request-compatible interface for HTTP/2 streams.
"""

from io import BytesIO

from gunicorn.util import split_request_uri


class HTTP2Body:
    """Body wrapper for HTTP/2 request data.

    Provides a file-like interface to the request body,
    compatible with gunicorn's Body class expectations.
    """

    def __init__(self, data):
        """Initialize with body data.

        Args:
            data: bytes containing the request body
        """
        self._data = BytesIO(data)
        self._len = len(data)

    def read(self, size=None):
        """Read data from the body.

        Args:
            size: Number of bytes to read, or None for all remaining

        Returns:
            bytes: The requested data
        """
        if size is None:
            return self._data.read()
        return self._data.read(size)

    def readline(self, size=None):
        """Read a line from the body.

        Args:
            size: Maximum bytes to read

        Returns:
            bytes: A line of data
        """
        if size is None:
            return self._data.readline()
        return self._data.readline(size)

    def readlines(self, hint=None):
        """Read all lines from the body.

        Args:
            hint: Approximate byte count hint

        Returns:
            list: List of lines
        """
        return self._data.readlines(hint)

    def __iter__(self):
        """Iterate over lines in the body."""
        return iter(self._data)

    def __len__(self):
        """Return the content length."""
        return self._len

    def close(self):
        """Close the body stream."""
        self._data.close()


class HTTP2Request:
    """HTTP/2 request wrapper compatible with gunicorn Request interface.

    Wraps an HTTP2Stream to provide the same interface as the HTTP/1.x
    Request class, allowing workers to handle HTTP/2 requests using
    existing code paths.
    """

    def __init__(self, stream, cfg, peer_addr):
        """Initialize from an HTTP/2 stream.

        Args:
            stream: HTTP2Stream instance with received headers/body
            cfg: Gunicorn configuration object
            peer_addr: Client address tuple (host, port)
        """
        self.stream = stream
        self.cfg = cfg
        self.peer_addr = peer_addr
        self.remote_addr = peer_addr

        # HTTP/2 version tuple
        self.version = (2, 0)

        # Parse pseudo-headers
        pseudo = stream.get_pseudo_headers()
        self.method = pseudo.get(':method', 'GET')
        self.scheme = pseudo.get(':scheme', 'https')
        authority = pseudo.get(':authority', '')
        path = pseudo.get(':path', '/')

        # Parse the path into components
        self.uri = path
        try:
            parts = split_request_uri(path)
            self.path = parts.path or ""
            self.query = parts.query or ""
            self.fragment = parts.fragment or ""
        except ValueError:
            self.path = path
            self.query = ""
            self.fragment = ""

        # Store authority for Host header equivalent
        self._authority = authority

        # Convert HTTP/2 headers to HTTP/1.1 style
        # HTTP/2 headers are lowercase, convert to uppercase for WSGI
        self.headers = []
        for name, value in stream.get_regular_headers():
            # Convert to uppercase for WSGI compatibility
            self.headers.append((name.upper(), value))

        # Set Host header from :authority (RFC 9113 section 8.3.1)
        # :authority MUST take precedence over Host header
        if authority:
            self.headers = [(n, v) for n, v in self.headers if n != 'HOST']
            self.headers.append(('HOST', authority))

        # Trailers (if any)
        self.trailers = []
        if stream.trailers:
            self.trailers = [
                (name.upper(), value)
                for name, value in stream.trailers
            ]

        # Body - HTTP/2 streams have complete body data
        body_data = stream.get_request_body()
        self.body = HTTP2Body(body_data)

        # Connection state
        self.must_close = False
        self._expected_100_continue = False

        # Request numbering (for logging)
        self.req_number = stream.stream_id

        # HTTP/2 does not use proxy protocol through the data stream
        self.proxy_protocol_info = None

        # Stream priority (RFC 7540 Section 5.3)
        self.priority_weight = stream.priority_weight
        self.priority_depends_on = stream.priority_depends_on

    def force_close(self):
        """Force the connection to close after this request."""
        self.must_close = True

    def should_close(self):
        """Check if connection should close after this request.

        HTTP/2 connections are persistent by design, but we may still
        need to close if explicitly requested.

        Returns:
            bool: True if connection should close
        """
        if self.must_close:
            return True
        # HTTP/2 connections are persistent, don't close by default
        return False

    def get_header(self, name):
        """Get a header value by name.

        Args:
            name: Header name (case-insensitive)

        Returns:
            str: Header value, or None if not found
        """
        name = name.upper()
        for h_name, h_value in self.headers:
            if h_name == name:
                return h_value
        return None

    @property
    def content_length(self):
        """Get the Content-Length header value.

        Returns:
            int: Content length, or None if not set
        """
        cl = self.get_header('CONTENT-LENGTH')
        if cl is not None:
            try:
                return int(cl)
            except ValueError:
                pass
        return None

    @property
    def content_type(self):
        """Get the Content-Type header value.

        Returns:
            str: Content type, or None if not set
        """
        return self.get_header('CONTENT-TYPE')

    def __repr__(self):
        return (
            f"<HTTP2Request "
            f"method={self.method} "
            f"path={self.path} "
            f"stream_id={self.stream.stream_id}>"
        )


__all__ = ['HTTP2Request', 'HTTP2Body']
