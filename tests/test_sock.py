try:
    import unittest.mock as mock
except ImportError:
    import mock

from gunicorn import sock


@mock.patch('os.getpid')
@mock.patch('os.unlink')
@mock.patch('socket.fromfd')
def test_unix_socket_close_unlink(fromfd, unlink, getpid):
    gsock = sock.UnixSocket('test.sock', mock.Mock(), mock.Mock(), mock.Mock())
    gsock.close()
    unlink.assert_called_with("test.sock")
