# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
HTTP/2 server connection implementation.

Uses the hyper-h2 library for HTTP/2 protocol handling.
"""

import collections
import selectors
import time
from io import BytesIO

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
        # Events pulled off the wire while blocked on a flow-control window.
        # They have left the h2 state machine already, so they are held here
        # for the main receive loop rather than discarded.
        self._deferred_events = collections.deque()
        self._reset_times = collections.deque()

        # Requests that arrived while a request body was being pulled
        # off the socket; handed to the worker on its next call.
        self.pending_requests = collections.deque()
        # Peer sent a graceful GOAWAY: finish open streams, take no new ones
        self.draining = False
        self.peer_last_stream_id = None
        # Seconds a stream may make no progress on the wire; 0 means no limit
        self.stream_timeout = cfg.timeout or None
        # Seconds an idle connection may sit with no stream open; 0 means no limit
        self.idle_timeout = cfg.keepalive or None

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
            **({_h2_settings.SettingCodes.MAX_HEADER_LIST_SIZE: self.max_header_list_size}
               if self.max_header_list_size else {}),
        })

        self.h2_conn.initiate_connection()
        self._send_pending_data()
        self._initialized = True

    def initiate_upgrade(self, settings_header, http1_req, body=None):
        """Switch a connection to HTTP/2 after an Upgrade: h2c request.

        The upgraded request becomes stream 1 (RFC 7540 section 3.2). h2
        opens it in the state machine; the matching gunicorn stream is built
        here from the HTTP/1 request that carried the upgrade, so the worker
        sees an ordinary HTTP/2 request.

        ``body`` is the request payload. A caller that has to drain it before
        collecting the bytes pipelined behind the request passes it here;
        leaving it None reads it off the request.

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
        self._send_pending_data()
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

        if body is None:
            body = b""
            if http1_req.body is not None:
                body = http1_req.body.read() or b""
        stream.receive_headers(pseudo + regular, end_stream=not body)
        if body:
            stream.receive_data(body, end_stream=True)
            # That body came over HTTP/1, so no window credit is owed.
            stream.acked_size = stream.body_size
        self.streams[1] = stream
        return HTTP2Request(stream, self.cfg, self.client_addr)

    def receive_data(self, data=None):
        """Process received data and return new requests.

        A request is returned as soon as its headers are in; its body is
        read from the stream by the application, arriving frames being
        pulled in through pump() as needed.

        Args:
            data: Optional bytes to process. If None, reads from socket.

        Returns:
            list: List of HTTP2Request objects for new requests

        Raises:
            HTTP2ConnectionError: On protocol or connection errors
        """
        if data is None and self.pending_requests:
            pending = list(self.pending_requests)
            self.pending_requests.clear()
            return self._live_requests(pending)
        return self._read_and_process(data)

    def _live_requests(self, requests):
        """Drop requests whose stream the peer already reset."""
        live = []
        for request in requests:
            if request.stream.state is StreamState.CLOSED:
                self.streams.pop(request.stream.stream_id, None)
            else:
                live.append(request)
        return live

    def pump(self, stream_id=None):
        """Read once from the socket while a request body is being consumed.

        Frames for the stream being read land in its buffer; any request
        that arrives meanwhile is queued for the worker's next
        receive_data() call rather than dropped.

        Args:
            stream_id: The stream whose body is being read.
        """
        self.pending_requests.extend(self._read_and_process(None, stream_id))

    def _read_and_process(self, data, waiting_stream_id=None):
        if data is None and self._deferred_events:
            # Events set aside during a send-credit wait arrived before
            # anything still on the socket; hand them out without reading.
            return self._process_events(())
        if data is None:
            # A worker thread or greenlet sits in this read, so the read
            # itself has to bound how long a peer may keep it: cfg.timeout
            # while a request body is being pulled, cfg.keepalive between
            # requests.
            timeout = self.stream_timeout if waiting_stream_id is not None else self.idle_timeout
            try:
                self.sock.settimeout(timeout)
            except (OSError, AttributeError):
                pass
            try:
                data = self.sock.recv(self.READ_BUFFER_SIZE)
            except TimeoutError:
                if waiting_stream_id is not None:
                    # The body stalled; HTTP2Body finds the stream closed.
                    self.abort_stream(waiting_stream_id, HTTP2ErrorCode.CANCEL)
                elif not self.streams:
                    self.close()
                return []
            except (OSError, IOError) as e:
                raise HTTP2ConnectionError(f"Socket read error: {e}")

        if not data:
            # Connection closed by peer
            self._closed = True
            self._abort_all_streams()
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
        except UnicodeDecodeError as e:
            # Header bytes h2 could not decode
            self.close(error_code=HTTP2ErrorCode.PROTOCOL_ERROR)
            raise HTTP2ProtocolError(f"Undecodable header: {e}")
        except _h2_exceptions.ProtocolError as e:
            # Send GOAWAY with PROTOCOL_ERROR before raising
            self.close(error_code=HTTP2ErrorCode.PROTOCOL_ERROR)
            raise HTTP2ProtocolError(str(e))

        return self._process_events(events)

    def _process_events(self, events):
        """Run h2 events, oldest first, and return the new requests.

        Anything set aside during a flow-control wait arrived before
        this batch, so it goes first.
        """
        completed_requests = []
        if self._deferred_events:
            events = list(self._deferred_events) + list(events)
            self._deferred_events.clear()
        for event in events:
            request = self._handle_event(event)
            if request is not None:
                completed_requests.append(request)
        completed_requests = self._live_requests(completed_requests)

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

        Args:
            event: DataReceived event with body data
        """
        stream = self.streams.get(event.stream_id)
        if stream is None:
            # Stream was reset or doesn't exist
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

        Called by the stream as the application takes body data.
        """
        if size <= 0 or self._closed:
            return
        try:
            self.h2_conn.increment_flow_control_window(size, stream_id=stream_id)
        except (ValueError, KeyError, _h2_exceptions.ProtocolError):
            # h2 raises KeyError for a stream it already dropped
            return
        self._send_pending_data()

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

        # The request went out on its headers; only mark the body complete.
        stream.request_complete = True
        stream._body_complete = True
        if stream._body_event:
            stream._body_event.set()
        return None

    def _handle_stream_reset(self, event):
        """Handle StreamReset event (RST_STREAM frame).

        Args:
            event: StreamReset event
        """
        self._count_reset()
        stream_id = event.stream_id
        stream = self.streams.get(stream_id)

        if stream is None:
            return
        stream.reset(event.error_code)
        # A request the worker has not seen yet is dropped here; one it
        # is serving is cleaned up by the worker. Reset streams must not
        # accumulate: h2 only counts open ones against the limit.
        if any(r.stream is stream for r in self.pending_requests):
            self.pending_requests = collections.deque(
                r for r in self.pending_requests if r.stream is not stream)
            self.streams.pop(stream_id, None)

    def _handle_connection_terminated(self, event):
        """Handle ConnectionTerminated event (GOAWAY frame).

        A graceful GOAWAY (NO_ERROR) with streams in flight puts the
        connection into draining: the established streams finish, later
        ones are refused, and the connection closes once they are done
        (RFC 9113 section 6.8). The h2 subclass has already kept its own
        state open for that case. Any other GOAWAY closes at once.

        Args:
            event: ConnectionTerminated event
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
                self._send_pending_data()
            except Exception:
                pass
            self._abort_all_streams()
            raise HTTP2ProtocolError("RST_STREAM rate exceeded")

    def _abort_all_streams(self):
        """The connection is gone: wake every stream still waiting on it."""
        for stream in list(self.streams.values()):
            stream.signal_disconnect()

    def _reset_quietly(self, stream_id, error_code):
        """Queue RST_STREAM for a stream h2 knows about, ignoring a closed one."""
        try:
            self.h2_conn.reset_stream(stream_id, error_code=error_code)
        except _h2_exceptions.ProtocolError:
            pass

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
        if stream.response_headers_sent:
            raise HTTP2Error("Informational response after the final headers")

        # Build headers with :status pseudo-header
        response_headers = [(':status', str(status))]
        for name, value in headers:
            # HTTP/2 headers must be lowercase
            response_headers.append((name.lower(), str(value)))

        # Send headers with end_stream=False (informational, more to follow)
        self.h2_conn.send_headers(stream_id, response_headers, end_stream=False)
        self._send_pending_data()

    def send_response_headers(self, stream_id, status, headers,
                              end_stream=False):
        """Send response headers on a stream without ending it.

        Returns False if the stream is already gone. Split out of
        send_response() so a response can be streamed: headers first, then
        any number of data frames, then end_stream().
        """
        stream = self.streams.get(stream_id)
        if stream is None or stream.state is StreamState.CLOSED:
            # Stream was already cleaned up (reset/closed)
            return False
        if stream.response_headers_sent:
            # A second HEADERS block would be encoded into the HPACK table
            # before h2 refuses it, corrupting every later response.
            return False

        # Build response headers with :status pseudo-header
        response_headers = [(':status', str(status))]
        for name, value in headers:
            # HTTP/2 headers must be lowercase
            response_headers.append((name.lower(), str(value)))

        try:
            self.h2_conn.send_headers(stream_id, response_headers,
                                      end_stream=end_stream)
        except (_h2_exceptions.StreamClosedError, _h2_exceptions.StreamIDTooLowError):
            stream.close()
            self.cleanup_stream(stream_id)
            return False
        stream.send_headers(response_headers, end_stream=end_stream)
        self._send_pending_data()
        return True

    def end_stream(self, stream_id, trailers=None):
        """Close the sending half of a stream, with trailers if given."""
        if self.streams.get(stream_id) is None:
            return False
        if trailers:
            self.send_trailers(stream_id, trailers)
            return True
        return self.send_data(stream_id, b"", end_stream=True)

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
        end_stream = body is None or len(body) == 0
        try:
            if not self.send_response_headers(stream_id, status, headers,
                                              end_stream=end_stream):
                return False
            # Send body if present
            if body and len(body) > 0:
                self.send_data(stream_id, body, end_stream=True)
            return True
        except (_h2_exceptions.StreamClosedError, _h2_exceptions.StreamIDTooLowError):
            # Stream was reset by client - clean up gracefully
            stream = self.streams.get(stream_id)
            if stream is not None:
                stream.close()
            self.cleanup_stream(stream_id)
            return False

    def _wait_for_flow_control_window(self, stream_id, deadline=None):  # pylint: disable=too-many-return-statements
        """Wait for the stream's send window to become positive.

        Frames read while waiting are handled in order: a reset of this
        stream or a GOAWAY goes through the usual handlers (a graceful
        GOAWAY keeps the wait going), everything else is set aside for
        the main loop.

        Returns:
            int: Available window size; 0 if ``deadline`` passed first;
            -1 if the stream or the connection is gone.
        """
        try:
            sel = selectors.DefaultSelector()
            sel.register(self.sock, selectors.EVENT_READ)
        except (TypeError, ValueError):
            # Socket doesn't support selectors (e.g., mock socket)
            return -1

        try:
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
                wait = 1.0
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return 0
                    wait = min(remaining, wait)

                if not sel.select(timeout=wait):
                    continue
                try:
                    incoming = self.sock.recv(self.READ_BUFFER_SIZE)
                except (OSError, IOError):
                    incoming = b""
                if not incoming:
                    self._closed = True
                    self._abort_all_streams()
                    return -1
                try:
                    events = self.h2_conn.receive_data(incoming)
                except _h2_exceptions.ProtocolError:
                    self.close(error_code=HTTP2ErrorCode.PROTOCOL_ERROR)
                    return -1
                for event in events:
                    if (isinstance(event, _h2_events.StreamReset)
                            and event.stream_id == stream_id):
                        self._handle_stream_reset(event)
                    elif isinstance(event, _h2_events.ConnectionTerminated):
                        self._handle_connection_terminated(event)
                    else:
                        # Belongs to the main loop. It has already left the
                        # h2 state machine, so dropping it here would lose
                        # a request or its body for good.
                        self._deferred_events.append(event)
                self._send_pending_data()
        finally:
            sel.close()

    def send_data(self, stream_id, data, end_stream=False):  # pylint: disable=too-many-return-statements
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
        deadline = None
        try:
            if not data_to_send:
                if not end_stream:
                    return True
                # An empty DATA frame carrying END_STREAM needs no window
                # credit and is how a response with nothing left ends.
                self.h2_conn.send_data(stream_id, b"", end_stream=True)
                stream.send_data(b"", end_stream=True)
                self._send_pending_data()
                return True
            while data_to_send:
                available = self.h2_conn.local_flow_control_window(stream_id)
                chunk_size = min(available, self.h2_conn.max_outbound_frame_size, len(data_to_send))

                if chunk_size <= 0:
                    # Wait for WINDOW_UPDATE per RFC 7540 Section 6.9.2,
                    # for at most stream_timeout without progress.
                    self._send_pending_data()
                    if deadline is None and self.stream_timeout:
                        deadline = time.monotonic() + self.stream_timeout
                    available = self._wait_for_flow_control_window(stream_id, deadline)
                    if available == 0:
                        # The peer is there but not reading.
                        self.abort_stream(stream_id, HTTP2ErrorCode.CANCEL)
                        return False
                    if available < 0:
                        self.cleanup_stream(stream_id)
                        return False
                    chunk_size = min(available, self.h2_conn.max_outbound_frame_size, len(data_to_send))

                chunk = data_to_send[:chunk_size]
                data_to_send = data_to_send[chunk_size:]
                is_final = end_stream and len(data_to_send) == 0

                self.h2_conn.send_data(stream_id, chunk, end_stream=is_final)
                stream.send_data(chunk, end_stream=is_final)
                self._send_pending_data()
                deadline = None

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
        except (_h2_exceptions.StreamClosedError, _h2_exceptions.StreamIDTooLowError):
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
        stream = self.streams.get(stream_id)
        if stream is None or stream.response_headers_sent:
            # Too late for a status: the peer already has one. Cut the
            # stream off instead of corrupting the HPACK table with a
            # second HEADERS block.
            self.abort_stream(stream_id, HTTP2ErrorCode.INTERNAL_ERROR)
            return

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
        self.abort_stream(stream_id, error_code)

    def abort_stream(self, stream_id, error_code):
        """Reset a stream, drop it, and tell the peer.

        Safe on a stream h2 already closed and on a dead socket.
        """
        stream = self.streams.get(stream_id)
        if stream is not None:
            stream.reset(error_code)
        self._reset_quietly(stream_id, error_code)
        if stream is not None:
            self.cleanup_stream(stream_id)
        elif not self._closed:
            try:
                self._send_pending_data()
            except HTTP2ConnectionError:
                pass

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
            self.h2_conn.close_connection(error_code=error_code,
                                          last_stream_id=last_stream_id)
            self._send_pending_data()
        except Exception:
            pass  # Best effort
        self._abort_all_streams()

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

        A response the application never finished is cut off with
        RST_STREAM(INTERNAL_ERROR). A body it did not finish reading is
        cut off with RST_STREAM(NO_ERROR): the response is complete and
        the peer is only asked to stop sending (RFC 9113 section 8.1).

        Args:
            stream_id: The stream ID to clean up
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
        if self.draining and not self.streams and not self.pending_requests:
            # The peer's GOAWAY is honoured once the last established
            # stream is done.
            self.close()
            return
        if not self._closed:
            try:
                self._send_pending_data()
            except HTTP2ConnectionError:
                pass

    def __repr__(self):
        return (
            f"<HTTP2ServerConnection "
            f"streams={len(self.streams)} "
            f"closed={self._closed}>"
        )


__all__ = ['HTTP2ServerConnection']
