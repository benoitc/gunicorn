#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for the ginterpreter worker."""

import os
from unittest import mock

import pytest

from gunicorn.config import Config
from gunicorn.workers import ginterpreter


def _create_worker(cfg=None):
    """Create a worker instance for testing."""
    if cfg is None:
        cfg = Config()
    cfg.set('workers', 1)
    cfg.set('threads', 4)

    mock_app = mock.Mock()
    mock_app.app_uri = 'myapp:application'
    mock_app.cfg = mock.Mock()
    mock_app.cfg.wsgi_app = None

    return ginterpreter.InterpreterWorker(
        age=1,
        ppid=os.getpid(),
        sockets=[],
        app=mock_app,
        timeout=30,
        cfg=cfg,
        log=mock.Mock(),
    )


class TestInterpreterWorker:

    def test_extract_config(self):
        worker = _create_worker()
        cfg_dict = worker._extract_config()
        assert isinstance(cfg_dict, dict)
        assert 'limit_request_line' in cfg_dict
        assert 'timeout' in cfg_dict
        for value in cfg_dict.values():
            assert isinstance(value, (int, bool, str, list, dict, type(None)))

    def test_handle_quit(self):
        worker = _create_worker()
        worker.executor = mock.Mock()
        with pytest.raises(SystemExit):
            worker.handle_quit(None, None)
        worker.executor.shutdown.assert_called_once_with(wait=False)


class TestAccept:

    def test_submit_to_executor(self):
        worker = _create_worker()
        worker.executor = mock.Mock()

        mock_client = mock.Mock()
        mock_client.fileno.return_value = 7
        mock_client.family = 2
        mock_listener = mock.Mock()
        mock_listener.accept.return_value = (mock_client, ('127.0.0.1', 8000))
        mock_listener.getsockname.return_value = ('0.0.0.0', 9000)

        worker.accept(mock_listener)

        worker.executor.submit.assert_called_once_with(
            ginterpreter._handle_request_in_interpreter,
            7, ('127.0.0.1', 8000), ('0.0.0.0', 9000), 2,
        )
        mock_client.detach.assert_called_once()