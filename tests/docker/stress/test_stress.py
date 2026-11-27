#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Smoke matrix: drive each representative config under a short k6 load and
assert the server stayed correct (thresholds passed, no worker traceback)."""

import pytest

from conftest import CONFIGS

pytestmark = [pytest.mark.docker, pytest.mark.stress, pytest.mark.integration]


def _rate(summary, metric):
    try:
        return summary["metrics"][metric]["values"]["rate"]
    except KeyError:
        return None


@pytest.mark.parametrize("config", list(CONFIGS))
def test_smoke(stack, config):
    res = stack.run_k6(config, "smoke")
    assert res.returncode == 0, f"k6 thresholds failed:\n{res.stdout}"

    checks = _rate(res.summary, "checks")
    assert checks == 1.0, f"checks rate {checks}\n{res.stdout}"

    if CONFIGS[config]["kind"] == "http":
        failed = _rate(res.summary, "http_req_failed")
        assert failed == 0.0, f"request failure rate {failed}\n{res.stdout}"

    service = CONFIGS[config]["service"]
    assert stack.tracebacks(service) == 0, stack.logs(service)[-4000:]
