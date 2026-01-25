# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for HTTP/2 stream state management."""

import pytest
from unittest import mock

from gunicorn.http2.stream import HTTP2Stream, StreamState
from gunicorn.http2.errors import HTTP2StreamError


class MockConnection:
    """Mock HTTP/2 connection for testing streams."""

    def __init__(self, initial_window_size=65535):
        self.initial_window_size = initial_window_size


class TestStreamState:
    """Test StreamState enum values."""

    def test_state_values_exist(self):
        assert StreamState.IDLE is not None
        assert StreamState.RESERVED_LOCAL is not None
        assert StreamState.RESERVED_REMOTE is not None
        assert StreamState.OPEN is not None
        assert StreamState.HALF_CLOSED_LOCAL is not None
        assert StreamState.HALF_CLOSED_REMOTE is not None
        assert StreamState.CLOSED is not None

    def test_states_are_unique(self):
        states = [
            StreamState.IDLE,
            StreamState.RESERVED_LOCAL,
            StreamState.RESERVED_REMOTE,
            StreamState.OPEN,
            StreamState.HALF_CLOSED_LOCAL,
            StreamState.HALF_CLOSED_REMOTE,
            StreamState.CLOSED,
        ]
        assert len(states) == len(set(states))


class TestHTTP2StreamInitialization:
    """Test stream initialization."""

    def test_basic_init(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)

        assert stream.stream_id == 1
        assert stream.connection is conn
        assert stream.state == StreamState.IDLE
        assert stream.request_headers == []
        assert stream.request_complete is False
        assert stream.response_started is False
        assert stream.response_headers_sent is False
        assert stream.response_complete is False
        assert stream.window_size == 65535
        assert stream.trailers is None

    def test_custom_window_size(self):
        conn = MockConnection(initial_window_size=32768)
        stream = HTTP2Stream(stream_id=3, connection=conn)
        assert stream.window_size == 32768


class TestStreamIdProperties:
    """Test stream ID classification properties."""

    def test_is_client_stream_odd_ids(self):
        conn = MockConnection()
        for stream_id in [1, 3, 5, 7, 99, 101]:
            stream = HTTP2Stream(stream_id=stream_id, connection=conn)
            assert stream.is_client_stream is True
            assert stream.is_server_stream is False

    def test_is_server_stream_even_ids(self):
        conn = MockConnection()
        for stream_id in [2, 4, 6, 8, 100, 102]:
            stream = HTTP2Stream(stream_id=stream_id, connection=conn)
            assert stream.is_client_stream is False
            assert stream.is_server_stream is True

    def test_stream_id_zero(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=0, connection=conn)
        assert stream.is_client_stream is False
        assert stream.is_server_stream is True


