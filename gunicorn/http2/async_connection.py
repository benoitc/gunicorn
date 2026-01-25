# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Async HTTP/2 server connection implementation for ASGI workers.

Uses the hyper-h2 library for HTTP/2 protocol handling with
asyncio for non-blocking I/O.
"""

import asyncio

from .errors import (
    HTTP2Error, HTTP2ProtocolError, HTTP2ConnectionError,
    HTTP2NotAvailable,
)
from .stream import HTTP2Stream
from .request import HTTP2Request


# Import h2 lazily to allow graceful fallback
_h2 = None
_h2_config = None
_h2_events = None
_h2_exceptions = None
_h2_settings = None


def _import_h2():
    """Lazily import h2 library components."""
    global _h2, _h2_config, _h2_events, _h2_exceptions, _h2_settings

    if _h2 is not None:
        return

    try:
        import h2.connection as _h2
        import h2.config as _h2_config
        import h2.events as _h2_events
        import h2.exceptions as _h2_exceptions
        import h2.settings as _h2_settings
    except ImportError:
        raise HTTP2NotAvailable()


class AsyncHTTP2Connection:
    """Async HTTP/2 server-side connection handler for ASGI.

    Manages the HTTP/2 connection state and multiplexed streams
    using asyncio for non-blocking I/O operations.
    """

    # Default buffer size for socket reads
    READ_BUFFER_SIZE = 65536

    def __init__(self, cfg, reader, writer, client_addr):
        """Initialize an async HTTP/2 server connection.

        Args:
            cfg: Gunicorn configuration object
            reader: asyncio StreamReader
            writer: asyncio StreamWriter
            client_addr: Client address tuple (host, port)

        Raises:
            HTTP2NotAvailable: If h2 library is not installed
        """
        _import_h2()

        self.cfg = cfg
        self.reader = reader
        self.writer = writer
        self.client_addr = client_addr

        # Active streams indexed by stream ID
        self.streams = {}

        # Queue of completed requests for the worker
        self._request_queue = asyncio.Queue()

        # Connection settings from config
        self.initial_window_size = cfg.http2_initial_window_size
        self.max_concurrent_streams = cfg.http2_max_concurrent_streams
        self.max_frame_size = cfg.http2_max_frame_size
        self.max_header_list_size = cfg.http2_max_header_list_size

        # Initialize h2 connection
        config = _h2_config.H2Configuration(
            client_side=False,
            header_encoding='utf-8',
        )
        self.h2_conn = _h2.H2Connection(config=config)

        # Connection state
        self._closed = False
        self._initialized = False
        self._receive_task = None

    async def initiate_connection(self):
        """Send initial HTTP/2 settings to client.

        Should be called after the SSL handshake completes and
        before processing any data.
        """
        if self._initialized:
            return

        # Update local settings before initiating
        self.h2_conn.update_settings({
            _h2_settings.SettingCodes.MAX_CONCURRENT_STREAMS: self.max_concurrent_streams,
            _h2_settings.SettingCodes.INITIAL_WINDOW_SIZE: self.initial_window_size,
            _h2_settings.SettingCodes.MAX_FRAME_SIZE: self.max_frame_size,
            _h2_settings.SettingCodes.MAX_HEADER_LIST_SIZE: self.max_header_list_size,
        })

        self.h2_conn.initiate_connection()
        await self._send_pending_data()
        self._initialized = True

    async def receive_data(self, timeout=None):
        """Receive data and return completed requests.

        Args:
            timeout: Optional timeout in seconds for read operation

        Returns:
            list: List of HTTP2Request objects for completed requests

        Raises:
            HTTP2ConnectionError: On protocol or connection errors
            asyncio.TimeoutError: If timeout expires
        """
        try:
            if timeout is not None:
                data = await asyncio.wait_for(
                    self.reader.read(self.READ_BUFFER_SIZE),
                    timeout=timeout
                )
            else:
                data = await self.reader.read(self.READ_BUFFER_SIZE)
        except (OSError, IOError) as e:
            raise HTTP2ConnectionError(f"Socket read error: {e}")

        if not data:
            # Connection closed by peer
            self._closed = True
            return []

        # Feed data to h2
        try:
            events = self.h2_conn.receive_data(data)
        except _h2_exceptions.ProtocolError as e:
            raise HTTP2ProtocolError(str(e))

        # Process events
        completed_requests = []
        for event in events:
            request = self._handle_event(event)
            if request is not None:
                completed_requests.append(request)

        # Send any pending data (WINDOW_UPDATE, etc.)
        await self._send_pending_data()

        return completed_requests

    def _handle_event(self, event):
        """Handle a single h2 event.

        Args:
            event: h2 event object

        Returns:
            HTTP2Request if a request is complete, None otherwise
        """
        if isinstance(event, _h2_events.RequestReceived):
            return self._handle_request_received(event)

        elif isinstance(event, _h2_events.DataReceived):
            return self._handle_data_received(event)

        elif isinstance(event, _h2_events.StreamEnded):
            return self._handle_stream_ended(event)

        elif isinstance(event, _h2_events.StreamReset):
            self._handle_stream_reset(event)

        elif isinstance(event, _h2_events.WindowUpdated):
            pass  # Flow control update, handled by h2

        elif isinstance(event, _h2_events.PriorityUpdated):
            pass  # Priority update, could be used for scheduling

        elif isinstance(event, _h2_events.SettingsAcknowledged):
            pass  # Settings ACK received

        elif isinstance(event, _h2_events.ConnectionTerminated):
            self._handle_connection_terminated(event)

        elif isinstance(event, _h2_events.TrailersReceived):
            return self._handle_trailers_received(event)

        return None

    def _handle_request_received(self, event):
        """Handle RequestReceived event (HEADERS frame)."""
        stream_id = event.stream_id
        headers = event.headers

        # Create new stream
        stream = HTTP2Stream(stream_id, self)
        self.streams[stream_id] = stream

        # Process headers
        stream.receive_headers(headers, end_stream=False)
        return None

    def _handle_data_received(self, event):
        """Handle DataReceived event."""
        stream_id = event.stream_id
        data = event.data

        stream = self.streams.get(stream_id)
        if stream is None:
            return None

        stream.receive_data(data, end_stream=False)

        # Increment flow control windows (only if data received)
        if len(data) > 0:
            # Update stream-level window
            self.h2_conn.increment_flow_control_window(len(data), stream_id=stream_id)
            # Update connection-level window
            self.h2_conn.increment_flow_control_window(len(data), stream_id=None)

        return None

    def _handle_stream_ended(self, event):
        """Handle StreamEnded event."""
        stream_id = event.stream_id
        stream = self.streams.get(stream_id)

        if stream is None:
            return None

        stream.request_complete = True
        return HTTP2Request(stream, self.cfg, self.client_addr)

    def _handle_stream_reset(self, event):
        """Handle StreamReset event."""
        stream_id = event.stream_id
        stream = self.streams.get(stream_id)

        if stream is not None:
            stream.reset(event.error_code)

    def _handle_connection_terminated(self, event):
        """Handle ConnectionTerminated event."""
        self._closed = True

    def _handle_trailers_received(self, event):
        """Handle TrailersReceived event."""
        stream_id = event.stream_id
        stream = self.streams.get(stream_id)

        if stream is None:
            return None

        stream.receive_trailers(event.headers)
        return HTTP2Request(stream, self.cfg, self.client_addr)

    async def send_informational(self, stream_id, status, headers):
        """Send an informational response (1xx) on a stream.

        This is used for 103 Early Hints and other 1xx responses.
        Informational responses are sent before the final response
        and do not end the stream.

        Args:
            stream_id: The stream ID
            status: HTTP status code (100-199)
            headers: List of (name, value) header tuples

        Raises:
            HTTP2Error: If status is not in 1xx range
        """
        if status < 100 or status >= 200:
            raise HTTP2Error(f"Invalid informational status: {status}")

        stream = self.streams.get(stream_id)
        if stream is None:
            raise HTTP2Error(f"Stream {stream_id} not found")

        # Build headers with :status pseudo-header
        response_headers = [(':status', str(status))]
        for name, value in headers:
            # HTTP/2 headers must be lowercase
            response_headers.append((name.lower(), str(value)))

        # Send headers with end_stream=False (informational, more to follow)
        self.h2_conn.send_headers(stream_id, response_headers, end_stream=False)
        await self._send_pending_data()

    async def send_response(self, stream_id, status, headers, body=None):
        """Send a response on a stream.

        Args:
            stream_id: The stream ID to respond on
            status: HTTP status code (int)
            headers: List of (name, value) header tuples
            body: Optional response body bytes
        """
        stream = self.streams.get(stream_id)
        if stream is None:
            raise HTTP2Error(f"Stream {stream_id} not found")

        # Build response headers with :status pseudo-header
        response_headers = [(':status', str(status))]
        for name, value in headers:
            response_headers.append((name.lower(), str(value)))

        end_stream = body is None or len(body) == 0

        # Send headers
        self.h2_conn.send_headers(stream_id, response_headers, end_stream=end_stream)
        stream.send_headers(response_headers, end_stream=end_stream)
        await self._send_pending_data()

        # Send body if present
        if body and len(body) > 0:
            await self.send_data(stream_id, body, end_stream=True)

    async def send_data(self, stream_id, data, end_stream=False):
        """Send data on a stream.

        Args:
            stream_id: The stream ID
            data: Body data bytes
            end_stream: Whether this ends the stream
        """
        stream = self.streams.get(stream_id)
        if stream is None:
            raise HTTP2Error(f"Stream {stream_id} not found")

        # Send data in chunks respecting flow control and max frame size
        data_to_send = data
        while data_to_send:
            # Get available window size for this stream
            available = self.h2_conn.local_flow_control_window(stream_id)
            # Also respect max frame size
            chunk_size = min(available, self.max_frame_size, len(data_to_send))

            if chunk_size <= 0:
                # No window available, send what we have and wait
                await self._send_pending_data()
                # Try again - the window might open after ACKs
                available = self.h2_conn.local_flow_control_window(stream_id)
                if available <= 0:
                    # Still no window, just try to send a small chunk
                    chunk_size = min(self.max_frame_size, len(data_to_send))

            chunk = data_to_send[:chunk_size]
            data_to_send = data_to_send[chunk_size:]

            # Only set end_stream on the final chunk
            is_final = end_stream and len(data_to_send) == 0

            self.h2_conn.send_data(stream_id, chunk, end_stream=is_final)
            await self._send_pending_data()

        stream.send_data(data, end_stream=end_stream)

    async def send_error(self, stream_id, status_code, message=None):
        """Send an error response on a stream."""
        body = message.encode() if message else b''
        headers = [('content-length', str(len(body)))]
        if body:
            headers.append(('content-type', 'text/plain; charset=utf-8'))

        await self.send_response(stream_id, status_code, headers, body)

    async def reset_stream(self, stream_id, error_code=0x8):
        """Reset a stream with RST_STREAM."""
        stream = self.streams.get(stream_id)
        if stream is not None:
            stream.reset(error_code)

        self.h2_conn.reset_stream(stream_id, error_code=error_code)
        await self._send_pending_data()

    async def close(self, error_code=0x0, last_stream_id=None):
        """Close the connection gracefully with GOAWAY."""
        if self._closed:
            return

        self._closed = True

        if last_stream_id is None:
            last_stream_id = max(self.streams.keys()) if self.streams else 0

        try:
            self.h2_conn.close_connection(error_code=error_code)
            await self._send_pending_data()
        except Exception:
            pass

        try:
            self.writer.close()
            await self.writer.wait_closed()
        except Exception:
            pass

    async def _send_pending_data(self):
        """Send any pending data from h2 to the socket."""
        data = self.h2_conn.data_to_send()
        if data:
            try:
                self.writer.write(data)
                await self.writer.drain()
            except (OSError, IOError) as e:
                self._closed = True
                raise HTTP2ConnectionError(f"Socket write error: {e}")

    @property
    def is_closed(self):
        """Check if connection is closed."""
        return self._closed

    def cleanup_stream(self, stream_id):
        """Remove a stream after processing is complete."""
        self.streams.pop(stream_id, None)

    def __repr__(self):
        return (
            f"<AsyncHTTP2Connection "
            f"streams={len(self.streams)} "
            f"closed={self._closed}>"
        )


__all__ = ['AsyncHTTP2Connection']
