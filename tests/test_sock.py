try:
    import unittest.mock as mock
except ImportError:
    import mock

from gunicorn import sock


@mock.patch('os.close')
@mock.patch('os.getpid')
@mock.patch('os.unlink')
@mock.patch('socket.fromfd')
def test_unix_socket_close_unlink(fromfd, unlink, getpid, close):
    fd = 42
    gsock = sock.UnixSocket('test.sock', mock.Mock(), mock.Mock(), fd=fd)
    gsock.close()
    unlink.assert_called_with("test.sock")
    close.assert_called_with(fd)
