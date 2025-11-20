#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import io
from unittest import mock

import pytest

from gunicorn import config
from gunicorn.workers.workertmp import WorkerTmp


@pytest.fixture
def cfg(tmp_path):
    c = config.Config()
    c.set('worker_tmp_dir', str(tmp_path))
    return c


@mock.patch('time.monotonic')
def test_creation(mock_monotonic, cfg):
    mock_monotonic.side_effect = [100.0]
    wt = WorkerTmp(cfg)

    mock_monotonic.assert_called_once()
    assert isinstance(wt._tmp, io.IOBase)
    assert wt.last_update() == 100.0


@mock.patch('time.monotonic')
def test_creation_with_delay(mock_monotonic, cfg):
    mock_monotonic.side_effect = [100.0]
    cfg.set('timeout_delay', 50)
    wt = WorkerTmp(cfg)

    mock_monotonic.assert_called_once()
    assert isinstance(wt._tmp, io.IOBase)
    assert wt.last_update() == 150.0


@mock.patch('time.monotonic')
def test_notify(mock_monotonic, cfg):
    mock_monotonic.side_effect = [100.0, 200.0]
    wt = WorkerTmp(cfg)
    wt.notify()

    mock_monotonic.assert_has_calls([(), ()])
    assert wt.last_update() == 200.0


@mock.patch('time.monotonic')
def test_notify_before_delay(mock_monotonic, cfg):
    mock_monotonic.side_effect = [100.0, 200.0]
    cfg.set('timeout_delay', 300)

    wt = WorkerTmp(cfg)
    assert wt.last_update() == 400.0
    wt.notify()

    mock_monotonic.assert_has_calls([(), ()])
    assert wt.last_update() == 200.0


@mock.patch('time.monotonic')
def test_notify_after_delay(mock_monotonic, cfg):
    mock_monotonic.side_effect = [100.0, 500.0]
    cfg.set('timeout_delay', 300)

    wt = WorkerTmp(cfg)
    assert wt.last_update() == 400.0
    wt.notify()

    mock_monotonic.assert_has_calls([(), ()])
    assert wt.last_update() == 500.0
