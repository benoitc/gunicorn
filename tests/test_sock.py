# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

try:
    import unittest.mock as mock
except ImportError:
    import mock

import pytest

from socket import SOCK_STREAM
from socket import AF_UNIX
from socket import AF_INET
from socket import AF_INET6

from gunicorn import sock


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
    listener = mock.Mock()
    listener.getsockname.return_value = '/var/run/test.sock'
    listener.family = SOCK_STREAM
    sock.close_sockets([listener])
    listener.close.assert_called_with()
    unlink.assert_called_once_with('/var/run/test.sock')


@mock.patch('os.unlink')
def test_unix_socket_close_without_unlink(unlink):
    listener = mock.Mock()
    listener.getsockname.return_value = '/var/run/test.sock'
    listener.family = SOCK_STREAM
    sock.close_sockets([listener], False)
    listener.close.assert_called_with()
    assert not unlink.called, 'unlink should not have been called'

@pytest.mark.parametrize('test_input, expected', [
    (AF_UNIX, sock.UnixSocket),
    (AF_INET, sock.TCPSocket),
    (AF_INET6, sock.TCP6Socket)])
def test__sock_type(test_input, expected):
     assert sock._sock_type(test_input) is expected

def test__sock_type2():
    with pytest.raises(TypeError) as err:
        sock._sock_type(17)
    assert 'Unable to create socket family:' in str(err)
