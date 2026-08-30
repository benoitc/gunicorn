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
import collections
import time

from .errors import (
    HTTP2Error, HTTP2ProtocolError, HTTP2ConnectionError,
    HTTP2NotAvailable, HTTP2ErrorCode,
)
from .stream import HTTP2Stream, StreamState
from .h2conn import server_connection_class
from .request import HTTP2Request
from gunicorn.http.errors import ParseException


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


# RST_STREAM frames a peer may send per window before the connection is
# closed with ENHANCE_YOUR_CALM (CVE-2023-44487 style floods). A client
# cancelling requests never comes close.
RST_STREAM_RATE_LIMIT = 200
RST_STREAM_RATE_WINDOW = 10.0


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
        # Events pulled off the wire while blocked on a flow-control window.
        # They have left the h2 state machine already, so they are held here
        # for the main receive loop rather than discarded.
        self._deferred_events = collections.deque()
        self._reset_times = collections.deque()
        # Set by the receive loop whenever the peer widens a window, so
        # a response task can wait for credit without touching the
        # reader the loop owns.
        self._window_event = None
        self._write_lock = None
        # Peer sent a graceful GOAWAY: finish open streams, take no new ones
        self.draining = False
        self.peer_last_stream_id = None

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
        self.h2_conn = server_connection_class()(config=config)

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
            **({_h2_settings.SettingCodes.MAX_HEADER_LIST_SIZE: self.max_header_list_size}
               if self.max_header_list_size else {}),
        })

        self.h2_conn.initiate_connection()
        await self._send_pending_data()
        self._initialized = True

    async def initiate_upgrade(self, settings_header, http1_req, body=b""):
        """Switch a connection to HTTP/2 after an Upgrade: h2c request.

        The async twin of HTTP2Connection.initiate_upgrade. The upgraded
        request becomes stream 1 (RFC 7540 section 3.2): h2 opens it in the
        state machine, and the matching gunicorn stream is built here from the
        HTTP/1 request that carried the upgrade, so the worker sees an
        ordinary HTTP/2 request.

        The body is passed in rather than read off the request: the callback
        parser hands body chunks to the protocol, not to the request object.

        Returns the HTTP2Request for stream 1.
        """
        self.h2_conn.update_settings({
            _h2_settings.SettingCodes.MAX_CONCURRENT_STREAMS: self.max_concurrent_streams,
            _h2_settings.SettingCodes.INITIAL_WINDOW_SIZE: self.initial_window_size,
            _h2_settings.SettingCodes.MAX_FRAME_SIZE: self.max_frame_size,
            **({_h2_settings.SettingCodes.MAX_HEADER_LIST_SIZE: self.max_header_list_size}
               if self.max_header_list_size else {}),
        })
        self.h2_conn.initiate_upgrade_connection(settings_header=settings_header)
        await self._send_pending_data()
        self._initialized = True

        stream = HTTP2Stream(stream_id=1, connection=self)
        authority = ""
        for name, value in http1_req.headers:
            if name == "HOST":
                authority = value
                break
        pseudo = [
            (':method', http1_req.method),
            (':path', http1_req.uri),
            (':scheme', http1_req.scheme),
        ]
        if authority:
            pseudo.append((':authority', authority))
        regular = [(name.lower(), value) for name, value in http1_req.headers
                   if name not in ("CONNECTION", "UPGRADE", "HTTP2-SETTINGS")]

        stream.receive_headers(pseudo + regular, end_stream=not body)
        if body:
            stream.receive_data(body, end_stream=True)
            # That body came over HTTP/1, so no window credit is owed.
            stream.acked_size = stream.body_size
        self.streams[1] = stream
        return HTTP2Request(stream, self.cfg, self.client_addr)

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
        except asyncio.TimeoutError:
            # A subclass of OSError since Python 3.11; the caller's
            # timeout is not a socket failure.
            raise
        except (OSError, IOError) as e:
            raise HTTP2ConnectionError(f"Socket read error: {e}")

        if not data:
            # Connection closed by peer
            self._closed = True
            self._abort_all_streams()
            self._signal_window()
            return []

        # Feed data to h2
        # Note: Specific exceptions must come before ProtocolError (their parent class)
        try:
            events = self.h2_conn.receive_data(data)
        except _h2_exceptions.FlowControlError as e:
            # Send GOAWAY with FLOW_CONTROL_ERROR
            await self.close(error_code=HTTP2ErrorCode.FLOW_CONTROL_ERROR)
            raise HTTP2ProtocolError(str(e))
        except _h2_exceptions.FrameTooLargeError as e:
            # Send GOAWAY with FRAME_SIZE_ERROR
            await self.close(error_code=HTTP2ErrorCode.FRAME_SIZE_ERROR)
            raise HTTP2ProtocolError(str(e))
        except _h2_exceptions.InvalidSettingsValueError as e:
            # Use error_code from h2 exception (RFC 7540 Section 6.5.2):
            # INITIAL_WINDOW_SIZE > 2^31-1 gives FLOW_CONTROL_ERROR
            # Other invalid settings give PROTOCOL_ERROR
            error_code = getattr(e, 'error_code', None)
            if error_code is not None:
                await self.close(error_code=error_code)
            else:
                await self.close(error_code=HTTP2ErrorCode.PROTOCOL_ERROR)
            raise HTTP2ProtocolError(str(e))
        except _h2_exceptions.TooManyStreamsError as e:
            # Send GOAWAY with REFUSED_STREAM
            await self.close(error_code=HTTP2ErrorCode.REFUSED_STREAM)
            raise HTTP2ProtocolError(str(e))
        except UnicodeDecodeError as e:
            # Header bytes h2 could not decode
            await self.close(error_code=HTTP2ErrorCode.PROTOCOL_ERROR)
            raise HTTP2ProtocolError(f"Undecodable header: {e}")
        except _h2_exceptions.ProtocolError as e:
            # Send GOAWAY with PROTOCOL_ERROR before raising
            await self.close(error_code=HTTP2ErrorCode.PROTOCOL_ERROR)
            raise HTTP2ProtocolError(str(e))

        # Process events, oldest first: anything set aside during a
        # flow-control wait arrived before this batch.
        completed_requests = []
        if self._deferred_events:
            events = list(self._deferred_events) + list(events)
            self._deferred_events.clear()
        for event in events:
            request = self._handle_event(event)
            if request is not None:
                completed_requests.append(request)
        # A stream reset in the same batch gets no task at all.
        live = []
        for request in completed_requests:
            if request.stream.state is StreamState.CLOSED:
                self.streams.pop(request.stream.stream_id, None)
            else:
                live.append(request)
        completed_requests = live

        # Send any pending data (WINDOW_UPDATE, etc.). Not waited on: a
        # peer that stopped reading must not stop us from reading.
        await self._write_pending()

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
            self._signal_window()

        elif isinstance(event, _h2_events.PriorityUpdated):
            self._handle_priority_updated(event)

        elif isinstance(event, _h2_events.SettingsAcknowledged):
            pass  # Settings ACK received

        elif isinstance(event, _h2_events.RemoteSettingsChanged):
            self._signal_window()

        elif isinstance(event, _h2_events.ConnectionTerminated):
            self._handle_connection_terminated(event)
            self._signal_window()

        elif isinstance(event, _h2_events.TrailersReceived):
            return self._handle_trailers_received(event)

        return None

    def _handle_request_received(self, event):
        """Handle RequestReceived event (HEADERS frame)."""
        stream_id = event.stream_id
        headers = event.headers

        if self.draining and stream_id > self.peer_last_stream_id:
            # Opened after the peer's GOAWAY: it said it would not process it.
            self._reset_quietly(stream_id, HTTP2ErrorCode.REFUSED_STREAM)
            return None

        # Create new stream
        stream = HTTP2Stream(stream_id, self)
        self.streams[stream_id] = stream

        # Process headers
        stream.receive_headers(headers, end_stream=False)

        # Dispatch on headers: the body streams in behind the request.
        try:
            return HTTP2Request(stream, self.cfg, self.client_addr)
        except (ParseException, ValueError):
            # A bad request is a stream error, not a connection error
            # (RFC 9113 section 8.1.1).
            self.streams.pop(stream_id, None)
            self._reset_quietly(stream_id, HTTP2ErrorCode.PROTOCOL_ERROR)
            return None

    def _handle_data_received(self, event):
        """Handle DataReceived event.

        The payload is held on the stream until the application takes it;
        window credit goes back through acknowledge_data() at that point.
        """
        stream = self.streams.get(event.stream_id)
        if stream is None:
            return None

        stream.receive_data(event.data, end_stream=False)

        # Connection-level credit goes straight back so a stream that is
        # waiting its turn can never starve the one being served; the
        # stream-level window is credited only as the body is consumed.
        # Padding is never buffered, so its credit goes back now too.
        length = event.flow_controlled_length
        padding = length - len(event.data)
        try:
            if length:
                self.h2_conn.increment_flow_control_window(length, stream_id=None)
            if padding:
                self.h2_conn.increment_flow_control_window(padding, stream_id=event.stream_id)
        except (ValueError, _h2_exceptions.ProtocolError):
            pass
        return None

    def acknowledge_data(self, stream_id, size):
        """Credit ``size`` consumed bytes back to the peer.

        Called by the stream as the application takes body data. The
        WINDOW_UPDATE frames are written without waiting on drain: they
        are small and the reader must not be blocked behind them.
        """
        if size <= 0 or self._closed:
            return
        try:
            self.h2_conn.increment_flow_control_window(size, stream_id=stream_id)
        except (ValueError, KeyError, _h2_exceptions.ProtocolError):
            # h2 raises KeyError for a stream it already dropped
            return
        self._write_pending_nowait()

    def _write_pending_nowait(self):
        data = self.h2_conn.data_to_send()
        if data:
            try:
                self.writer.write(data)
            except (OSError, IOError):
                self._closed = True

    def _handle_stream_ended(self, event):
        """Handle StreamEnded event."""
        stream_id = event.stream_id
        stream = self.streams.get(stream_id)

        if stream is None:
            return None

        # The request went out on its headers; only mark the body complete.
        stream.request_complete = True
        stream._body_complete = True
        if stream._body_event:
            stream._body_event.set()
        return None

    def _handle_stream_reset(self, event):
        """Handle StreamReset event."""
        self._count_reset()
        stream_id = event.stream_id
        stream = self.streams.get(stream_id)

        if stream is not None:
            stream.reset(event.error_code)
        # A sender waiting for credit on this stream must re-check.
        self._signal_window()

    def _handle_connection_terminated(self, event):
        """Handle ConnectionTerminated event (GOAWAY frame).

        A graceful GOAWAY (NO_ERROR) with streams in flight puts the
        connection into draining: the established streams finish, later
        ones are refused, and the connection closes once they are done
        (RFC 9113 section 6.8). The h2 subclass has already kept its own
        state open for that case. Any other GOAWAY closes at once.
        """
        if (event.error_code == HTTP2ErrorCode.NO_ERROR
                and self.h2_conn.peer_goaway_last_stream_id is not None):
            self.draining = True
            self.peer_last_stream_id = event.last_stream_id
            return
        self._closed = True
        self._abort_all_streams()

    def _count_reset(self):
        """Close the connection when the peer resets streams at flood rate."""
        now = time.monotonic()
        self._reset_times.append(now)
        while self._reset_times and now - self._reset_times[0] > RST_STREAM_RATE_WINDOW:
            self._reset_times.popleft()
        if len(self._reset_times) > RST_STREAM_RATE_LIMIT:
            self._closed = True
            try:
                self.h2_conn.close_connection(error_code=HTTP2ErrorCode.ENHANCE_YOUR_CALM)
                self._write_pending_nowait()
            except Exception:
                pass
            self._abort_all_streams()
            raise HTTP2ProtocolError("RST_STREAM rate exceeded")

    def _abort_all_streams(self):
        """The connection is gone: wake every stream still waiting on it."""
        for stream in list(self.streams.values()):
            stream.signal_disconnect()

    def abort_streams_nowait(self):
        """Called by the protocol on connection loss."""
        self._closed = True
        self._abort_all_streams()
        self._signal_window()

    def _reset_quietly(self, stream_id, error_code):
        """Queue RST_STREAM for a stream h2 knows about, ignoring a closed one."""
        try:
            self.h2_conn.reset_stream(stream_id, error_code=error_code)
        except _h2_exceptions.ProtocolError:
            pass

    def _handle_trailers_received(self, event):
        """Handle TrailersReceived event."""
        stream_id = event.stream_id
        stream = self.streams.get(stream_id)

        if stream is None:
            return None

        stream.receive_trailers(event.headers)
        if stream._body_event:
            stream._body_event.set()
        return None

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
        if stream.response_headers_sent:
            raise HTTP2Error("Informational response after the final headers")

        # Build headers with :status pseudo-header
        response_headers = [(':status', str(status))]
        for name, value in headers:
            # HTTP/2 headers must be lowercase
            response_headers.append((name.lower(), str(value)))

        # Send headers with end_stream=False (informational, more to follow)
        await self._send(lambda: self.h2_conn.send_headers(
            stream_id, response_headers, end_stream=False))

    async def send_response_headers(self, stream_id, headers, end_stream=False):
        """Send response HEADERS already carrying ``:status``.

        Returns:
            bool: True if sent, False if the stream is gone
        """
        stream = self.streams.get(stream_id)
        if stream is None or stream.state is StreamState.CLOSED:
            return False
        if stream.response_headers_sent:
            # A second HEADERS block would be encoded into the HPACK table
            # before h2 refuses it, corrupting every later response.
            return False

        def queue():
            self.h2_conn.send_headers(stream_id, headers, end_stream=end_stream)
            stream.send_headers(headers, end_stream=end_stream)

        try:
            await self._send(queue)
        except (_h2_exceptions.StreamClosedError, _h2_exceptions.StreamIDTooLowError):
            stream.close()
            self.cleanup_stream(stream_id)
            return False
        return True

    async def send_response(self, stream_id, status, headers, body=None):
        """Send a response on a stream.

        Args:
            stream_id: The stream ID to respond on
            status: HTTP status code (int)
            headers: List of (name, value) header tuples
            body: Optional response body bytes

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
            response_headers.append((name.lower(), str(value)))

        end_stream = body is None or len(body) == 0

        try:
            # Send headers
            def queue():
                self.h2_conn.send_headers(stream_id, response_headers, end_stream=end_stream)
                stream.send_headers(response_headers, end_stream=end_stream)

            await self._send(queue)

            # Send body if present
            if body and len(body) > 0:
                await self.send_data(stream_id, body, end_stream=True)
            return True
        except (_h2_exceptions.StreamClosedError, _h2_exceptions.StreamIDTooLowError):
            # Stream was reset by client - clean up gracefully
            stream.close()
            self.cleanup_stream(stream_id)
            return False

    def _signal_window(self):
        """Wake response tasks waiting for send credit."""
        if self._window_event is not None:
            self._window_event.set()

    async def _wait_for_flow_control_window(self, stream_id):
        """Wait for the stream's send window to become positive.

        The receive loop owns the reader; it processes the peer's
        WINDOW_UPDATE, SETTINGS, RST_STREAM and GOAWAY frames and signals
        here. The wait is bounded by ``cfg.timeout`` (0 means no limit).

        Returns:
            int: Available window size; 0 if the timeout passed first;
            -1 if the stream or the connection is gone.
        """
        if self._window_event is None:
            self._window_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        timeout = self.cfg.timeout or None
        deadline = None if timeout is None else loop.time() + timeout
        while True:
            if self._closed:
                return -1
            stream = self.streams.get(stream_id)
            if stream is not None and stream.state is StreamState.CLOSED:
                return -1
            try:
                available = self.h2_conn.local_flow_control_window(stream_id)
            except _h2_exceptions.ProtocolError:
                return -1
            if available > 0:
                return available
            remaining = None
            if deadline is not None:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return 0
            self._window_event.clear()
            try:
                await asyncio.wait_for(self._window_event.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                return 0

    async def send_data(self, stream_id, data, end_stream=False):  # pylint: disable=too-many-return-statements
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
            if not data_to_send:
                if not end_stream:
                    return True
                # An empty DATA frame carrying END_STREAM needs no window
                # credit and is how a response with nothing left ends.
                async with self._lock():
                    self.h2_conn.send_data(stream_id, b"", end_stream=True)
                    stream.send_data(b"", end_stream=True)
                    wrote = self._write_locked()
                if wrote:
                    await self._drain()
                return True
            while data_to_send:
                # The window is read and the frame queued under the lock,
                # so another stream cannot spend the credit in between.
                async with self._lock():
                    available = self.h2_conn.local_flow_control_window(stream_id)
                    chunk_size = min(available, self.h2_conn.max_outbound_frame_size, len(data_to_send))
                    if chunk_size > 0:
                        chunk = data_to_send[:chunk_size]
                        data_to_send = data_to_send[chunk_size:]
                        is_final = end_stream and len(data_to_send) == 0
                        self.h2_conn.send_data(stream_id, chunk, end_stream=is_final)
                        # Bookkeeping goes with the frame, before the
                        # drain: a reset processed meanwhile closes the
                        # stream and must not turn into a send error.
                        stream.send_data(chunk, end_stream=is_final)
                        wrote = self._write_locked()
                if chunk_size > 0:
                    # Outside the lock: a peer that stops reading must not
                    # hold up the receive loop or the other streams.
                    if wrote:
                        await self._drain()
                else:
                    # Wait for WINDOW_UPDATE per RFC 7540 Section 6.9.2
                    available = await self._wait_for_flow_control_window(stream_id)
                    if available == 0:
                        # The peer is there but not reading.
                        await self.abort_stream(stream_id, HTTP2ErrorCode.CANCEL)
                        return False
                    if available < 0:
                        return False

            return True
        except (_h2_exceptions.StreamClosedError, _h2_exceptions.FlowControlError):
            stream.close()
            self.cleanup_stream(stream_id)
            return False

    async def send_trailers(self, stream_id, trailers):
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
            def queue():
                self.h2_conn.send_headers(stream_id, trailer_headers, end_stream=True)
                stream.send_trailers(trailer_headers)

            await self._send(queue)
            return True
        except (_h2_exceptions.StreamClosedError, _h2_exceptions.StreamIDTooLowError):
            # Stream was reset by client - clean up gracefully
            stream.close()
            self.cleanup_stream(stream_id)
            return False

    async def send_error(self, stream_id, status_code, message=None):
        """Send an error response on a stream.

        Once the peer has a status the stream is cut off with
        RST_STREAM(INTERNAL_ERROR) instead: a second HEADERS block would
        corrupt the HPACK table.
        """
        stream = self.streams.get(stream_id)
        if stream is None or stream.response_headers_sent:
            await self.abort_stream(stream_id, HTTP2ErrorCode.INTERNAL_ERROR)
            return

        body = message.encode() if message else b''
        headers = [('content-length', str(len(body)))]
        if body:
            headers.append(('content-type', 'text/plain; charset=utf-8'))

        await self.send_response(stream_id, status_code, headers, body)

    async def reset_stream(self, stream_id, error_code=0x8):
        """Reset a stream with RST_STREAM."""
        await self.abort_stream(stream_id, error_code)

    async def abort_stream(self, stream_id, error_code):
        """Reset a stream, drop it, and tell the peer.

        Safe on a stream h2 already closed and on a dead socket.
        """
        stream = self.streams.get(stream_id)
        if stream is not None:
            stream.reset(error_code)
        try:
            await self._send(lambda: self._reset_quietly(stream_id, error_code))
        except HTTP2ConnectionError:
            pass
        if stream is not None:
            self.cleanup_stream(stream_id)

    async def close(self, error_code=0x0, last_stream_id=None):
        """Close the connection gracefully with GOAWAY."""
        if self._closed:
            return

        self._closed = True

        if last_stream_id is None:
            last_stream_id = max(self.streams.keys()) if self.streams else 0

        try:
            await self._send(lambda: self.h2_conn.close_connection(
                error_code=error_code, last_stream_id=last_stream_id))
        except Exception:
            pass
        self._abort_all_streams()
        self._signal_window()

        # Not awaited: the writer's protocol is a stand-in that never
        # sees connection_lost, so wait_closed() would never return.
        try:
            self.writer.close()
        except Exception:
            pass

    def _lock(self):
        if self._write_lock is None:
            self._write_lock = asyncio.Lock()
        return self._write_lock

    async def _send(self, queue_frames):
        """Queue frames on h2 and put them on the wire.

        Streams are served by concurrent tasks, so encoding and writing
        happen under one lock with no await between them: the receive
        loop cannot parse a GOAWAY (which clears h2's outbound buffer)
        in between, and HEADERS leave in the order they were encoded.
        Waiting for the transport happens after the lock is released.
        """
        async with self._lock():
            queue_frames()
            wrote = self._write_locked()
        if wrote:
            await self._drain()

    async def _send_pending_data(self):
        """Send whatever h2 already has queued and wait for the transport."""
        async with self._lock():
            wrote = self._write_locked()
        if wrote:
            await self._drain()

    async def _write_pending(self):
        """Send whatever h2 already has queued, without waiting.

        Used by the receive loop: what it has to send are control frames
        (SETTINGS and PING acknowledgements, WINDOW_UPDATE, RST_STREAM,
        GOAWAY), and waiting for the transport there would stop the
        connection from reading. Backpressure belongs on the response
        path, where the volume is.
        """
        async with self._lock():
            self._write_locked()

    def _write_locked(self):
        """Hand h2's pending bytes to the transport. Never waits.

        Returns:
            bool: True if there was anything to write
        """
        data = self.h2_conn.data_to_send()
        if not data:
            return False
        try:
            self.writer.write(data)
        except (OSError, IOError) as e:
            self._closed = True
            raise HTTP2ConnectionError(f"Socket write error: {e}")
        return True

    async def _drain(self):
        """Wait for the transport to catch up, for at most cfg.timeout.

        Holding the write lock here would let one peer that stops
        reading freeze the receive loop and every other stream on the
        connection, so this runs outside it. A peer that never catches
        up is treated as gone: nothing else bounds the wait, since it
        can keep its flow-control window wide open.
        """
        try:
            await asyncio.wait_for(self.writer.drain(), self.cfg.timeout or None)
        except asyncio.TimeoutError:
            self._closed = True
            self._abort_all_streams()
            self._signal_window()
            raise HTTP2ConnectionError("Write timed out: the peer stopped reading")
        except (OSError, IOError) as e:
            self._closed = True
            raise HTTP2ConnectionError(f"Socket write error: {e}")

    @property
    def is_closed(self):
        """Check if connection is closed."""
        return self._closed

    def cleanup_stream(self, stream_id):
        """Remove a stream after processing is complete.

        A response the application never finished is cut off with
        RST_STREAM(INTERNAL_ERROR); a body it did not finish reading with
        RST_STREAM(NO_ERROR) (RFC 9113 section 8.1).
        """
        stream = self.streams.pop(stream_id, None)
        if stream is None:
            return
        if stream.state is StreamState.CLOSED:
            pass
        elif not stream.response_complete:
            # The application never finished its response: the peer must
            # not wait for one.
            stream.reset(HTTP2ErrorCode.INTERNAL_ERROR)
            self._reset_quietly(stream_id, HTTP2ErrorCode.INTERNAL_ERROR)
        elif not stream.body_complete:
            stream.reset(HTTP2ErrorCode.NO_ERROR)
            self._reset_quietly(stream_id, HTTP2ErrorCode.NO_ERROR)
        # A listener still blocked in receive() after the app returned
        stream.signal_disconnect()
        if not self._closed:
            self._write_pending_nowait()

    def __repr__(self):
        return (
            f"<AsyncHTTP2Connection "
            f"streams={len(self.streams)} "
            f"closed={self._closed}>"
        )


__all__ = ['AsyncHTTP2Connection']
