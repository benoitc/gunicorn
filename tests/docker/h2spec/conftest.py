# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Fixtures for the h2spec conformance suite."""

import subprocess
from pathlib import Path

import pytest

DOCKER_DIR = Path(__file__).parent
CERTS_DIR = DOCKER_DIR / "certs"
COMPOSE_FILE = DOCKER_DIR / "docker-compose.yml"

WORKERS = ("gthread", "gevent", "asgi")
PORTS = {"gthread": 8451, "gevent": 8452, "asgi": 8453}


def _compose(*args, **kwargs):
    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), *args],
        cwd=DOCKER_DIR, **kwargs)


def _generate_cert():
    CERTS_DIR.mkdir(exist_ok=True)
    crt, key = CERTS_DIR / "server.crt", CERTS_DIR / "server.key"
    if crt.exists() and key.exists():
        check = subprocess.run(
            ["openssl", "x509", "-checkend", "86400", "-noout", "-in", str(crt)],
            capture_output=True)
        if check.returncode == 0:
            return
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(key), "-out", str(crt), "-days", "1",
        "-subj", "/CN=localhost",
    ], check=True, capture_output=True)


def _wait_healthy(timeout=180):
    import time
    deadline = time.monotonic() + timeout
    services = [f"gunicorn-{w}" for w in WORKERS]
    while time.monotonic() < deadline:
        result = _compose("ps", "--format", "{{.Service}} {{.Health}}",
                          capture_output=True, text=True)
        healthy = {line.split()[0] for line in result.stdout.splitlines()
                   if line.endswith("healthy")}
        if all(s in healthy for s in services):
            return True
        time.sleep(2)
    return False


@pytest.fixture(scope="session")
def h2spec_services():
    """Bring up one gunicorn per worker class; tear everything down after."""
    for cmd in (["docker", "info"], ["docker", "compose", "version"]):
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            pytest.skip("Docker is not available")
    _generate_cert()
    try:
        _compose("build", check=True)
        _compose("pull", "h2spec", check=True, capture_output=True)
        _compose("up", "-d", check=True)
        if not _wait_healthy():
            logs = _compose("logs", capture_output=True, text=True)
            pytest.fail(f"gunicorn services did not become healthy:\n{logs.stdout}\n{logs.stderr}")
        yield
    finally:
        _compose("down", "--remove-orphans", "-v", capture_output=True)


def run_h2spec(worker):
    """Run h2spec against one worker inside the compose network.

    Returns (passed, failed, [failing case descriptions], full output).
    """
    result = _compose(
        "run", "--rm", "--no-deps", "h2spec",
        "-h", f"gunicorn-{worker}", "-p", "8443", "-t", "-k", "-o", "10",
        capture_output=True, text=True)
    out = result.stdout + result.stderr
    passed = failed = None
    failures = []
    for line in out.splitlines():
        stripped = line.strip()
        if stripped.startswith("×"):
            failures.append(stripped[1:].strip())
        if " tests, " in stripped and " passed" in stripped:
            parts = stripped.replace(",", "").split()
            passed = int(parts[parts.index("passed") - 1])
            failed = int(parts[parts.index("failed") - 1])
    if passed is None:
        pytest.fail(f"h2spec produced no summary for {worker}:\n{out}")
    return passed, failed, sorted(set(failures)), out