class TestCanReceiveProperty:
    """Test can_receive property."""

    def test_can_receive_in_open_state(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.OPEN
        assert stream.can_receive is True

    def test_can_receive_in_half_closed_local(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.HALF_CLOSED_LOCAL
        assert stream.can_receive is True

    def test_cannot_receive_in_idle(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        assert stream.state == StreamState.IDLE
        assert stream.can_receive is False

    def test_cannot_receive_in_half_closed_remote(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.HALF_CLOSED_REMOTE
        assert stream.can_receive is False

    def test_cannot_receive_in_closed(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.CLOSED
        assert stream.can_receive is False


class TestCanSendProperty:
    """Test can_send property."""

    def test_can_send_in_open_state(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.OPEN
        assert stream.can_send is True

    def test_can_send_in_half_closed_remote(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.HALF_CLOSED_REMOTE
        assert stream.can_send is True

    def test_cannot_send_in_idle(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        assert stream.state == StreamState.IDLE
        assert stream.can_send is False

    def test_cannot_send_in_half_closed_local(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.HALF_CLOSED_LOCAL
        assert stream.can_send is False

    def test_cannot_send_in_closed(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.CLOSED
        assert stream.can_send is False


class TestReceiveHeaders:
    """Test receive_headers method."""

    def test_receive_headers_from_idle(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        headers = [(':method', 'GET'), (':path', '/')]

        stream.receive_headers(headers, end_stream=False)

        assert stream.state == StreamState.OPEN
        assert stream.request_headers == headers
        assert stream.request_complete is False

    def test_receive_headers_with_end_stream(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        headers = [(':method', 'GET'), (':path', '/')]

        stream.receive_headers(headers, end_stream=True)

        assert stream.state == StreamState.HALF_CLOSED_REMOTE
        assert stream.request_complete is True

    def test_receive_headers_in_open_state(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.OPEN

        headers = [('content-type', 'text/plain')]
        stream.receive_headers(headers, end_stream=False)

        assert stream.state == StreamState.OPEN
        assert stream.request_headers == headers

    def test_receive_headers_extends_existing(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.receive_headers([(':method', 'POST')], end_stream=False)
        stream.receive_headers([('content-type', 'text/plain')], end_stream=False)

        assert len(stream.request_headers) == 2

    def test_receive_headers_in_invalid_state(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.CLOSED

        with pytest.raises(HTTP2StreamError) as exc_info:
            stream.receive_headers([], end_stream=False)
        assert exc_info.value.stream_id == 1


class TestReceiveData:
    """Test receive_data method."""

    def test_receive_data_in_open_state(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.OPEN

        stream.receive_data(b"Hello, World!", end_stream=False)

        assert stream.request_body.getvalue() == b"Hello, World!"
        assert stream.request_complete is False

    def test_receive_data_with_end_stream(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.OPEN

        stream.receive_data(b"Final data", end_stream=True)

        assert stream.state == StreamState.HALF_CLOSED_REMOTE
        assert stream.request_complete is True

    def test_receive_data_accumulates(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.OPEN

        stream.receive_data(b"Part1")
        stream.receive_data(b"Part2")
        stream.receive_data(b"Part3", end_stream=True)

        assert stream.request_body.getvalue() == b"Part1Part2Part3"

    def test_receive_data_in_half_closed_local(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.HALF_CLOSED_LOCAL

        stream.receive_data(b"data", end_stream=False)
        assert stream.request_body.getvalue() == b"data"

    def test_receive_data_in_invalid_state(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.HALF_CLOSED_REMOTE

        with pytest.raises(HTTP2StreamError) as exc_info:
            stream.receive_data(b"data", end_stream=False)
        assert exc_info.value.stream_id == 1


class TestReceiveTrailers:
    """Test receive_trailers method."""

    def test_receive_trailers_in_open_state(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.OPEN

        trailers = [('grpc-status', '0')]
        stream.receive_trailers(trailers)

        assert stream.trailers == trailers
        assert stream.state == StreamState.HALF_CLOSED_REMOTE
        assert stream.request_complete is True

    def test_receive_trailers_in_invalid_state(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.CLOSED

        with pytest.raises(HTTP2StreamError):
            stream.receive_trailers([])


class TestSendHeaders:
    """Test send_headers method."""

    def test_send_headers_in_open_state(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.OPEN

        headers = [(':status', '200')]
        stream.send_headers(headers, end_stream=False)

        assert stream.response_started is True
        assert stream.response_headers_sent is True
        assert stream.response_complete is False
        assert stream.state == StreamState.OPEN

    def test_send_headers_with_end_stream(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.OPEN

        stream.send_headers([(':status', '204')], end_stream=True)

        assert stream.state == StreamState.HALF_CLOSED_LOCAL
        assert stream.response_complete is True

    def test_send_headers_in_half_closed_remote(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.HALF_CLOSED_REMOTE

        stream.send_headers([(':status', '200')], end_stream=False)
        assert stream.response_headers_sent is True

    def test_send_headers_in_invalid_state(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.HALF_CLOSED_LOCAL

        with pytest.raises(HTTP2StreamError):
            stream.send_headers([], end_stream=False)


class TestSendData:
    """Test send_data method."""

    def test_send_data_in_open_state(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.OPEN

        stream.send_data(b"Response body", end_stream=False)
        assert stream.response_complete is False

    def test_send_data_with_end_stream(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.OPEN

        stream.send_data(b"Final", end_stream=True)

        assert stream.state == StreamState.HALF_CLOSED_LOCAL
        assert stream.response_complete is True

    def test_send_data_in_half_closed_remote(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.HALF_CLOSED_REMOTE

        stream.send_data(b"data", end_stream=True)
        assert stream.state == StreamState.CLOSED

    def test_send_data_in_invalid_state(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.CLOSED

        with pytest.raises(HTTP2StreamError):
            stream.send_data(b"data", end_stream=False)


class TestStreamReset:
    """Test stream reset method."""

    def test_reset_default_error_code(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.OPEN

        stream.reset()

        assert stream.state == StreamState.CLOSED
        assert stream.response_complete is True
        assert stream.request_complete is True

    def test_reset_custom_error_code(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.OPEN

        stream.reset(error_code=0x1)  # PROTOCOL_ERROR

        assert stream.state == StreamState.CLOSED


class TestStreamClose:
    """Test stream close method."""

    def test_close_stream(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.OPEN

        stream.close()

        assert stream.state == StreamState.CLOSED
        assert stream.response_complete is True
        assert stream.request_complete is True


class TestHalfCloseTransitions:
    """Test half-close state transitions."""

    def test_half_close_local_from_open(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.OPEN

        stream._half_close_local()
        assert stream.state == StreamState.HALF_CLOSED_LOCAL

    def test_half_close_local_from_half_closed_remote(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.HALF_CLOSED_REMOTE

        stream._half_close_local()
        assert stream.state == StreamState.CLOSED

    def test_half_close_local_invalid_state(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.IDLE

        with pytest.raises(HTTP2StreamError):
            stream._half_close_local()

    def test_half_close_remote_from_open(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.OPEN

        stream._half_close_remote()
        assert stream.state == StreamState.HALF_CLOSED_REMOTE

    def test_half_close_remote_from_half_closed_local(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.HALF_CLOSED_LOCAL

        stream._half_close_remote()
        assert stream.state == StreamState.CLOSED

    def test_half_close_remote_invalid_state(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.IDLE

        with pytest.raises(HTTP2StreamError):
            stream._half_close_remote()


class TestGetRequestBody:
    """Test get_request_body method."""

    def test_get_empty_body(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        assert stream.get_request_body() == b""

    def test_get_body_after_data(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.state = StreamState.OPEN
        stream.receive_data(b"Test body content")

        assert stream.get_request_body() == b"Test body content"


class TestGetPseudoHeaders:
    """Test get_pseudo_headers method."""

    def test_extract_pseudo_headers(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.request_headers = [
            (':method', 'POST'),
            (':path', '/api/test'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
            ('content-type', 'application/json'),
            ('accept', '*/*'),
        ]

        pseudo = stream.get_pseudo_headers()

        assert pseudo == {
            ':method': 'POST',
            ':path': '/api/test',
            ':scheme': 'https',
            ':authority': 'example.com',
        }

    def test_empty_pseudo_headers(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.request_headers = [
            ('content-type', 'text/plain'),
        ]

        pseudo = stream.get_pseudo_headers()
        assert pseudo == {}


class TestGetRegularHeaders:
    """Test get_regular_headers method."""

    def test_extract_regular_headers(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.request_headers = [
            (':method', 'GET'),
            (':path', '/'),
            ('content-type', 'text/html'),
            ('accept-language', 'en-US'),
        ]

        regular = stream.get_regular_headers()

        assert regular == [
            ('content-type', 'text/html'),
            ('accept-language', 'en-US'),
        ]

    def test_no_regular_headers(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)
        stream.request_headers = [
            (':method', 'GET'),
            (':path', '/'),
        ]

        regular = stream.get_regular_headers()
        assert regular == []


class TestStreamRepr:
    """Test stream string representation."""

    def test_repr_format(self):
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=5, connection=conn)
        repr_str = repr(stream)

        assert "HTTP2Stream" in repr_str
        assert "id=5" in repr_str
        assert "state=IDLE" in repr_str
        assert "req_complete=False" in repr_str
        assert "resp_complete=False" in repr_str


class TestFullStreamLifecycle:
    """Test complete stream lifecycles."""

    def test_simple_get_request(self):
        """Test a simple GET request lifecycle."""
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)

        # Receive request headers (GET with end_stream)
        stream.receive_headers([
            (':method', 'GET'),
            (':path', '/'),
            (':scheme', 'https'),
            (':authority', 'example.com'),
        ], end_stream=True)

        assert stream.state == StreamState.HALF_CLOSED_REMOTE
        assert stream.request_complete is True

        # Send response headers with body
        stream.send_headers([(':status', '200')], end_stream=False)
        assert stream.state == StreamState.HALF_CLOSED_REMOTE

        # Send response body
        stream.send_data(b"Hello!", end_stream=True)
        assert stream.state == StreamState.CLOSED
        assert stream.response_complete is True

    def test_post_request_with_body(self):
        """Test a POST request with body."""
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)

        # Receive request headers
        stream.receive_headers([
            (':method', 'POST'),
            (':path', '/submit'),
            ('content-type', 'application/json'),
        ], end_stream=False)

        assert stream.state == StreamState.OPEN

        # Receive body data
        stream.receive_data(b'{"key": "value"}', end_stream=True)
        assert stream.state == StreamState.HALF_CLOSED_REMOTE
        assert stream.get_request_body() == b'{"key": "value"}'

        # Send response
        stream.send_headers([(':status', '201')], end_stream=False)
        stream.send_data(b'Created', end_stream=True)

        assert stream.state == StreamState.CLOSED

    def test_stream_reset_lifecycle(self):
        """Test a stream that gets reset."""
        conn = MockConnection()
        stream = HTTP2Stream(stream_id=1, connection=conn)

        stream.receive_headers([(':method', 'GET'), (':path', '/')], end_stream=False)
        assert stream.state == StreamState.OPEN

        # Reset the stream
        stream.reset(error_code=0x8)  # CANCEL

        assert stream.state == StreamState.CLOSED
        assert stream.request_complete is True
        assert stream.response_complete is True
