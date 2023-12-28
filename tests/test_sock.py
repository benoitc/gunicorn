# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import socket
from unittest import mock

import pytest

from gunicorn import sock

@pytest.fixture(scope='function')
def addr(request, tmp_path):
    if isinstance(request.param, str):
        return str(tmp_path / request.param)
    return request.param


@pytest.mark.parametrize(
    'addr, family',
    [
        ('gunicorn.sock', socket.AF_UNIX),
        (('0.0.0.0', 0), socket.AF_INET),
        (('::', 0), socket.AF_INET6),
    ],
    indirect=['addr'],
)
@mock.patch('socket.socket')
@mock.patch('gunicorn.util.chown')
def test_create_socket(chown, socket, addr, family):
    conf = mock.Mock(address=[addr], umask=0o22)
    log = mock.Mock()
    listener = sock.create_socket(conf, log, addr)
    assert listener == socket.return_value
    socket.assert_called_with(family)
    listener.bind.assert_called_with(addr)
    listener.listen.assert_called_with(conf.backlog)
    if family is socket.AF_UNIX:
        chown.assert_called_with(addr, conf.uid, conf.gid)


def test_socket_close():
    listener1 = mock.Mock()
    listener1.getsockname.return_value = ('127.0.0.1', '80')
    listener2 = mock.Mock()
    listener2.getsockname.return_value = ('192.168.2.5', '80')
    sock.close_sockets([listener1, listener2])
    listener1.close.assert_called_with()
    listener2.close.assert_called_with()


@mock.patch('os.unlink')
def test_unix_socket_close_unlink(unlink):
    listener = mock.Mock(family=socket.AF_UNIX)
    listener.getsockname.return_value = '/var/run/test.sock'
    sock.close_sockets([listener])
    listener.close.assert_called_with()
    unlink.assert_called_once_with('/var/run/test.sock')


@mock.patch('os.unlink')
def test_unix_socket_close_without_unlink(unlink):
    listener = mock.Mock(family=socket.AF_UNIX)
    listener.getsockname.return_value = '/var/run/test.sock'
    sock.close_sockets([listener], False)
    listener.close.assert_called_with()
    assert not unlink.called, 'unlink should not have been called'
