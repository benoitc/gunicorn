import fcntl

try:
    import unittest.mock as mock
except ImportError:
    import mock

from gunicorn import sock


@mock.patch('fcntl.lockf')
@mock.patch('socket.fromfd')
def test_unix_socket_init_lock(fromfd, lockf):
    s = fromfd.return_value
    sock.UnixSocket('test.sock', mock.Mock(), mock.Mock(), mock.Mock())
    lockf.assert_called_with(s, fcntl.LOCK_SH | fcntl.LOCK_NB)


@mock.patch('fcntl.lockf')
@mock.patch('os.getpid')
@mock.patch('os.unlink')
@mock.patch('socket.fromfd')
def test_unix_socket_close_delete_if_exlock(fromfd, unlink, getpid, lockf):
    s = fromfd.return_value
    gsock = sock.UnixSocket('test.sock', mock.Mock(), mock.Mock(), mock.Mock())
    lockf.reset_mock()
    gsock.close()
    lockf.assert_called_with(s, fcntl.LOCK_EX | fcntl.LOCK_NB)
    unlink.assert_called_with('test.sock')


@mock.patch('fcntl.lockf')
@mock.patch('os.getpid')
@mock.patch('os.unlink')
@mock.patch('socket.fromfd')
def test_unix_socket_close_keep_if_no_exlock(fromfd, unlink, getpid, lockf):
    s = fromfd.return_value
    gsock = sock.UnixSocket('test.sock', mock.Mock(), mock.Mock(), mock.Mock())
    lockf.reset_mock()
    lockf.side_effect = IOError('locked')
    gsock.close()
    lockf.assert_called_with(s, fcntl.LOCK_EX | fcntl.LOCK_NB)
    unlink.assert_not_called()


@mock.patch('fcntl.lockf')
@mock.patch('os.getpid')
@mock.patch('socket.fromfd')
def test_unix_socket_not_deleted_by_worker(fromfd, getpid, lockf):
    fd = mock.Mock()
    gsock = sock.UnixSocket('name', mock.Mock(), mock.Mock(), fd)
    lockf.reset_mock()
    getpid.reset_mock()
    getpid.return_value = mock.Mock()  # fake a pid change
    gsock.close()
    lockf.assert_not_called()
