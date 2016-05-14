try:
    import unittest.mock as mock
except ImportError:
    import mock

from gunicorn import sock


@mock.patch('os.getpid')
@mock.patch('os.unlink')
@mock.patch('socket.fromfd')
def test_unix_socket_close_delete_if_exlock(fromfd, unlink, getpid):
    gsock = sock.UnixSocket('test.sock', mock.Mock(), mock.Mock(), mock.Mock())
    gsock.close(False)
    unlink.assert_called_with('test.sock')


@mock.patch('os.getpid')
@mock.patch('os.unlink')
@mock.patch('socket.fromfd')
def test_unix_socket_close_keep_if_no_exlock(fromfd, unlink, getpid):
    gsock = sock.UnixSocket('test.sock', mock.Mock(), mock.Mock(), mock.Mock())
    gsock.close(True)
    unlink.assert_not_called()


@mock.patch('os.getpid')
@mock.patch('os.unlink')
@mock.patch('socket.fromfd')
def test_unix_socket_not_deleted_by_worker(fromfd, unlink, getpid):
    fd = mock.Mock()
    gsock = sock.UnixSocket('test.sock', mock.Mock(), mock.Mock(), fd)
    getpid.reset_mock()
    getpid.return_value = "fake"  # fake a pid change
    gsock.close(False)
    unlink.assert_not_called()
