#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import errno
from unittest import mock

from gunicorn import sock


@mock.patch('os.stat')
def test_create_sockets_unix_bytes(stat):
    conf = mock.Mock(address=[b'127.0.0.1:8000'])
    log = mock.Mock()
    with mock.patch.object(sock.UnixSocket, '__init__', lambda *args: None):
        listeners = sock.create_sockets(conf, log)
        assert len(listeners) == 1
        print(type(listeners[0]))
        assert isinstance(listeners[0], sock.UnixSocket)


@mock.patch('os.stat')
def test_create_sockets_unix_strings(stat):
    conf = mock.Mock(address=['127.0.0.1:8000'])
    log = mock.Mock()
    with mock.patch.object(sock.UnixSocket, '__init__', lambda *args: None):
        listeners = sock.create_sockets(conf, log)
        assert len(listeners) == 1
        assert isinstance(listeners[0], sock.UnixSocket)


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
    sock.close_sockets([listener])
    listener.close.assert_called_with()
    unlink.assert_called_once_with('/var/run/test.sock')


@mock.patch('os.unlink')
def test_unix_socket_close_without_unlink(unlink):
    listener = mock.Mock()
    listener.getsockname.return_value = '/var/run/test.sock'
    sock.close_sockets([listener], False)
    listener.close.assert_called_with()
    assert not unlink.called, 'unlink should not have been called'


@mock.patch('os.stat')
def test_unix_socket_abstract_namespace_skips_stat(stat):
    conf = mock.Mock()
    log = mock.Mock()
    with mock.patch.object(sock.BaseSocket, '__init__', lambda *a, **kw: None):
        sock.UnixSocket('\0my-abstract-socket', conf, log)
    assert not stat.called, 'os.stat should be skipped for an abstract namespace address'


@mock.patch('os.stat')
def test_unix_socket_filesystem_path_still_checks_stat(stat):
    stat.side_effect = OSError(errno.ENOENT, 'No such file or directory')
    conf = mock.Mock()
    log = mock.Mock()
    with mock.patch.object(sock.BaseSocket, '__init__', lambda *a, **kw: None):
        sock.UnixSocket('/var/run/test.sock', conf, log)
    stat.assert_called_once_with('/var/run/test.sock')


@mock.patch.object(sock.util, 'chown')
def test_unix_socket_bind_abstract_namespace_skips_chown(chown):
    listener = mock.Mock()
    unix_sock = sock.UnixSocket.__new__(sock.UnixSocket)
    unix_sock.conf = mock.Mock(umask=0)
    unix_sock.cfg_addr = '\0my-abstract-socket'
    unix_sock.bind(listener)
    listener.bind.assert_called_once_with('\0my-abstract-socket')
    assert not chown.called, 'chown should be skipped for an abstract namespace address'
