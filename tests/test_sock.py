#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import errno
import os
import socket
from unittest import mock

import pytest

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


@pytest.mark.parametrize('source', ['inherited', 'also_configured', 'constructor'])
def test_listener_adopts_received_fd(tmp_path, source):
    path = str(tmp_path / 'listener.sock')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as original:
        original.bind(path)
        original.listen()
        original.set_inheritable(True)
        fd = original.detach()

    conf = mock.Mock(address=[fd] if source == 'also_configured' else [], certfile=None,
                     keyfile=None, reuse_port=False)
    if source == 'constructor':
        listeners = [sock.UnixSocket(path, conf, mock.Mock(), fd=fd)]
    else:
        listeners = sock.create_sockets(conf, mock.Mock(), fds=[fd])
    try:
        assert len(listeners) == 1
        listener = listeners[0]
        assert isinstance(listener, sock.UnixSocket)
        assert listener.fileno() == fd
        assert not listener.get_inheritable()
        assert listener.getsockname() == path
        assert os.path.exists(path)
    finally:
        sock.close_sockets(listeners, unlink=False)

    with pytest.raises(OSError) as exc:
        os.fstat(fd)
    assert exc.value.errno == errno.EBADF


def test_create_sockets_closes_adopted_fds_on_error():
    with socket.socket() as first, socket.socket(type=socket.SOCK_DGRAM) as second:
        first.bind(('127.0.0.1', 0))
        fds = [first.detach(), second.detach()]
    conf = mock.Mock(address=[], certfile=None, keyfile=None, reuse_port=False, backlog=1)
    with pytest.raises(OSError) as setup_error:
        sock.create_sockets(conf, mock.Mock(), fds=fds)
    assert setup_error.value.errno != errno.EBADF
    for fd in fds:
        with pytest.raises(OSError) as exc:
            os.fstat(fd)
        assert exc.value.errno == errno.EBADF


def test_create_sockets_does_not_relisten_inherited_socket():
    conf = mock.Mock(address=[], certfile=None, keyfile=None,
                     reuse_port=False, backlog=123)
    log = mock.Mock()
    inherited_socket = mock.Mock()
    inherited_socket.getsockname.return_value = ('127.0.0.1', 8000)
    inherited_socket.getsockopt.return_value = 1

    with mock.patch.object(sock.socket, 'socket', return_value=inherited_socket):
        listeners = sock.create_sockets(conf, log, fds=[3])

    assert len(listeners) == 1
    inherited_socket.listen.assert_not_called()


def test_create_sockets_listens_on_bind_fd():
    conf = mock.Mock(address=[3], certfile=None, keyfile=None,
                     reuse_port=False, backlog=123)
    log = mock.Mock()
    bound_socket = mock.Mock()
    bound_socket.getsockname.return_value = ('127.0.0.1', 8000)
    bound_socket.getsockopt.return_value = 0

    with mock.patch.object(sock.socket, 'socket', return_value=bound_socket):
        listeners = sock.create_sockets(conf, log)

    assert len(listeners) == 1
    bound_socket.listen.assert_called_once_with(123)


def test_create_sockets_listens_when_acceptconn_unsupported():
    """If the platform cannot report SO_ACCEPTCONN, listen() as before."""
    conf = mock.Mock(address=[3], certfile=None, keyfile=None,
                     reuse_port=False, backlog=123)
    log = mock.Mock()
    bound_socket = mock.Mock()
    bound_socket.getsockname.return_value = ('127.0.0.1', 8000)
    bound_socket.getsockopt.side_effect = OSError("not supported")

    with mock.patch.object(sock.socket, 'socket', return_value=bound_socket):
        listeners = sock.create_sockets(conf, log)

    assert len(listeners) == 1
    bound_socket.listen.assert_called_once_with(123)


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
