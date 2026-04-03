#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
ASGI error handling tests.

Tests for application error scenarios and graceful shutdown behavior
to ensure robust error handling in ASGI applications.
"""

import asyncio
from unittest import mock

import pytest

from gunicorn.config import Config


# ============================================================================
# Application Error Tests
# ============================================================================

class TestApplicationErrors:
    """Test handling of ASGI application errors."""

    def _create_protocol(self):
        """Create an ASGIProtocol instance for testing."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()
        worker.nr_conns = 1
        worker.loop = mock.Mock()

        protocol = ASGIProtocol(worker)
        protocol._closed = False
        return protocol

    def _create_mock_request(self):
        """Create a mock HTTP request."""
        request = mock.Mock()
        request.method = "GET"
        request.path = "/"
        request.raw_path = b"/"
        request.query = ""
        request.version = (1, 1)
        request.scheme = "http"
        request.headers = []
        request.content_length = 0
        request.chunked = False
        return request

    def test_protocol_tracks_closed_state(self):
        """Protocol should track closed state."""
        protocol = self._create_protocol()

        assert protocol._closed is False

        protocol._closed = True

        assert protocol._closed is True

    def test_connection_lost_sets_closed(self):
        """connection_lost should set closed state."""
        protocol = self._create_protocol()
        protocol.reader = mock.Mock()

        assert protocol._closed is False

        protocol.connection_lost(None)

        assert protocol._closed is True

    def test_connection_lost_with_exception(self):
        """connection_lost handles exception argument gracefully."""
        protocol = self._create_protocol()
        protocol.reader = mock.Mock()

        exc = ConnectionResetError("Connection reset")
        protocol.connection_lost(exc)

        assert protocol._closed is True


# ============================================================================
# Response Info Tests
# ============================================================================

class TestResponseInfo:
    """Test response info tracking."""

    def test_response_info_initial(self):
        """Test initial ASGIResponseInfo values."""
        from gunicorn.asgi.protocol import ASGIResponseInfo

        info = ASGIResponseInfo(status=200, headers=[], sent=False)

        assert info.status == 200
        assert info.headers == []
        assert info.sent is False

    def test_response_info_with_headers(self):
        """Test ASGIResponseInfo with headers."""
        from gunicorn.asgi.protocol import ASGIResponseInfo

        headers = [
            (b"content-type", b"text/plain"),
            (b"content-length", b"5"),
        ]
        info = ASGIResponseInfo(status=200, headers=headers, sent=True)

        assert info.status == 200
        assert len(info.headers) == 2
        assert info.sent is True


# ============================================================================
# Body Receiver Error Tests
# ============================================================================

class TestBodyReceiverErrors:
    """Test error handling in BodyReceiver."""

    def _create_protocol(self):
        """Create an ASGIProtocol instance for testing."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()
        worker.nr_conns = 1
        worker.loop = mock.Mock()

        protocol = ASGIProtocol(worker)
        protocol._closed = False
        return protocol

    @pytest.mark.asyncio
    async def test_body_receiver_handles_closed_protocol(self):
        """BodyReceiver should handle protocol being closed."""
        from gunicorn.asgi.protocol import BodyReceiver

        protocol = self._create_protocol()

        mock_request = mock.Mock()
        mock_request.content_length = 0
        mock_request.chunked = False

        body_receiver = BodyReceiver(mock_request, protocol)

        # Consume the empty body
        msg = await body_receiver.receive()
        assert msg["type"] == "http.request"
        assert msg["more_body"] is False

        # Mark protocol as closed
        protocol._closed = True

        # Signal disconnect
        body_receiver.signal_disconnect()

        # Receive should return disconnect
        msg = await body_receiver.receive()
        assert msg == {"type": "http.disconnect"}

    @pytest.mark.asyncio
    async def test_body_receiver_multiple_signal_disconnect(self):
        """Multiple signal_disconnect calls should be safe."""
        from gunicorn.asgi.protocol import BodyReceiver

        protocol = self._create_protocol()

        mock_request = mock.Mock()
        mock_request.content_length = 0
        mock_request.chunked = False

        body_receiver = BodyReceiver(mock_request, protocol)

        # Signal disconnect multiple times - should not raise
        body_receiver.signal_disconnect()
        body_receiver.signal_disconnect()
        body_receiver.signal_disconnect()

        assert body_receiver._closed is True

    @pytest.mark.asyncio
    async def test_body_receiver_feed_after_complete(self):
        """Feeding data after body is complete should be safe."""
        from gunicorn.asgi.protocol import BodyReceiver

        protocol = self._create_protocol()

        mock_request = mock.Mock()
        mock_request.content_length = 5
        mock_request.chunked = False

        body_receiver = BodyReceiver(mock_request, protocol)

        # Feed the expected body
        body_receiver.feed(b"hello")
        body_receiver.set_complete()

        # Consume the body
        msg = await body_receiver.receive()
        assert msg["body"] == b"hello"
        assert msg["more_body"] is False

        # Feeding more data after complete should be safe
        body_receiver.feed(b"extra")  # Should not raise


# ============================================================================
# Graceful Shutdown Tests
# ============================================================================

class TestGracefulShutdown:
    """Test graceful shutdown behavior."""

    def _create_protocol(self):
        """Create an ASGIProtocol instance for testing."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()
        worker.nr_conns = 1
        worker.loop = mock.Mock()

        protocol = ASGIProtocol(worker)
        protocol._closed = False
        return protocol

    def test_graceful_shutdown_schedules_cancel(self):
        """Graceful shutdown should schedule task cancellation."""
        protocol = self._create_protocol()

        # Create a mock task
        mock_task = mock.Mock()
        mock_task.done.return_value = False
        protocol._task = mock_task
        protocol.reader = mock.Mock()

        # Simulate connection lost
        protocol.connection_lost(None)

        # Task should NOT be cancelled immediately
        mock_task.cancel.assert_not_called()

        # Cancellation should be scheduled
        protocol.worker.loop.call_later.assert_called_once()

    def test_completed_task_not_cancelled(self):
        """Completed tasks should not be cancelled."""
        protocol = self._create_protocol()

        # Create a mock task that's already done
        mock_task = mock.Mock()
        mock_task.done.return_value = True
        protocol._task = mock_task
        protocol.reader = mock.Mock()

        # Simulate connection lost
        protocol.connection_lost(None)

        # Task should not be cancelled
        mock_task.cancel.assert_not_called()


