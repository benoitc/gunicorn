#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for TCP RST prevention via request body draining (issue #3334)."""

import os
from unittest import mock

from gunicorn.config import Config
from gunicorn.workers import sync as sync_mod
from gunicorn.workers import gthread
from gunicorn.workers import base_async


def _make_cfg(**overrides):
    cfg = Config()
    cfg.set('workers', 1)
    cfg.set('threads', 1)
    cfg.set('worker_connections', 100)
    for key, value in overrides.items():
        cfg.set(key, value)
    return cfg


def _make_worker(cls, cfg=None, **kwargs):
    cfg = cfg or _make_cfg()
    return cls(
        age=1,
        ppid=os.getpid(),
        sockets=[],
        app=mock.Mock(),
        timeout=30,
        cfg=cfg,
        log=mock.Mock(),
        **kwargs,
    )


class TestSyncDrainBody:
    """Sync worker drains unread body before closing the socket."""

    def test_finish_body_called_on_normal_close(self):
        worker = _make_worker(sync_mod.SyncWorker)
        client = mock.Mock()
        parser = mock.Mock()

        with mock.patch('gunicorn.workers.sync.http.get_parser', return_value=parser):
            parser.__next__ = mock.Mock(side_effect=StopIteration)
            worker.handle(mock.Mock(), client, ('127.0.0.1', 0))

        client.settimeout.assert_called_with(1)
        parser.finish_body.assert_called_once()

    def test_finish_body_exception_suppressed(self):
        worker = _make_worker(sync_mod.SyncWorker)
        client = mock.Mock()
        parser = mock.Mock()
        parser.finish_body.side_effect = OSError("read failed")

        with mock.patch('gunicorn.workers.sync.http.get_parser', return_value=parser):
            parser.__next__ = mock.Mock(side_effect=StopIteration)
            # Should not raise
            worker.handle(mock.Mock(), client, ('127.0.0.1', 0))

        parser.finish_body.assert_called_once()


class TestGthreadDrainBody:
    """Gthread worker drains unread body before closing the socket."""

    def _make_conn(self):
        conn = mock.Mock()
        conn.initialized = True
        conn.data_ready = False
        conn.is_http2 = False
        conn.client = ('127.0.0.1', 0)
        conn.sock = mock.Mock()
        conn.parser = mock.Mock()
        conn.parser.__next__ = mock.Mock(side_effect=StopIteration)
        return conn

    def test_finish_body_called_on_normal_close(self):
        worker = _make_worker(gthread.ThreadWorker)
        conn = self._make_conn()

        worker.handle(conn)

        conn.sock.settimeout.assert_called_with(1)
        conn.parser.finish_body.assert_called_once()

    def test_finish_body_exception_suppressed(self):
        worker = _make_worker(gthread.ThreadWorker)
        conn = self._make_conn()
        conn.parser.finish_body.side_effect = OSError("read failed")

        # Should not raise
        result = worker.handle(conn)

        assert result is False
        conn.parser.finish_body.assert_called_once()


class TestAsyncDrainBody:
    """Async worker drains unread body before closing the socket."""

    def test_finish_body_called_on_normal_close(self):
        cfg = _make_cfg(keepalive=0)
        worker = _make_worker(base_async.AsyncWorker, cfg=cfg)
        client = mock.Mock()
        parser = mock.Mock()

        with mock.patch('gunicorn.workers.base_async.http.get_parser', return_value=parser):
            parser.__next__ = mock.Mock(side_effect=StopIteration)
            worker.handle(mock.Mock(), client, ('127.0.0.1', 0))

        client.settimeout.assert_called_with(1)
        parser.finish_body.assert_called_once()

    def test_finish_body_exception_suppressed(self):
        cfg = _make_cfg(keepalive=0)
        worker = _make_worker(base_async.AsyncWorker, cfg=cfg)
        client = mock.Mock()
        parser = mock.Mock()
        parser.finish_body.side_effect = OSError("read failed")

        with mock.patch('gunicorn.workers.base_async.http.get_parser', return_value=parser):
            parser.__next__ = mock.Mock(side_effect=StopIteration)
            # Should not raise
            worker.handle(mock.Mock(), client, ('127.0.0.1', 0))

        parser.finish_body.assert_called_once()
