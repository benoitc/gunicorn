# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
HTTP/2 stream state management.

Each HTTP/2 stream represents a single request/response exchange.
"""

from enum import Enum, auto
from io import BytesIO

from .errors import HTTP2StreamError


class StreamState(Enum):
    """HTTP/2 stream states as defined in RFC 7540 Section 5.1."""

    IDLE = auto()
    RESERVED_LOCAL = auto()
    RESERVED_REMOTE = auto()
    OPEN = auto()
    HALF_CLOSED_LOCAL = auto()
    HALF_CLOSED_REMOTE = auto()
    CLOSED = auto()


class HTTP2Stream:
    """Represents a single HTTP/2 stream.

    Manages stream state, headers, and body data for a single
    request/response exchange within an HTTP/2 connection.
    """

    def __init__(self, stream_id, connection):
        """Initialize an HTTP/2 stream.

        Args:
            stream_id: The unique stream identifier (odd for client-initiated)
            connection: The parent HTTP2ServerConnection
        """
        self.stream_id = stream_id
        self.connection = connection

        # Stream state
        self.state = StreamState.IDLE

        # Request data
        self.request_headers = []
        self.request_body = BytesIO()
        self.request_complete = False

        # Response data
        self.response_started = False
        self.response_headers_sent = False
        self.response_complete = False

        # Flow control
        self.window_size = connection.initial_window_size

        # Request trailers
        self.trailers = None

        # Response trailers
        self.response_trailers = None

        # Stream priority (RFC 7540 Section 5.3)
        self.priority_weight = 16
        self.priority_depends_on = 0
        self.priority_exclusive = False

    @property
    def is_client_stream(self):
        """Check if this is a client-initiated stream (odd stream ID)."""
        return self.stream_id % 2 == 1

    @property
    def is_server_stream(self):
        """Check if this is a server-initiated stream (even stream ID)."""
        return self.stream_id % 2 == 0

    @property
    def can_receive(self):
        """Check if this stream can receive data."""
        return self.state in (
            StreamState.OPEN,
            StreamState.HALF_CLOSED_LOCAL,
        )

    @property
    def can_send(self):
        """Check if this stream can send data."""
        return self.state in (
            StreamState.OPEN,
            StreamState.HALF_CLOSED_REMOTE,
        )

    def receive_headers(self, headers, end_stream=False):
        """Process received HEADERS frame.

        Args:
            headers: List of (name, value) tuples
            end_stream: True if END_STREAM flag is set

        Raises:
            HTTP2StreamError: If headers received in invalid state
        """
        if self.state == StreamState.IDLE:
            self.state = StreamState.OPEN
        elif self.state not in (StreamState.OPEN, StreamState.HALF_CLOSED_LOCAL):
            raise HTTP2StreamError(
                self.stream_id,
                f"Cannot receive headers in state {self.state.name}"
            )

        self.request_headers.extend(headers)

        if end_stream:
            self._half_close_remote()
            self.request_complete = True

    def receive_data(self, data, end_stream=False):
        """Process received DATA frame.

        Args:
            data: Bytes received
            end_stream: True if END_STREAM flag is set

        Raises:
            HTTP2StreamError: If data received in invalid state
        """
        if not self.can_receive:
            raise HTTP2StreamError(
                self.stream_id,
                f"Cannot receive data in state {self.state.name}"
            )

        self.request_body.write(data)

        if end_stream:
            self._half_close_remote()
            self.request_complete = True

    def receive_trailers(self, trailers):
        """Process received trailing headers.

        Args:
            trailers: List of (name, value) tuples
        """
        if not self.can_receive:
            raise HTTP2StreamError(
                self.stream_id,
                f"Cannot receive trailers in state {self.state.name}"
            )

        self.trailers = trailers
        self._half_close_remote()
        self.request_complete = True

    def send_headers(self, headers, end_stream=False):
        """Mark headers as sent.

        Args:
            headers: List of (name, value) tuples to send
            end_stream: True if this completes the response

        Raises:
            HTTP2StreamError: If headers cannot be sent in current state
        """
        if not self.can_send:
            raise HTTP2StreamError(
                self.stream_id,
                f"Cannot send headers in state {self.state.name}"
            )

        self.response_started = True
        self.response_headers_sent = True

        if end_stream:
            self._half_close_local()
            self.response_complete = True

    def send_data(self, data, end_stream=False):
        """Mark data as sent.

        Args:
            data: Bytes to send
            end_stream: True if this completes the response

        Raises:
            HTTP2StreamError: If data cannot be sent in current state
        """
        if not self.can_send:
            raise HTTP2StreamError(
                self.stream_id,
                f"Cannot send data in state {self.state.name}"
            )

        if end_stream:
            self._half_close_local()
            self.response_complete = True

    def send_trailers(self, trailers):
        """Mark trailers as sent and close the stream.

        Args:
            trailers: List of (name, value) trailer tuples

        Raises:
            HTTP2StreamError: If trailers cannot be sent in current state
        """
        if not self.can_send:
            raise HTTP2StreamError(
                self.stream_id,
                f"Cannot send trailers in state {self.state.name}"
            )
        self.response_trailers = trailers
        self._half_close_local()
        self.response_complete = True

    def reset(self, error_code=0x8):
        """Reset this stream with RST_STREAM.

        Args:
            error_code: HTTP/2 error code (default: CANCEL)
        """
        self.state = StreamState.CLOSED
        self.response_complete = True
        self.request_complete = True

    def close(self):
        """Close this stream normally."""
        self.state = StreamState.CLOSED
        self.response_complete = True
        self.request_complete = True

    def update_priority(self, weight=None, depends_on=None, exclusive=None):
        """Update stream priority from PRIORITY frame.

        Args:
            weight: Priority weight (1-256), higher = more resources
            depends_on: Stream ID this stream depends on
            exclusive: Whether this is an exclusive dependency
        """
        if weight is not None:
            self.priority_weight = max(1, min(256, weight))
        if depends_on is not None:
            self.priority_depends_on = depends_on
        if exclusive is not None:
            self.priority_exclusive = exclusive

    def _half_close_local(self):
        """Transition to half-closed (local) state."""
        if self.state == StreamState.OPEN:
            self.state = StreamState.HALF_CLOSED_LOCAL
        elif self.state == StreamState.HALF_CLOSED_REMOTE:
            self.state = StreamState.CLOSED
        else:
            raise HTTP2StreamError(
                self.stream_id,
                f"Cannot half-close local in state {self.state.name}"
            )

    def _half_close_remote(self):
        """Transition to half-closed (remote) state."""
        if self.state == StreamState.OPEN:
            self.state = StreamState.HALF_CLOSED_REMOTE
        elif self.state == StreamState.HALF_CLOSED_LOCAL:
            self.state = StreamState.CLOSED
        else:
            raise HTTP2StreamError(
                self.stream_id,
                f"Cannot half-close remote in state {self.state.name}"
            )

    def get_request_body(self):
        """Get the complete request body.

        Returns:
            bytes: The request body data
        """
        return self.request_body.getvalue()

    def get_pseudo_headers(self):
        """Extract HTTP/2 pseudo-headers from request headers.

        Returns:
            dict: Mapping of pseudo-header names to values
                  (e.g., {':method': 'GET', ':path': '/'})
        """
        pseudo = {}
        for name, value in self.request_headers:
            if name.startswith(':'):
                pseudo[name] = value
        return pseudo

    def get_regular_headers(self):
        """Get regular (non-pseudo) headers from request.

        Returns:
            list: List of (name, value) tuples for regular headers
        """
        return [
            (name, value)
            for name, value in self.request_headers
            if not name.startswith(':')
        ]

    def __repr__(self):
        return (
            f"<HTTP2Stream id={self.stream_id} "
            f"state={self.state.name} "
            f"req_complete={self.request_complete} "
            f"resp_complete={self.response_complete}>"
        )


__all__ = ['HTTP2Stream', 'StreamState']
