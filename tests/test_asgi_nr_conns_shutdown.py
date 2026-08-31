#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Connection accounting across server-initiated closes.

Issue: https://github.com/benoitc/gunicorn/issues/3661

``connection_made()`` increments ``worker.nr_conns``.  A server-initiated
close goes through ``_close_transport()``, which sets ``_closed`` before
asyncio delivers ``connection_lost()``.  If the idempotence guard in
``connection_lost()`` keys off ``_closed``, the decrement never runs and the
counter leaks one per connection the server closed first: every
``Connection: close`` response, every keepalive timeout, every error abort.

``ASGIWorker._shutdown()`` waits on that counter, so a leaked count means
every graceful stop runs to the full ``graceful_timeout`` deadline and then
logs "Forcing close of N connections" for connections that are long gone.
"""

import asyncio
import logging
import types
from unittest import mock

import pytest

from gunicorn.asgi.protocol import ASGIProtocol
from gunicorn.config import Config
from gunicorn.workers.gasgi import ASGIWorker


class FakeTransport:
    """Plain HTTP/1.x transport: no ssl_object, close() is a no-op."""

    def __init__(self):
        self.closed = False

    def get_extra_info(self, name, default=None):
        return default

    def set_write_buffer_limits(self, high=None, low=None):
        pass

    def can_write_eof(self):
        return False

    def write_eof(self):
        pass

    def close(self):
        self.closed = True

    def is_closing(self):
        return self.closed


def make_worker(graceful_timeout=1):
    cfg = Config()
    cfg.set("graceful_timeout", graceful_timeout)
    return types.SimpleNamespace(
        cfg=cfg,
        loop=asyncio.get_running_loop(),
        nr_conns=0,
        alive=True,
        log=logging.getLogger("test.asgi.nr_conns"),
        asgi=None,
    )


def open_connection(worker):
    proto = ASGIProtocol(worker)
    proto.connection_made(FakeTransport())
    return proto


@pytest.mark.asyncio
async def test_server_initiated_close_decrements_nr_conns():
    """A close the server starts must still be counted down exactly once."""
    worker = make_worker()
    proto = open_connection(worker)
    assert worker.nr_conns == 1

    # Server closes first: Connection: close, keepalive timeout, error abort.
    proto._close_transport()
    # asyncio then reports the transport loss.
    proto.connection_lost(None)

    assert worker.nr_conns == 0


@pytest.mark.asyncio
async def test_client_initiated_close_decrements_nr_conns():
    """The already-working direction must keep working (no double decrement)."""
    worker = make_worker()
    proto = open_connection(worker)
    assert worker.nr_conns == 1

    proto.connection_lost(None)
    proto._close_transport()

    assert worker.nr_conns == 0


@pytest.mark.asyncio
async def test_keepalive_timeout_close_decrements_nr_conns():
    """The keepalive path closes server-side too and must stay balanced."""
    worker = make_worker()
    proto = open_connection(worker)
    assert worker.nr_conns == 1

    proto._keepalive_timeout()
    proto.connection_lost(None)

    assert worker.nr_conns == 0


@pytest.mark.asyncio
async def test_repeated_close_is_idempotent():
    """Extra close/lost callbacks must not drive the counter negative."""
    worker = make_worker()
    proto = open_connection(worker)

    proto._close_transport()
    proto._close_transport()
    proto.connection_lost(None)
    proto.connection_lost(None)

    assert worker.nr_conns == 0


@pytest.mark.asyncio
async def test_server_initiated_close_still_runs_full_cleanup():
    """The counter is not the only casualty of the early return.

    ``connection_lost()`` also cancels the keepalive timer, feeds EOF to the
    reader and tells the body receiver the peer is gone (see #3484).  A fix
    that only rebalances ``nr_conns`` leaves those undone, so pin them here.
    """
    worker = make_worker()
    proto = open_connection(worker)

    proto.reader = mock.Mock()
    proto._body_receiver = mock.Mock()
    proto._cancel_keepalive_timer = mock.Mock()

    proto._close_transport()
    proto.connection_lost(None)

    assert worker.nr_conns == 0
    assert proto._cancel_keepalive_timer.called, "keepalive timer left running"
    assert proto.reader.feed_eof.called, "reader never got EOF"
    assert proto._body_receiver.signal_disconnect.called, (
        "app never told the peer disconnected"
    )


@pytest.mark.asyncio
async def test_graceful_shutdown_does_not_wait_out_timeout(caplog):
    """The reported symptom: an idle worker must not burn graceful_timeout.

    Serve a few connections that the server closes first, then shut down.
    With the counter leaking, ``_shutdown()`` blocks until the deadline and
    warns about connections that no longer exist.
    """
    graceful_timeout = 1
    worker = make_worker(graceful_timeout=graceful_timeout)

    for _ in range(3):
        proto = open_connection(worker)
        proto._close_transport()
        proto.connection_lost(None)

    # Drive the real shutdown loop with the worker state we just produced.
    shutdown = ASGIWorker._shutdown.__get__(worker, ASGIWorker)
    worker.servers = []
    worker.lifespan = None
    worker._quick_shutdown = False

    loop = asyncio.get_running_loop()
    started = loop.time()
    with caplog.at_level(logging.INFO, logger="test.asgi.nr_conns"):
        await shutdown()
    elapsed = loop.time() - started

    forced = [r.getMessage() for r in caplog.records if "Forcing close" in r.getMessage()]
    assert elapsed < graceful_timeout, (
        "graceful shutdown took %.2fs of a %ds timeout with no live "
        "connections (nr_conns=%d, %s)"
        % (elapsed, graceful_timeout, worker.nr_conns, forced or "no warning")
    )
    assert not forced, "forced close of connections that were already gone: %s" % forced
