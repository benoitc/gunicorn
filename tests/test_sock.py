#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import sys
import socket
from unittest import mock

import pytest

from gunicorn import sock


@pytest.fixture(scope='function')
def addr(request, tmp_path):
    if isinstance(request.param, str):
        return str(tmp_path / request.param)
    return request.param


def test_socket_backlog():
    listener = mock.Mock(family=socket.AF_INET6)

    def fake_getsockopt(prot, opt, length):
        assert prot == socket.IPPROTO_TCP
        assert opt == socket.TCP_INFO
        assert length == 104
        return b"\x01\x01\0\0" * (length // 4)
    listener.getsockopt = fake_getsockopt
    bl = sock.get_backlog(listener)
    if sys.platform == "linux":
        assert bl == (1 << 8) + 1
    else:
        assert bl == -1


@mock.patch('socket.socket')
@mock.patch('gunicorn.util.chown')
def test_inherit_socket(chown, socket):
    conf = mock.Mock(address=[], certfile=None, keyfile=None)
    log = mock.Mock()
    listeners = sock.create_sockets(conf, log, fds=[3])
    assert len(listeners) == 1
    listener = listeners[0]
    assert listener == socket.return_value
    socket.assert_called_with(fileno=3)
    listener.listen.assert_not_called()
    chown.assert_not_called()


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


@pytest.mark.parametrize(
    'addr, is_ssl, addr_as_uri',
    [
        ('gunicorn.sock', False, "unix://%s"),
        (('192.0.2.1', 80), False, "http://192.0.2.1:80"),
        (('192.0.2.1', 443), True, "https://192.0.2.1:443"),
        (('[fe80::1]', 443), True, "https://[fe80::1]:443"),
    ],
    indirect=['addr'],
)
@mock.patch('socket.socket')
@mock.patch('gunicorn.util.chown')
def test_get_socket_uri(chown, socket, addr, is_ssl, addr_as_uri):
    conf = mock.Mock(address=[addr], umask=0o22)
    log = mock.Mock()
    listener = sock.create_socket(conf, log, addr)
    assert listener == socket.return_value
    # mock
    listener.getsockname = lambda: addr
    if isinstance(addr, str):
        addr_as_uri = addr_as_uri.replace("%s", addr)
    assert sock.get_uri(listener, is_ssl=is_ssl) == addr_as_uri


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
