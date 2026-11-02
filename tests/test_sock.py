#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import errno
import socket
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


def test_create_sockets_from_fd_closes_inspection_socket():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', 0))
    srv.listen(1)
    fd = srv.fileno()
    conf = mock.Mock(
        address=[],
        certfile=None,
        keyfile=None,
        reuse_port=False,
        backlog=8,
        is_ssl=False,
    )
    log = mock.Mock()
    created = []
    real_fromfd = sock.socket.fromfd

    def tracking_fromfd(*args, **kwargs):
        dup = real_fromfd(*args, **kwargs)
        created.append(dup)
        return dup

    listeners = []
    try:
        with mock.patch.object(sock.socket, 'fromfd', tracking_fromfd):
            listeners = sock.create_sockets(conf, log, fds=[fd])
        assert len(listeners) == 1
        assert len(created) >= 2

        def socket_is_closed(dup):
            if getattr(dup, '_closed', False):
                return True
            try:
                return dup.fileno() < 0
            except OSError:
                return True

        assert socket_is_closed(created[0])
        assert listeners[0].sock.fileno() >= 0
    finally:
        for listener in listeners:
            listener.close()
        try:
            srv.close()
        except OSError:
            pass


@mock.patch.object(sock.util, 'chown')
def test_unix_socket_bind_abstract_namespace_skips_chown(chown):
    listener = mock.Mock()
    unix_sock = sock.UnixSocket.__new__(sock.UnixSocket)
    unix_sock.conf = mock.Mock(umask=0)
    unix_sock.cfg_addr = '\0my-abstract-socket'
    unix_sock.bind(listener)
    listener.bind.assert_called_once_with('\0my-abstract-socket')
    assert not chown.called, 'chown should be skipped for an abstract namespace address'
