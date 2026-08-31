# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
HTTP/2 request wrapper.

Provides a Request-compatible interface for HTTP/2 streams.
"""

from gunicorn.http.message import (
    RFC9110_6_5_1_FORBIDDEN_TRAILER, TOKEN_RE,
    HeaderPolicy,
    RFC9110_5_5_INVALID_AND_DANGEROUS,
)
from gunicorn.http.errors import (
    InvalidHeader, InvalidRequestMethod, LimitRequestHeaders, LimitRequestLine,
)
from gunicorn.http2.errors import HTTP2StreamError
from gunicorn.http2.stream import StreamState
from gunicorn.util import split_request_uri


class HTTP2Body:
    """File-like ``wsgi.input`` over an HTTP/2 stream.

    Data is taken from the stream as the application reads it. When the
    stream holds nothing and the body is not complete, the connection is
    asked to read more frames from the socket, so the request is served
    while its body is still arriving and the peer only ever has one
    receive window of it in flight.

    Bytes may be passed instead of a stream for a body already in hand.
    """

    def __init__(self, source):
        self._buf = b""
        self._eof = False
        self._closed = False
        if isinstance(source, (bytes, bytearray)):
            self._stream = None
            self._buf = bytes(source)
            self._eof = True
        else:
            self._stream = source

    def _next_chunk(self):
        """Return the next payload, or None once the body is complete."""
        if self._eof:
            return None
        stream = self._stream
        while True:
            chunk = stream.pop_chunk()
            if chunk is not None:
                return chunk
            if stream.body_complete:
                self._eof = True
                return None
            connection = stream.connection
            if stream.state is StreamState.CLOSED or connection.is_closed:
                raise HTTP2StreamError(
                    stream.stream_id,
                    "stream closed before its request body was complete")
            pump = getattr(connection, "pump", None)
            if stream.expect_continue and not stream.response_headers_sent:
                # The client is waiting for a 100 before sending the body.
                stream.expect_continue = False
                connection.send_informational(stream.stream_id, 100, [])
            if pump is None:
                # Nothing here can wait for frames; the caller reads via
                # read_body_chunk() instead.
                self._eof = True
                return None
            pump(stream.stream_id)

    def _fill(self, size):
        """Hold at least ``size`` bytes, or everything up to the end."""
        if self._closed:
            raise ValueError("I/O operation on closed file.")
        parts = [self._buf]
        held = len(self._buf)
        while size is None or held < size:
            chunk = self._next_chunk()
            if chunk is None:
                break
            parts.append(chunk)
            held += len(chunk)
        self._buf = b"".join(parts) if len(parts) > 1 else parts[0]

    def read(self, size=None):
        """Read data from the body.

        Args:
            size: Number of bytes to read, or None for all remaining

        Returns:
            bytes: The requested data
        """
        if size is None or size < 0:
            self._fill(None)
            data, self._buf = self._buf, b""
            return data
        if size == 0:
            return b""
        self._fill(size)
        data, self._buf = self._buf[:size], self._buf[size:]
        return data

    def readline(self, size=None):
        """Read a line from the body.

        Args:
            size: Maximum bytes to read

        Returns:
            bytes: A line of data
        """
        if size is not None and size < 0:
            size = None
        if size == 0:
            return b""
        if self._closed:
            raise ValueError("I/O operation on closed file.")
        while True:
            idx = self._buf.find(b"\n")
            if idx >= 0:
                end = idx + 1
                if size is not None:
                    end = min(end, size)
                break
            if size is not None and len(self._buf) >= size:
                end = size
                break
            chunk = self._next_chunk()
            if chunk is None:
                end = len(self._buf) if size is None else min(size, len(self._buf))
                break
            self._buf += chunk
        data, self._buf = self._buf[:end], self._buf[end:]
        return data

    def readlines(self, hint=None):
        """Read all lines from the body.

        Args:
            hint: Approximate byte count hint

        Returns:
            list: List of lines
        """
        lines = []
        total = 0
        while True:
            line = self.readline()
            if not line:
                break
            lines.append(line)
            total += len(line)
            if hint is not None and 0 < hint <= total:
                break
        return lines

    def close(self):
        """Drop what is held; further reads raise ValueError."""
        self._closed = True
        self._buf = b""

    def __iter__(self):
        """Iterate over lines in the body."""
        return self

    def __next__(self):
        line = self.readline()
        if not line:
            raise StopIteration
        return line


class HTTP2Request(HeaderPolicy):
    """HTTP/2 request wrapper compatible with gunicorn Request interface.

    Wraps an HTTP2Stream to provide the same interface as the HTTP/1.x
    Request class, allowing workers to handle HTTP/2 requests using
    existing code paths.
    """

    #: HTTP/2 carries no 100-continue handshake gunicorn can answer: the
    #: response would be written as HTTP/1 bytes onto an HTTP/2 connection.
    _policy_expect_continue = False

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
        if not TOKEN_RE.fullmatch(self.method):
            raise InvalidRequestMethod(self.method)
        # Derive the scheme from the transport, as HTTP/1 does. A client
        # supplied :scheme is honoured only from a peer allowed to speak for
        # the connection; otherwise it is ignored rather than rejected, which
        # mirrors how an untrusted X-Forwarded-Proto is treated on HTTP/1.
        self.scheme = "https" if cfg.is_ssl else "http"
        claimed_scheme = pseudo.get(':scheme')
        if claimed_scheme and self._peer_is_trusted_proxy():
            self.scheme = claimed_scheme
        authority = pseudo.get(':authority', '')
        path = pseudo.get(':path', '/')
        # The same limits HTTP/1 applies to the request line and fields.
        if cfg.limit_request_line and len(path) > cfg.limit_request_line:
            raise LimitRequestLine(len(path), cfg.limit_request_line)
        regular = stream.get_regular_headers()
        if cfg.limit_request_fields and len(regular) > cfg.limit_request_fields:
            raise LimitRequestHeaders("limit request headers fields")
        if cfg.limit_request_field_size:
            for name, value in regular:
                if len(name) + len(value) + 2 > cfg.limit_request_field_size:
                    raise LimitRequestHeaders("limit request headers fields size")

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

        # Convert HTTP/2 headers to HTTP/1.1 style and put them through the
        # same policy as HTTP/1, so a rule cannot hold on one protocol and be
        # skipped on the other.
        self.headers = []
        scheme_state = [False]
        seen = set()
        secure_scheme_headers, forwarder_headers = \
            self._peer_trusted_for_forwarded()
        for name, value in stream.get_regular_headers():
            # Convert to uppercase for WSGI compatibility
            name = name.upper()
            if RFC9110_5_5_INVALID_AND_DANGEROUS.search(value):
                raise InvalidHeader(name, req=self)
            kept = self._apply_header_policy(
                name, value, scheme_state, seen,
                secure_scheme_headers, forwarder_headers,
            )
            if kept is None:
                continue
            self.headers.append(kept)

        # Set Host header from :authority (RFC 9113 section 8.3.1)
        # :authority MUST take precedence over Host header. Runs after the
        # policy so a duplicate Host is still rejected rather than replaced.
        if authority:
            self.headers = [(n, v) for n, v in self.headers if n != 'HOST']
            self.headers.append(('HOST', authority))

        # Body: read from the stream as it arrives.
        self.body = HTTP2Body(stream)
        expect = self.get_header('EXPECT')
        stream.expect_continue = bool(expect) and expect.strip().lower() == '100-continue'

        # Connection state
        self.must_close = False
        # Never set on HTTP/2: gunicorn answers it with HTTP/1 bytes written
        # straight to the socket, which would corrupt the connection.
        self._expected_100_continue = False

        # Request numbering (for logging)
        self.req_number = stream.stream_id

        # HTTP/2 does not use proxy protocol through the data stream
        self.proxy_protocol_info = None

        # Stream priority (RFC 7540 Section 5.3)
        self.priority_weight = stream.priority_weight
        self.priority_depends_on = stream.priority_depends_on

    @property
    def trailers(self):
        """Trailing headers, available once the whole body has been read."""
        if not self.stream.trailers:
            return []
        return [
            (name.upper(), value)
            for name, value in self.stream.trailers
            if name.upper() not in RFC9110_6_5_1_FORBIDDEN_TRAILER
            and not name.startswith(':')
        ]

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
