#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Resilience: apply a control-plane fault while k6 load runs and assert the
worker recovers and keeps serving. Gated behind GUNICORN_STRESS_HEAVY=1."""

import threading
import time

import pytest

pytestmark = [pytest.mark.docker, pytest.mark.stress_heavy, pytest.mark.integration]

SERVICE = "gunicorn-asgi"
CONFIG = "asgi-nginx-h1"


def _load(stack, results, extra_env):
    results.append(stack.run_k6(CONFIG, "constant", extra_env=extra_env))


def _wait_workers(stack, predicate, timeout=15):
    """Poll the worker count until ``predicate(count)`` holds or time runs out.

    Worker counts settle asynchronously after a signal, and the session stack is
    shared across tests, so poll rather than assert after a fixed sleep.
    """
    deadline = time.time() + timeout
    count = len(stack.worker_pids(SERVICE))
    while time.time() < deadline:
        count = len(stack.worker_pids(SERVICE))
        if predicate(count):
            return count
        time.sleep(0.5)
    return count


def _wait_stable(stack, timeout=20, samples=4, interval=0.5):
    """Return the worker count once it holds steady across ``samples`` reads.

    A prior HUP reload leaves old and new workers briefly co-parented under the
    master, so the raw count is inflated until reaping finishes; wait it out
    before capturing a baseline.
    """
    deadline = time.time() + timeout
    last, streak = None, 0
    while time.time() < deadline:
        count = len(stack.worker_pids(SERVICE))
        streak = streak + 1 if count == last else 1
        last = count
        if streak >= samples:
            return count
        time.sleep(interval)
    return last


def _run_under_load(stack, fault, fail_budget="0.05"):
    """Start a constant-rate load, fire ``fault`` mid-run, return the k6 result."""
    results = []
    env = {"RATE": "40", "DURATION": "20s", "FAIL_BUDGET": fail_budget}
    t = threading.Thread(target=_load, args=(stack, results, env))
    t.start()
    time.sleep(6)
    fault()
    t.join()
    assert results, "load thread produced no result"
    return results[0]


def test_worker_kill_recovers(stack):
    before = stack.worker_pids(SERVICE)
    res = _run_under_load(stack, lambda: stack.kill_one_worker(SERVICE))
    # A direct-connection casualty is allowed; the budget covers it.
    assert res.returncode == 0, res.stdout
    after = _wait_workers(stack, lambda c: c >= len(before))
    assert after >= len(before), f"workers not respawned: {len(before)} -> {after}"


def test_hup_reload_under_load(stack):
    res = _run_under_load(stack, lambda: stack.signal_master(SERVICE, "HUP"))
    assert res.returncode == 0, res.stdout
    time.sleep(3)
    assert stack.worker_pids(SERVICE), "no workers after HUP reload"


def test_ttin_ttou_scaling_under_load(stack):
    base = _wait_stable(stack)

    res = _run_under_load(stack, lambda: stack.signal_master(SERVICE, "TTIN"))
    assert res.returncode == 0, res.stdout
    grown = _wait_workers(stack, lambda c: c >= base + 1)
    assert grown >= base + 1, f"TTIN did not add a worker: {base} -> {grown}"

    stack.signal_master(SERVICE, "TTOU")
    restored = _wait_workers(stack, lambda c: c <= grown - 1)
    assert restored <= grown - 1, f"TTOU did not remove a worker: {grown} -> {restored}"


def test_no_tracebacks_after_faults(stack):
    assert stack.tracebacks(SERVICE) == 0, stack.logs(SERVICE)[-4000:]
