#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for the ginterpreter worker."""

import os
import ssl
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

    def test_handle_quit(self):
        worker = _create_worker()
        worker.executor = mock.Mock()
        with pytest.raises(SystemExit):
            worker.handle_quit(None, None)
        worker.executor.shutdown.assert_called_once_with(wait=False)


class TestHandleRequest:

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


    @mock.patch('gunicorn.http.wsgi.create')
    @mock.patch('gunicorn.http.parser.RequestParser')
    @mock.patch('socket.socket')
    def test_handle_request(self, mock_socket_cls, mock_parser_cls, mock_create):
        mock_sock = mock.Mock()
        mock_socket_cls.return_value = mock_sock

        mock_req = mock.Mock()
        mock_parser_cls.return_value = iter([mock_req])

        mock_resp = mock.Mock()
        mock_environ = {'wsgi.multithread': False, 'wsgi.multiprocess': False}
        mock_create.return_value = (mock_resp, mock_environ)

        mock_wsgi_app = mock.Mock(return_value=[b'response'])

        cfg = ginterpreter._config_from_dict({
            'timeout': 30,
            'forwarded_allow_ips': [],
            'proxy_allow_ips': [],
        })
        ginterpreter._interpreter_state = ginterpreter.InterpreterState(
            cfg=cfg,
            ssl_context=None,
            wsgi_app=mock_wsgi_app,
            log=mock.Mock(),
        )

        ginterpreter._handle_request_in_interpreter(
            7, ('127.0.0.1', 8000), ('0.0.0.0', 9000), 2
        )

        mock_socket_cls.assert_called_once_with(2, mock.ANY, fileno=7)
        mock_sock.settimeout.assert_called_once_with(30)
        mock_wsgi_app.assert_called_once()


class TestSSL:

    @mock.patch('socket.socket')
    def test_handle_request_wraps_socket_with_ssl(self, mock_socket_cls):
        mock_sock = mock.Mock()
        mock_socket_cls.return_value = mock_sock

        mock_ssl_ctx = mock.Mock()
        mock_wrapped = mock.Mock()
        mock_ssl_ctx.wrap_socket.return_value = mock_wrapped
        mock_wrapped.settimeout = mock.Mock()

        cfg = ginterpreter._config_from_dict({
            'suppress_ragged_eofs': True,
            'do_handshake_on_connect': True,
            'timeout': 30,
            'forwarded_allow_ips': [],
            'proxy_allow_ips': [],
        })
        ginterpreter._interpreter_state = ginterpreter.InterpreterState(
            cfg=cfg,
            ssl_context=mock_ssl_ctx,
            wsgi_app=mock.Mock(),
            log=mock.Mock(),
        )

        with mock.patch('gunicorn.http.parser.RequestParser') as mock_parser:
            mock_parser.return_value = iter([])
            ginterpreter._handle_request_in_interpreter(
                7, ('127.0.0.1', 8000), ('0.0.0.0', 9000), 2
            )

        mock_ssl_ctx.wrap_socket.assert_called_once_with(
            mock_sock,
            server_side=True,
            suppress_ragged_eofs=True,
            do_handshake_on_connect=True,
        )
