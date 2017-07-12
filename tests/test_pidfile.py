# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import errno
import sys

try:
    import unittest.mock as mock
except ImportError:
    import mock

import gunicorn.pidfile


def builtin(name):
    if sys.version_info >= (3, 0):
        module = 'builtins'
    else:
        module = '__builtin__'

    return '{0}.{1}'.format(module, name)


@mock.patch(builtin('open'), new_callable=mock.mock_open)
def test_validate_no_file(_open):
    pidfile = gunicorn.pidfile.Pidfile('test.pid')
    _open.side_effect = IOError(errno.ENOENT)
    assert pidfile.validate() is None


@mock.patch(builtin('open'), new_callable=mock.mock_open, read_data='1')
@mock.patch('os.kill')
def test_validate_file_pid_exists(kill, _open):
    pidfile = gunicorn.pidfile.Pidfile('test.pid')
    assert pidfile.validate() == 1
    assert kill.called


@mock.patch(builtin('open'), new_callable=mock.mock_open, read_data='a')
def test_validate_file_pid_malformed(_open):
    pidfile = gunicorn.pidfile.Pidfile('test.pid')
    assert pidfile.validate() is None


@mock.patch(builtin('open'), new_callable=mock.mock_open, read_data='1')
@mock.patch('os.kill')
def test_validate_file_pid_exists_kill_exception(kill, _open):
    pidfile = gunicorn.pidfile.Pidfile('test.pid')
    kill.side_effect = OSError(errno.EPERM)
    assert pidfile.validate() == 1


@mock.patch(builtin('open'), new_callable=mock.mock_open, read_data='1')
@mock.patch('os.kill')
def test_validate_file_pid_does_not_exist(kill, _open):
    pidfile = gunicorn.pidfile.Pidfile('test.pid')
    kill.side_effect = OSError(errno.ESRCH)
    assert pidfile.validate() is None
