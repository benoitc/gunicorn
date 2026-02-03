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

    def test_disconnect_sends_message_to_queue(self, mock_worker):
        """Test that connection_lost sends http.disconnect to receive queue."""
        protocol = ASGIProtocol(mock_worker)
        protocol.reader = mock.Mock()
        mock_worker.nr_conns = 1

        # Create a receive queue (simulating active request)
        protocol._receive_queue = asyncio.Queue()

        # Simulate connection lost
        protocol.connection_lost(None)

        # Check that disconnect message was sent
        assert not protocol._receive_queue.empty()
        msg = protocol._receive_queue.get_nowait()
        assert msg == {"type": "http.disconnect"}

    def test_disconnect_is_idempotent(self, mock_worker):
        """Test that connection_lost can be called multiple times safely."""
        protocol = ASGIProtocol(mock_worker)
        protocol.reader = mock.Mock()
        mock_worker.nr_conns = 2  # Start with 2 so we can verify only 1 is decremented

        protocol._receive_queue = asyncio.Queue()

        # First call should work
        protocol.connection_lost(None)
        assert protocol._closed is True
        assert mock_worker.nr_conns == 1
        assert protocol._receive_queue.qsize() == 1

        # Second call should be a no-op
        protocol.connection_lost(None)
        assert mock_worker.nr_conns == 1  # Should not decrement again
        assert protocol._receive_queue.qsize() == 1  # Should not add another message

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
        protocol = ASGIProtocol(mock_worker)
        protocol._closed = True

        # Create receive queue with body complete
        receive_queue = asyncio.Queue()
        protocol._receive_queue = receive_queue

        # Add initial body message
        await receive_queue.put({
            "type": "http.request",
            "body": b"",
            "more_body": False,
        })

        # Simulate what happens in _handle_http_request
        body_complete = False

        async def receive():
            nonlocal body_complete
            if protocol._closed and body_complete:
                return {"type": "http.disconnect"}

            msg = await receive_queue.get()

            if msg.get("type") == "http.request" and not msg.get("more_body", True):
                body_complete = True

            return msg

        # First receive gets the body
        msg1 = await receive()
        assert msg1["type"] == "http.request"

        # Second receive should get disconnect
        msg2 = await receive()
        assert msg2["type"] == "http.disconnect"


class TestASGIDisconnectGracePeriod:
    """Test the grace period configuration."""

    def test_default_grace_period(self):
        """Test that the default grace period is reasonable."""
        from gunicorn.config import Config
        cfg = Config()
        assert cfg.asgi_disconnect_grace_period == 3
