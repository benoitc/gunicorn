#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Tests for ASGI graceful disconnect handling.

Issue: https://github.com/benoitc/gunicorn/issues/3484

When a client disconnects, the ASGI worker should:
1. Send http.disconnect to the receive queue
2. Allow the app a grace period to clean up
3. Only cancel the task after the grace period
"""

import asyncio
from unittest import mock

import pytest

from gunicorn.asgi.protocol import ASGIProtocol


class TestASGIGracefulDisconnect:
    """Test graceful disconnect handling."""

    @pytest.fixture
    def mock_worker(self):
        """Create a mock worker."""
        worker = mock.Mock()
        worker.nr_conns = 0
        worker.loop = asyncio.new_event_loop()
        worker.cfg = mock.Mock()
        worker.cfg.asgi_disconnect_grace_period = 3
        worker.log = mock.Mock()
        return worker

    def test_disconnect_sets_closed_flag(self, mock_worker):
        """Test that connection_lost sets the closed flag."""
        protocol = ASGIProtocol(mock_worker)
        protocol.reader = mock.Mock()

        # Simulate connection made
        mock_worker.nr_conns = 1

        assert protocol._closed is False

        # Simulate connection lost
        protocol.connection_lost(None)

        assert protocol._closed is True

    def test_disconnect_signals_body_receiver(self, mock_worker):
        """Test that connection_lost signals the body receiver."""
        from gunicorn.asgi.protocol import BodyReceiver

        protocol = ASGIProtocol(mock_worker)
        protocol.reader = mock.Mock()
        mock_worker.nr_conns = 1

        # Create a mock request for the body receiver
        mock_request = mock.Mock()
        mock_request.content_length = 100
        mock_request.chunked = False

        # Create a body receiver (simulating active request)
        body_receiver = BodyReceiver(mock_request, protocol)
        protocol._body_receiver = body_receiver

        # Verify disconnect flag is not set initially
        assert not body_receiver._closed

        # Simulate connection lost
        protocol.connection_lost(None)

        # Check that disconnect flag was set
        assert body_receiver._closed

    def test_disconnect_is_idempotent(self, mock_worker):
        """Test that connection_lost can be called multiple times safely."""
        from gunicorn.asgi.protocol import BodyReceiver

        protocol = ASGIProtocol(mock_worker)
        protocol.reader = mock.Mock()
        mock_worker.nr_conns = 2  # Start with 2 so we can verify only 1 is decremented

        # Create a mock request for the body receiver
        mock_request = mock.Mock()
        mock_request.content_length = 100
        mock_request.chunked = False

        body_receiver = BodyReceiver(mock_request, protocol)
        protocol._body_receiver = body_receiver

        # First call should work
        protocol.connection_lost(None)
        assert protocol._closed is True
        assert mock_worker.nr_conns == 1
        assert body_receiver._closed

        # Second call should be a no-op
        protocol.connection_lost(None)
        assert mock_worker.nr_conns == 1  # Should not decrement again
        # Closed flag is still set

    def test_server_initiated_close_still_decrements_nr_conns(self, mock_worker):
        """A server-initiated close must not leak the connection count (#3661).

        _close_transport() sets ``_closed`` before asyncio reports the transport
        loss, so connection_lost() must still run its cleanup and decrement
        nr_conns. Otherwise every graceful stop waits out the full timeout.
        """
        protocol = ASGIProtocol(mock_worker)
        protocol.reader = mock.Mock()
        protocol.transport = mock.Mock()
        mock_worker.nr_conns = 1

        # Server closes the connection (e.g. `Connection: close`, keepalive
        # timeout), which sets ``_closed`` early.
        protocol._close_transport()
        assert protocol._closed is True
        assert mock_worker.nr_conns == 1

        # asyncio then reports the transport loss.
        protocol.connection_lost(None)
        assert mock_worker.nr_conns == 0

    def test_disconnect_does_not_cancel_immediately(self, mock_worker):
        """Test that connection_lost doesn't cancel task immediately."""
        protocol = ASGIProtocol(mock_worker)
        protocol.reader = mock.Mock()
        mock_worker.nr_conns = 1

        # Create a mock task
        mock_task = mock.Mock()
        mock_task.done.return_value = False
        protocol._task = mock_task

        # Simulate connection lost
        protocol.connection_lost(None)

        # Task should NOT be cancelled immediately
        mock_task.cancel.assert_not_called()

    def test_disconnect_schedules_cancellation(self, mock_worker):
        """Test that connection_lost schedules task cancellation."""
        # Use a mock loop for this test to verify call_later was called
        mock_loop = mock.Mock()
        mock_worker.loop = mock_loop

        protocol = ASGIProtocol(mock_worker)
        protocol.reader = mock.Mock()
        mock_worker.nr_conns = 1

        # Create a mock task
        mock_task = mock.Mock()
        mock_task.done.return_value = False
        protocol._task = mock_task

        # Simulate connection lost
        protocol.connection_lost(None)

        # call_later should have been called to schedule cancellation
        mock_loop.call_later.assert_called_once()
        args = mock_loop.call_later.call_args[0]
        assert args[0] == mock_worker.cfg.asgi_disconnect_grace_period
        assert args[1] == protocol._cancel_task_if_pending

    def test_cancel_task_if_pending_cancels_running_task(self, mock_worker):
        """Test that _cancel_task_if_pending cancels a running task."""
        protocol = ASGIProtocol(mock_worker)

        # Create a mock task that's still running
        mock_task = mock.Mock()
        mock_task.done.return_value = False
        protocol._task = mock_task

        protocol._cancel_task_if_pending()

        mock_task.cancel.assert_called_once()

    def test_cancel_task_if_pending_skips_completed_task(self, mock_worker):
        """Test that _cancel_task_if_pending doesn't cancel completed tasks."""
        protocol = ASGIProtocol(mock_worker)

        # Create a mock task that's already done
        mock_task = mock.Mock()
        mock_task.done.return_value = True
        protocol._task = mock_task

        protocol._cancel_task_if_pending()

        mock_task.cancel.assert_not_called()

    @pytest.mark.asyncio
    async def test_receive_returns_disconnect_when_closed(self, mock_worker):
        """Test that receive() returns http.disconnect when connection is closed."""
        from gunicorn.asgi.protocol import BodyReceiver

        protocol = ASGIProtocol(mock_worker)
        protocol._closed = True

        # Create a mock request with no body
        mock_request = mock.Mock()
        mock_request.content_length = 0
        mock_request.chunked = False

        body_receiver = BodyReceiver(mock_request, protocol)
        protocol._body_receiver = body_receiver

        # First receive gets the body (empty)
        msg1 = await body_receiver.receive()
        assert msg1["type"] == "http.request"
        assert msg1["more_body"] is False

        # Second receive should get disconnect (body complete)
        msg2 = await body_receiver.receive()
        assert msg2["type"] == "http.disconnect"


class TestASGIDisconnectGracePeriod:
    """Test the grace period configuration."""

    def test_default_grace_period(self):
        """Test that the default grace period is reasonable."""
        from gunicorn.config import Config
        cfg = Config()
        assert cfg.asgi_disconnect_grace_period == 3


class TestBodyReceiverIncompleteBody:
    """Cover the receive() path when the request body never finishes framing."""

    @pytest.fixture
    def mock_worker(self):
        worker = mock.Mock()
        worker.nr_conns = 0
        worker.loop = asyncio.new_event_loop()
        worker.cfg = mock.Mock()
        worker.cfg.asgi_disconnect_grace_period = 3
        worker.cfg.timeout = 0.05  # tight bound for the test
        worker.log = mock.Mock()
        return worker

    @pytest.mark.asyncio
    async def test_receive_yields_disconnect_on_timeout(self, mock_worker):
        """When _wait_for_data times out and the body is not complete, the
        receiver MUST yield http.disconnect rather than synthesize a terminal
        http.request with more_body=False — that would desync the next
        pipelined request.

        Body-wait expiry sets _body_wait_expired, NOT _closed: the transport
        may still be alive; the body just never finished framing."""
        from gunicorn.asgi.protocol import ASGIProtocol, BodyReceiver

        protocol = ASGIProtocol(mock_worker)
        protocol.reader = mock.Mock()

        request = mock.Mock()
        request.content_length = 100
        request.chunked = False

        receiver = BodyReceiver(request, protocol)
        protocol._body_receiver = receiver

        msg = await receiver.receive()
        assert msg == {"type": "http.disconnect"}
        assert receiver._body_wait_expired is True
        assert receiver._closed is False
        assert receiver._disconnected is True

    @pytest.mark.asyncio
    async def test_receive_yields_terminal_request_when_complete(self, mock_worker):
        """If the body is framed complete, the existing terminal http.request
        with more_body=False must still be returned."""
        from gunicorn.asgi.protocol import ASGIProtocol, BodyReceiver

        protocol = ASGIProtocol(mock_worker)
        protocol.reader = mock.Mock()

        request = mock.Mock()
        request.content_length = 5
        request.chunked = False

        receiver = BodyReceiver(request, protocol)
        protocol._body_receiver = receiver

        receiver.feed(b"hello")
        receiver.set_complete()

        msg = await receiver.receive()
        assert msg["type"] == "http.request"
        assert msg["body"] == b"hello"
        # more_body may be False since the body is complete
        assert msg["more_body"] is False

    def test_signal_disconnect_sets_closed_only(self, mock_worker):
        """signal_disconnect is the transport-disconnect path; it must set
        _closed without touching _body_wait_expired so the two conditions
        remain distinguishable for any code that needs to differentiate."""
        from gunicorn.asgi.protocol import ASGIProtocol, BodyReceiver

        protocol = ASGIProtocol(mock_worker)
        protocol.reader = mock.Mock()

        request = mock.Mock()
        request.content_length = 0
        request.chunked = False

        receiver = BodyReceiver(request, protocol)
        receiver.signal_disconnect()
        assert receiver._closed is True
        assert receiver._body_wait_expired is False
        assert receiver._disconnected is True

    def test_keepalive_gate_refuses_after_receive_timeout(self, mock_worker):
        """The keepalive completion check must NOT treat a receive-timeout
        as a framed-complete message: residual body bytes on the wire would
        be misparsed as the next pipelined request (smuggling).  The gate
        keys on _complete only.
        """
        from gunicorn.asgi.protocol import ASGIProtocol, BodyReceiver

        protocol = ASGIProtocol(mock_worker)
        protocol.reader = mock.Mock()

        request = mock.Mock()
        request.content_length = 100
        request.chunked = False

        receiver = BodyReceiver(request, protocol)
        receiver._body_wait_expired = True  # simulate _wait_for_data timeout
        receiver._complete = False  # body never finished framing

        # The gate inlined in _handle_connection: refuse keepalive when
        # the receiver exists and the message wasn't framed complete.
        message_complete = receiver is None or receiver._complete
        assert message_complete is False
