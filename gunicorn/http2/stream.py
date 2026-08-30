# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
HTTP/2 stream state management.

Each HTTP/2 stream represents a single request/response exchange.
"""

from enum import Enum, auto

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

        # Request body: DATA payloads in arrival order, held only until
        # the application takes them. Flow-control credit for a payload
        # goes back to the peer when it is taken, not when it arrives, so
        # what sits here is bounded by the receive window. body_size
        # counts what arrived, acked_size what has been credited back.
        self._body_chunks = []
        self.body_size = 0
        self.acked_size = 0
        self._body_event = None  # Lazy-init asyncio.Event
        self._body_complete = False

        # Set once the peer reset the stream or the connection is gone;
        # wait_disconnect() lets an ASGI receive() block on it.
        self.disconnected = False
        self._disconnect_waiter = None
        # Request carried Expect: 100-continue and no 100 went out yet
        self.expect_continue = False

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
            self._body_complete = True
            if self._body_event:
                self._body_event.set()

    def receive_data(self, data, end_stream=False):
        """Process received DATA frame with streaming support.

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

        if data:
            self._body_chunks.append(data)
            self.body_size += len(data)
            if self._body_event:
                self._body_event.set()

        if end_stream:
            self._half_close_remote()
            self.request_complete = True
            self._body_complete = True
            if self._body_event:
                self._body_event.set()

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
        self.signal_disconnect()

    def signal_disconnect(self):
        """Mark the peer as gone and wake anything waiting on it."""
        self.disconnected = True
        waiter = self._disconnect_waiter
        if waiter is not None and not waiter.done():
            waiter.set_result(None)
        # Wake a reader waiting on the body; it finds the stream closed.
        if self._body_event:
            self._body_event.set()

    async def wait_disconnect(self):
        """Block until the peer resets the stream or the connection ends."""
        import asyncio

        if self.disconnected:
            return
        self._disconnect_waiter = asyncio.get_running_loop().create_future()
        try:
            await self._disconnect_waiter
        finally:
            self._disconnect_waiter = None

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

    @property
    def body_complete(self):
        """True once END_STREAM (or trailers) arrived for the request."""
        return self._body_complete

    @property
    def unacked_size(self):
        """Bytes received on this stream not yet credited back to the peer."""
        return self.body_size - self.acked_size

    def get_request_body(self):
        """Join whatever body data is currently held, without taking it.

        Returns:
            bytes: The request body data received so far
        """
        if len(self._body_chunks) == 1:
            return self._body_chunks[0]
        return b"".join(self._body_chunks)

    def pop_chunk(self):
        """Take the next held DATA payload and credit it back to the peer.

        Returns:
            bytes: The payload, or None when nothing is held right now.
        """
        if not self._body_chunks:
            return None
        chunk = self._body_chunks.pop(0)
        self._acknowledge(len(chunk))
        return chunk

    def _acknowledge(self, size):
        """Return flow-control credit for ``size`` consumed bytes."""
        if size <= 0 or self.acked_size >= self.body_size:
            # Nothing owed: an h2c upgrade body came over HTTP/1
            return
        self.acked_size += size
        ack = getattr(self.connection, "acknowledge_data", None)
        if ack is not None:
            ack(self.stream_id, size)

    async def read_body_chunk(self):
        """Read next body chunk asynchronously for streaming.

        Returns:
            bytes: Next chunk of body data, or None if body is complete.
        """
        import asyncio

        # Initialize event lazily (avoids event loop issues at construction)
        if self._body_event is None:
            self._body_event = asyncio.Event()
            # If data already arrived before event existed, set it now
            # This prevents race where DATA frames arrive before first read
            if self._body_chunks or self._body_complete:
                self._body_event.set()

        while True:
            # Return chunk if available
            chunk = self.pop_chunk()
            if chunk is not None:
                return chunk

            # No more data expected
            if self._body_complete:
                return None
            if self.state is StreamState.CLOSED:
                raise HTTP2StreamError(
                    self.stream_id,
                    "stream closed before its request body was complete")

            # Wait for more data
            self._body_event.clear()
            await self._body_event.wait()

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
