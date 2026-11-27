#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Network faults via Toxiproxy in front of gunicorn-asgi, with k6 driving load
through the toxic proxy. Gated behind GUNICORN_STRESS_HEAVY=1."""

import pytest

from conftest import add_toxic, toxiproxy_reset

pytestmark = [pytest.mark.docker, pytest.mark.stress_heavy, pytest.mark.integration]

# k6 reaches gunicorn-asgi through the toxiproxy container inside the network.
TOXIC_TARGET_ENV = {"TARGET": "http://toxiproxy:8475"}


def _run(faults_stack, env):
    # Reuse the asgi-direct config's checks but point k6 at the toxic proxy.
    return faults_stack.run_k6("asgi-direct-h1", "constant",
                               extra_env={**TOXIC_TARGET_ENV, "RATE": "30",
                                          "DURATION": "15s", **env})


def test_latency_toxic(faults_stack):
    toxiproxy_reset()
    add_toxic("latency", "latency", {"latency": 200, "jitter": 100})
    res = _run(faults_stack, {"FAIL_BUDGET": "0.02", "MAX_P95": "60000", "MAX_P99": "60000"})
    toxiproxy_reset()
    assert res.returncode == 0, res.stdout


def test_bandwidth_toxic(faults_stack):
    toxiproxy_reset()
    add_toxic("bandwidth", "bandwidth", {"rate": 512})  # KB/s
    res = _run(faults_stack, {"FAIL_BUDGET": "0.05", "MAX_P95": "60000", "MAX_P99": "60000"})
    toxiproxy_reset()
    assert res.returncode == 0, res.stdout


def test_reset_peer_toxic_is_survived(faults_stack):
    toxiproxy_reset()
    # Reset a fraction of connections; the worker must not crash or leak.
    add_toxic("reset", "reset_peer", {"timeout": 200}, toxicity=0.3)
    res = _run(faults_stack, {"FAIL_BUDGET": "0.6"})  # transport errors expected
    toxiproxy_reset()
    # We assert survival, not a clean run: the worker is still serving after.
    assert faults_stack.tracebacks("gunicorn-asgi") == 0
    ok = faults_stack.run_k6("asgi-direct-h1", "smoke")
    assert ok.returncode == 0, ok.stdout
