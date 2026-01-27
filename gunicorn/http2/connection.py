# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
HTTP/2 server connection implementation.

Uses the hyper-h2 library for HTTP/2 protocol handling.
"""

from io import BytesIO

from .errors import (
    HTTP2Error, HTTP2ProtocolError, HTTP2ConnectionError,
    HTTP2NotAvailable, HTTP2ErrorCode,
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
    global _h2, _h2_config, _h2_events, _h2_exceptions, _h2_settings  # pylint: disable=global-statement

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


class HTTP2ServerConnection:
    """HTTP/2 server-side connection handler.

    Manages the HTTP/2 connection state and multiplexed streams.
    This class wraps the h2 library and provides a higher-level
    interface for gunicorn workers.
    """

    # Default buffer size for socket reads
    READ_BUFFER_SIZE = 65536

    def __init__(self, cfg, sock, client_addr):
        """Initialize an HTTP/2 server connection.

        Args:
            cfg: Gunicorn configuration object
            sock: SSL socket with completed handshake
            client_addr: Client address tuple (host, port)

        Raises:
            HTTP2NotAvailable: If h2 library is not installed
        """
        _import_h2()

        self.cfg = cfg
        self.sock = sock
        self.client_addr = client_addr

        # Active streams indexed by stream ID
        self.streams = {}

        # Completed requests ready for processing
        self._pending_requests = []

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

        # Read buffer for partial frames
        self._read_buffer = BytesIO()

        # Connection state
        self._closed = False
        self._initialized = False

    def initiate_connection(self):
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
        self._send_pending_data()
        self._initialized = True

    def receive_data(self, data=None):
        """Process received data and return completed requests.

        Args:
            data: Optional bytes to process. If None, reads from socket.

        Returns:
            list: List of HTTP2Request objects for completed requests

        Raises:
            HTTP2ConnectionError: On protocol or connection errors
        """
        if data is None:
            try:
                data = self.sock.recv(self.READ_BUFFER_SIZE)
            except (OSError, IOError) as e:
                raise HTTP2ConnectionError(f"Socket read error: {e}")

        if not data:
            # Connection closed by peer
            self._closed = True
            return []

        # Feed data to h2
        # Note: Specific exceptions must come before ProtocolError (their parent class)
        try:
            events = self.h2_conn.receive_data(data)
        except _h2_exceptions.FlowControlError as e:
            # Send GOAWAY with FLOW_CONTROL_ERROR
            self.close(error_code=HTTP2ErrorCode.FLOW_CONTROL_ERROR)
            raise HTTP2ProtocolError(str(e))
        except _h2_exceptions.FrameTooLargeError as e:
            # Send GOAWAY with FRAME_SIZE_ERROR
            self.close(error_code=HTTP2ErrorCode.FRAME_SIZE_ERROR)
            raise HTTP2ProtocolError(str(e))
        except _h2_exceptions.InvalidSettingsValueError as e:
            # Use error_code from h2 exception (RFC 7540 Section 6.5.2):
            # INITIAL_WINDOW_SIZE > 2^31-1 gives FLOW_CONTROL_ERROR
            # Other invalid settings give PROTOCOL_ERROR
            error_code = getattr(e, 'error_code', None)
            if error_code is not None:
                self.close(error_code=error_code)
            else:
                self.close(error_code=HTTP2ErrorCode.PROTOCOL_ERROR)
            raise HTTP2ProtocolError(str(e))
        except _h2_exceptions.TooManyStreamsError as e:
            # Send GOAWAY with REFUSED_STREAM
            self.close(error_code=HTTP2ErrorCode.REFUSED_STREAM)
            raise HTTP2ProtocolError(str(e))
        except _h2_exceptions.ProtocolError as e:
            # Send GOAWAY with PROTOCOL_ERROR before raising
            self.close(error_code=HTTP2ErrorCode.PROTOCOL_ERROR)
            raise HTTP2ProtocolError(str(e))

        # Process events
        completed_requests = []
        for event in events:
            request = self._handle_event(event)
            if request is not None:
                completed_requests.append(request)

        # Send any pending data (WINDOW_UPDATE, etc.)
        self._send_pending_data()

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
            self._handle_priority_updated(event)

        elif isinstance(event, _h2_events.SettingsAcknowledged):
            pass  # Settings ACK received

        elif isinstance(event, _h2_events.ConnectionTerminated):
            self._handle_connection_terminated(event)

        elif isinstance(event, _h2_events.TrailersReceived):
            return self._handle_trailers_received(event)

        return None

    def _handle_request_received(self, event):
        """Handle RequestReceived event (HEADERS frame).

        Args:
            event: RequestReceived event with headers
        """
        stream_id = event.stream_id
        headers = event.headers

        # Create new stream
        stream = HTTP2Stream(stream_id, self)
        self.streams[stream_id] = stream

        # Process headers
        # The StreamEnded event will come separately for GET/HEAD with no body
        stream.receive_headers(headers, end_stream=False)

    def _handle_data_received(self, event):
        """Handle DataReceived event.

        Args:
            event: DataReceived event with body data

        Returns:
            None (request completion handled by StreamEnded)
        """
        stream_id = event.stream_id
        data = event.data

        stream = self.streams.get(stream_id)
        if stream is None:
            # Stream was reset or doesn't exist
            return None

        stream.receive_data(data, end_stream=False)

        # Increment flow control windows (only if data received)
        if len(data) > 0:
            try:
                # Update stream-level window
                self.h2_conn.increment_flow_control_window(len(data), stream_id=stream_id)
                # Update connection-level window
                self.h2_conn.increment_flow_control_window(len(data), stream_id=None)
                # Send WINDOW_UPDATE frames immediately
                self._send_pending_data()
            except (ValueError, _h2_exceptions.FlowControlError):
                # Window overflow - send FLOW_CONTROL_ERROR and close
                self.close(error_code=HTTP2ErrorCode.FLOW_CONTROL_ERROR)

        return None

    def _handle_stream_ended(self, event):
        """Handle StreamEnded event.

        Args:
            event: StreamEnded event

        Returns:
            HTTP2Request for the completed request
        """
        stream_id = event.stream_id
        stream = self.streams.get(stream_id)

        if stream is None:
            return None

        # Mark stream as request complete
        stream.request_complete = True

        # Create request object
        return HTTP2Request(stream, self.cfg, self.client_addr)

    def _handle_stream_reset(self, event):
        """Handle StreamReset event (RST_STREAM frame).

        Args:
            event: StreamReset event
        """
        stream_id = event.stream_id
        stream = self.streams.get(stream_id)

        if stream is not None:
            stream.reset(event.error_code)
            # Keep stream in dict for potential cleanup

    def _handle_connection_terminated(self, event):
        """Handle ConnectionTerminated event (GOAWAY frame).

        Args:
            event: ConnectionTerminated event
        """
        self._closed = True
        # Could log event.error_code and event.additional_data

    def _handle_trailers_received(self, event):
        """Handle TrailersReceived event.

        Args:
            event: TrailersReceived event with trailer headers

        Returns:
            HTTP2Request if this completes the request
        """
        stream_id = event.stream_id
        stream = self.streams.get(stream_id)

        if stream is None:
            return None

        stream.receive_trailers(event.headers)

        # Trailers always end the request
        return HTTP2Request(stream, self.cfg, self.client_addr)

    def _handle_priority_updated(self, event):
        """Handle PriorityUpdated event (PRIORITY frame).

        Args:
            event: PriorityUpdated event with priority info
        """
        stream = self.streams.get(event.stream_id)
        if stream is not None:
            stream.update_priority(
                weight=event.weight,
                depends_on=event.depends_on,
                exclusive=event.exclusive
            )

    def send_informational(self, stream_id, status, headers):
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
        self._send_pending_data()

    def send_response(self, stream_id, status, headers, body=None):
        """Send a response on a stream.

        Args:
            stream_id: The stream ID to respond on
            status: HTTP status code (int)
            headers: List of (name, value) header tuples
            body: Optional response body bytes

        Raises:
            HTTP2Error: If stream not found or in invalid state

        Returns:
            bool: True if response sent, False if stream was already closed
        """
        stream = self.streams.get(stream_id)
        if stream is None:
            # Stream was already cleaned up (reset/closed) - return gracefully
            return False

        # Build response headers with :status pseudo-header
        response_headers = [(':status', str(status))]
        for name, value in headers:
            # HTTP/2 headers must be lowercase
            response_headers.append((name.lower(), str(value)))

        end_stream = body is None or len(body) == 0

        try:
            # Send headers
            self.h2_conn.send_headers(stream_id, response_headers, end_stream=end_stream)
            stream.send_headers(response_headers, end_stream=end_stream)
            self._send_pending_data()

            # Send body if present
            if body and len(body) > 0:
                self.send_data(stream_id, body, end_stream=True)
            return True
        except _h2_exceptions.StreamClosedError:
            # Stream was reset by client - clean up gracefully
            stream.close()
            self.cleanup_stream(stream_id)
            return False

    def _wait_for_flow_control_window(self, stream_id):
        """Wait for flow control window to become positive.

        Returns:
            int: Available window size, or -1 if waiting failed
        """
        import selectors

        max_wait_attempts = 50  # ~5 seconds at 100ms per attempt
        try:
            sel = selectors.DefaultSelector()
            sel.register(self.sock, selectors.EVENT_READ)
        except (TypeError, ValueError):
            # Socket doesn't support selectors (e.g., mock socket)
            return -1

        result = -1
        try:
            for _ in range(max_wait_attempts):
                available = self.h2_conn.local_flow_control_window(stream_id)
                if available > 0:
                    result = available
                    break

                ready = sel.select(timeout=0.1)
                if ready:
                    try:
                        incoming = self.sock.recv(self.READ_BUFFER_SIZE)
                    except (OSError, IOError, _h2_exceptions.ProtocolError):
                        break
                    if not incoming:
                        self._closed = True
                        break
                    try:
                        events = self.h2_conn.receive_data(incoming)
                    except _h2_exceptions.ProtocolError:
                        break
                    for event in events:
                        if isinstance(event, _h2_events.StreamReset):
                            if event.stream_id == stream_id:
                                result = -1
                                break
                        elif isinstance(event, _h2_events.ConnectionTerminated):
                            self._closed = True
                            result = -1
                            break
                    else:
                        self._send_pending_data()
                        continue
                    break  # Break outer loop if inner loop broke
            else:
                # Loop completed without break - check final window
                result = self.h2_conn.local_flow_control_window(stream_id)
        finally:
            sel.close()

        return result

    def send_data(self, stream_id, data, end_stream=False):
        """Send data on a stream.

        Args:
            stream_id: The stream ID
            data: Body data bytes
            end_stream: Whether this ends the stream

        Returns:
            bool: True if data sent, False if stream was already closed
        """
        stream = self.streams.get(stream_id)
        if stream is None:
            return False

        data_to_send = data
        try:
            while data_to_send:
                available = self.h2_conn.local_flow_control_window(stream_id)
                chunk_size = min(available, self.max_frame_size, len(data_to_send))

                if chunk_size <= 0:
                    # Wait for WINDOW_UPDATE per RFC 7540 Section 6.9.2
                    self._send_pending_data()
                    available = self._wait_for_flow_control_window(stream_id)
                    if available <= 0:
                        return False
                    chunk_size = min(available, self.max_frame_size, len(data_to_send))

                chunk = data_to_send[:chunk_size]
                data_to_send = data_to_send[chunk_size:]
                is_final = end_stream and len(data_to_send) == 0

                self.h2_conn.send_data(stream_id, chunk, end_stream=is_final)
                self._send_pending_data()

            stream.send_data(data, end_stream=end_stream)
            return True
        except (_h2_exceptions.StreamClosedError, _h2_exceptions.FlowControlError):
            # Stream was reset by client or flow control error - clean up gracefully
            stream.close()
            self.cleanup_stream(stream_id)
            return False

    def send_trailers(self, stream_id, trailers):
        """Send trailing headers on a stream.

        Trailers are headers sent after the response body, commonly used
        for gRPC status codes, checksums, and timing information.

        Args:
            stream_id: The stream ID
            trailers: List of (name, value) trailer tuples

        Raises:
            HTTP2Error: If stream not found, headers not sent, or pseudo-headers used

        Returns:
            bool: True if trailers sent, False if stream was already closed
        """
        stream = self.streams.get(stream_id)
        if stream is None:
            # Stream was already cleaned up (reset/closed) - return gracefully
            return False
        if not stream.response_headers_sent:
            # Can't send trailers without headers - return False
            return False

        # Validate and normalize trailer headers
        trailer_headers = []
        for name, value in trailers:
            lname = name.lower()
            if lname.startswith(':'):
                raise HTTP2Error(f"Pseudo-header '{name}' not allowed in trailers")
            trailer_headers.append((lname, str(value)))

        try:
            # Send trailers with end_stream=True
            self.h2_conn.send_headers(stream_id, trailer_headers, end_stream=True)
            stream.send_trailers(trailer_headers)
            self._send_pending_data()
            return True
        except _h2_exceptions.StreamClosedError:
            # Stream was reset by client - clean up gracefully
            stream.close()
            self.cleanup_stream(stream_id)
            return False

    def send_error(self, stream_id, status_code, message=None):
        """Send an error response on a stream.

        Args:
            stream_id: The stream ID
            status_code: HTTP status code
            message: Optional error message body
        """
        body = message.encode() if message else b''
        headers = [('content-length', str(len(body)))]
        if body:
            headers.append(('content-type', 'text/plain; charset=utf-8'))

        self.send_response(stream_id, status_code, headers, body)

    def reset_stream(self, stream_id, error_code=0x8):
        """Reset a stream with RST_STREAM.

        Args:
            stream_id: The stream ID to reset
            error_code: HTTP/2 error code (default: CANCEL)
        """
        stream = self.streams.get(stream_id)
        if stream is not None:
            stream.reset(error_code)

        self.h2_conn.reset_stream(stream_id, error_code=error_code)
        self._send_pending_data()

    def close(self, error_code=0x0, last_stream_id=None):
        """Close the connection gracefully with GOAWAY.

        Args:
            error_code: HTTP/2 error code (default: NO_ERROR)
            last_stream_id: Last processed stream ID (default: highest)
        """
        if self._closed:
            return

        self._closed = True

        if last_stream_id is None:
            # Use highest stream ID we've seen
            last_stream_id = max(self.streams.keys()) if self.streams else 0

        try:
            self.h2_conn.close_connection(error_code=error_code)
            self._send_pending_data()
        except Exception:
            pass  # Best effort

    def _send_pending_data(self):
        """Send any pending data from h2 to the socket."""
        data = self.h2_conn.data_to_send()
        if data:
            try:
                self.sock.sendall(data)
            except (OSError, IOError) as e:
                self._closed = True
                raise HTTP2ConnectionError(f"Socket write error: {e}")

    @property
    def is_closed(self):
        """Check if connection is closed."""
        return self._closed

    def cleanup_stream(self, stream_id):
        """Remove a stream after processing is complete.

        Args:
            stream_id: The stream ID to clean up
        """
        self.streams.pop(stream_id, None)

    def __repr__(self):
        return (
            f"<HTTP2ServerConnection "
            f"streams={len(self.streams)} "
            f"closed={self._closed}>"
        )


__all__ = ['HTTP2ServerConnection']