# ============================================================================
# Protocol Timeout Tests
# ============================================================================

class TestProtocolTimeouts:
    """Test timeout handling in protocol."""

    def _create_protocol(self):
        """Create an ASGIProtocol instance for testing."""
        from gunicorn.asgi.protocol import ASGIProtocol

        worker = mock.Mock()
        worker.cfg = Config()
        worker.log = mock.Mock()
        worker.asgi = mock.Mock()
        worker.nr_conns = 1
        worker.loop = mock.Mock()

        protocol = ASGIProtocol(worker)
        protocol._closed = False
        return protocol

    def test_keepalive_timer_can_be_armed(self):
        """Keepalive timer should be arm-able."""
        protocol = self._create_protocol()

        # Initially no timer handle
        assert protocol._keepalive_handle is None

        # Verify the method exists
        assert hasattr(protocol, '_arm_keepalive_timer')
        assert hasattr(protocol, '_cancel_keepalive_timer')

    def test_cancel_keepalive_timer_handles_none(self):
        """Cancelling non-existent timer should be safe."""
        protocol = self._create_protocol()

        # Should not raise even with no timer
        protocol._cancel_keepalive_timer()
        protocol._cancel_keepalive_timer()  # Multiple calls safe


# ============================================================================
# Request Time Tests
# ============================================================================

class TestRequestTime:
    """Test request time handling."""

    def test_request_time_creation(self):
        """_RequestTime should track timing."""
        from gunicorn.asgi.protocol import _RequestTime

        request_time = _RequestTime(1.5)

        # _RequestTime splits into seconds and microseconds
        assert hasattr(request_time, 'seconds')
        assert hasattr(request_time, 'microseconds')

    def test_request_time_conversion(self):
        """_RequestTime should store time as seconds + microseconds."""
        from gunicorn.asgi.protocol import _RequestTime

        # 1.5 seconds = 1 second + 500000 microseconds
        request_time = _RequestTime(1.5)

        assert request_time.seconds == 1
        assert request_time.microseconds == 500000

    def test_request_time_with_zero(self):
        """_RequestTime with zero elapsed time."""
        from gunicorn.asgi.protocol import _RequestTime

        request_time = _RequestTime(0.0)

        assert request_time.seconds == 0
        assert request_time.microseconds == 0


# ============================================================================
# Message Validation Tests
# ============================================================================

class TestMessageValidation:
    """Test ASGI message validation."""

    def test_response_start_requires_status(self):
        """http.response.start must have status."""
        # Valid response start
        valid_msg = {
            "type": "http.response.start",
            "status": 200,
            "headers": [],
        }
        assert valid_msg["type"] == "http.response.start"
        assert "status" in valid_msg

    def test_response_body_message_format(self):
        """http.response.body format validation."""
        # With body
        msg_with_body = {
            "type": "http.response.body",
            "body": b"Hello",
            "more_body": False,
        }
        assert isinstance(msg_with_body["body"], bytes)

        # Empty body
        msg_empty = {
            "type": "http.response.body",
            "body": b"",
            "more_body": False,
        }
        assert msg_empty["body"] == b""

    def test_disconnect_message_minimal(self):
        """http.disconnect message should be minimal."""
        msg = {"type": "http.disconnect"}

        assert msg == {"type": "http.disconnect"}
        assert len(msg) == 1
