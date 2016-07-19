# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from contextlib import contextmanager
import os

try:
    import unittest.mock as mock
except ImportError:
    import mock

import pytest

from gunicorn import systemd


@contextmanager
def check_environ(unset=True):
    """
    A context manager that asserts post-conditions of ``listen_fds`` at exit.

    This helper is used to ease checking of the test post-conditions for the
    systemd socket activation tests that parametrize the call argument.
    """

    with mock.patch.dict(os.environ):
        old_fds = os.environ.get('LISTEN_FDS', None)
        old_pid = os.environ.get('LISTEN_PID', None)

        yield

        if unset:
            assert 'LISTEN_FDS' not in os.environ, \
                "LISTEN_FDS should have been unset"
            assert 'LISTEN_PID' not in os.environ, \
                "LISTEN_PID should have been unset"
        else:
            new_fds = os.environ.get('LISTEN_FDS', None)
            new_pid = os.environ.get('LISTEN_PID', None)
            assert new_fds == old_fds, \
                "LISTEN_FDS should not have been changed"
            assert new_pid == old_pid, \
                "LISTEN_PID should not have been changed"


@pytest.mark.parametrize("unset", [True, False])
def test_listen_fds_ignores_wrong_pid(unset):
    with mock.patch.dict(os.environ):
        os.environ['LISTEN_FDS'] = str(5)
        os.environ['LISTEN_PID'] = str(1)
        with check_environ(False):  # early exit — never changes the environment
            assert systemd.listen_fds(unset) == 0, \
                "should ignore listen fds not intended for this pid"


@pytest.mark.parametrize("unset", [True, False])
def test_listen_fds_returns_count(unset):
    with mock.patch.dict(os.environ):
        os.environ['LISTEN_FDS'] = str(5)
        os.environ['LISTEN_PID'] = str(os.getpid())
        with check_environ(unset):
            assert systemd.listen_fds(unset) == 5, \
                "should return the correct count of fds"
