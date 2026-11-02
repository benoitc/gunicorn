#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

from contextlib import contextmanager
import os
from unittest import mock

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


def test_watchdog_disabled_without_usec():
    with mock.patch.dict(os.environ, clear=True):
        assert systemd.watchdog_enabled() is False


def test_watchdog_disabled_for_zero_usec():
    with mock.patch.dict(os.environ, {"WATCHDOG_USEC": "0"}):
        assert systemd.watchdog_enabled() is False


def test_watchdog_disabled_for_other_pid():
    with mock.patch.dict(os.environ, {
        "WATCHDOG_USEC": "10000000",
        "WATCHDOG_PID": "1",
    }):
        assert systemd.watchdog_enabled() is False


def test_watchdog_enabled_for_this_pid():
    with mock.patch.dict(os.environ, {
        "WATCHDOG_USEC": "10000000",
        "WATCHDOG_PID": str(os.getpid()),
    }):
        assert systemd.watchdog_enabled() is True


def test_watchdog_enabled_without_pid():
    with mock.patch.dict(os.environ, {"WATCHDOG_USEC": "2000000"}):
        assert systemd.watchdog_enabled() is True


def test_ping_watchdog_sends_when_enabled():
    logger = mock.Mock()
    with mock.patch.dict(os.environ, {"WATCHDOG_USEC": "5000000"}):
        with mock.patch.object(systemd, "sd_notify") as notify:
            systemd.ping_watchdog(logger)
            notify.assert_called_once_with("WATCHDOG=1", logger)


def test_ping_watchdog_skips_when_disabled():
    logger = mock.Mock()
    with mock.patch.dict(os.environ, clear=True):
        with mock.patch.object(systemd, "sd_notify") as notify:
            systemd.ping_watchdog(logger)
            notify.assert_not_called()
