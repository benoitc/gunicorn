#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Fixtures and helpers for the k6 stress and resilience suite.

The suite brings up one gunicorn image serving several worker/topology targets
behind nginx, drives load with k6 (run as a pinned container inside the compose
network), and asserts correctness through k6 thresholds. Resilience and
Toxiproxy fault tests are gated behind ``@pytest.mark.stress_heavy`` and the
``GUNICORN_STRESS_HEAVY`` environment flag.
"""

import json
import os
import shutil
import ssl
import subprocess
import time
from collections import namedtuple
from pathlib import Path

import pytest

requests = pytest.importorskip("requests")

STRESS_DIR = Path(__file__).parent
COMPOSE_FILE = STRESS_DIR / "docker-compose.yml"
CERTS_DIR = STRESS_DIR / "certs"
RESULTS_DIR = STRESS_DIR / "_results"
PROJECT = "gunicorn_stress"
HEAVY = os.environ.get("GUNICORN_STRESS_HEAVY") == "1"

# config id -> how k6 (inside the network) and pytest (from the host) reach it.
CONFIGS = {
    "sync-direct-h1": dict(
        target="http://gunicorn-sync:8000", host="http://127.0.0.1:8460",
        proto="HTTP/1.1", service="gunicorn-sync", kind="http"),
    "gthread-nginx-h1": dict(
        target="http://nginx:8461", host="http://127.0.0.1:8461",
        proto="HTTP/1.1", service="gunicorn-gthread", kind="http"),
    "asgi-direct-h1": dict(
        target="http://gunicorn-asgi:8000", host="http://127.0.0.1:8462",
        proto="HTTP/1.1", service="gunicorn-asgi", kind="http"),
    "asgi-nginx-h1": dict(
        target="http://nginx:8463", host="http://127.0.0.1:8463",
        proto="HTTP/1.1", service="gunicorn-asgi", kind="http"),
    "asgi-ws-nginx": dict(
        target="ws://nginx:8463", host="http://127.0.0.1:8463",
        proto="", service="gunicorn-asgi", kind="ws"),
    "h2-direct-tls": dict(
        target="https://gunicorn-h2:8443", host="https://127.0.0.1:8465",
        proto="HTTP/2.0", service="gunicorn-h2", kind="http"),
}

K6Result = namedtuple("K6Result", "returncode summary stdout")


def _docker_available():
    if not shutil.which("docker"):
        return False
    try:
        subprocess.run(["docker", "info"], check=True, capture_output=True, timeout=20)
        subprocess.run(["docker", "compose", "version"], check=True, capture_output=True, timeout=20)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False


def _generate_cert():
    CERTS_DIR.mkdir(exist_ok=True)
    crt, key = CERTS_DIR / "server.crt", CERTS_DIR / "server.key"
    if crt.exists() and key.exists() and (time.time() - crt.stat().st_mtime) < 86400:
        return
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048",
        "-keyout", str(key), "-out", str(crt), "-days", "1", "-nodes",
        "-subj", "/CN=localhost/O=Gunicorn Stress/C=US",
        "-addext", "subjectAltName=DNS:localhost,DNS:gunicorn-h2,DNS:nginx,IP:127.0.0.1",
    ], check=True, capture_output=True)
    os.chmod(crt, 0o644)
    os.chmod(key, 0o644)


def _compose(*args, env=None, **kw):
    full = ["docker", "compose", "-p", PROJECT, "-f", str(COMPOSE_FILE), *args]
    merged = {**os.environ, **(env or {})}
    return subprocess.run(full, cwd=STRESS_DIR, env=merged, **kw)


def _wait_ready(timeout=240):
    session = requests.Session()
    session.verify = False
    tcp = [("127.0.0.1", 8460), ("127.0.0.1", 8462), ("127.0.0.1", 8465)]
    http = ["http://127.0.0.1:8461/small", "http://127.0.0.1:8463/small",
            "http://127.0.0.1:8466/small", "https://127.0.0.1:8464/small"]
    import socket
    deadline = time.time() + timeout
    import warnings
    warnings.filterwarnings("ignore")
    while time.time() < deadline:
        try:
            for host, port in tcp:
                if port == 8465:
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    with socket.create_connection((host, port), 2) as s:
                        ctx.wrap_socket(s, server_hostname=host).close()
                else:
                    socket.create_connection((host, port), 2).close()
            for url in http:
                if session.get(url, timeout=3).status_code != 200:
                    raise OSError(url)
            return
        except (OSError, requests.RequestException):
            time.sleep(1)
    _compose("logs", "--no-color")
    raise RuntimeError("stress stack did not become ready")


class Stack:
    """A running compose stack with load and control-plane helpers."""

    def run_k6(self, config, scenario, extra_env=None, timeout=1200):
        cfg = CONFIGS[config]
        rid = f"{config}-{scenario}.json"
        (RESULTS_DIR / rid).unlink(missing_ok=True)
        env_flags = {"SCENARIO": scenario, "EXPECT_PROTO": cfg["proto"],
                     "RESULT_FILE": rid, "INSECURE": "1", **(extra_env or {})}
        if cfg["kind"] == "ws":
            env_flags["WS_TARGET"] = cfg["target"]
            script = "ws.js"
        else:
            env_flags["TARGET"] = cfg["target"]
            script = "main.js"
        args = ["--profile", "tools", "run", "--rm"]
        for k, v in env_flags.items():
            args += ["-e", f"{k}={v}"]
        args += ["k6", "run", f"/scripts/{script}"]
        proc = _compose(*args, capture_output=True, text=True, timeout=timeout)
        summary = {}
        path = RESULTS_DIR / rid
        if path.exists():
            summary = json.loads(path.read_text())
        return K6Result(proc.returncode, summary, proc.stdout + proc.stderr)

    def worker_pids(self, service):
        out = _compose("exec", "-T", service, "pgrep", "-P", "1",
                       capture_output=True, text=True)
        return [int(p) for p in out.stdout.split() if p.strip()]

    def signal_master(self, service, sig):
        _compose("exec", "-T", service, "kill", f"-{sig}", "1", check=True)

    def kill_one_worker(self, service):
        pids = self.worker_pids(service)
        if not pids:
            return None
        _compose("exec", "-T", service, "kill", "-9", str(pids[0]), check=True)
        return pids[0]

    def logs(self, service):
        out = _compose("logs", "--no-color", service, capture_output=True, text=True)
        return out.stdout + out.stderr

    def tracebacks(self, service):
        return self.logs(service).count("Traceback (most recent call last)")

    def rss_kb(self, service):
        total = 0
        for pid in [1] + self.worker_pids(service):
            out = _compose("exec", "-T", service, "cat", f"/proc/{pid}/status",
                           capture_output=True, text=True)
            for line in out.stdout.splitlines():
                if line.startswith("VmRSS:"):
                    total += int(line.split()[1])
        return total


@pytest.fixture(scope="session")
def stack():
    if not _docker_available():
        pytest.skip("docker not available")
    _generate_cert()
    RESULTS_DIR.mkdir(exist_ok=True)
    os.chmod(RESULTS_DIR, 0o777)
    _compose("--profile", "faults", "--profile", "tools",
             "down", "-v", "--remove-orphans")  # clean any leftover stack first
    _compose("build", check=True)
    _compose("up", "-d", check=True)
    try:
        _wait_ready()
        _compose("pull", "k6", check=False)
        yield Stack()
    finally:
        _compose("--profile", "faults", "--profile", "tools",
                 "down", "-v", "--remove-orphans")


@pytest.fixture(scope="session")
def faults_stack(stack):
    """The smoke stack with a Toxiproxy front for gunicorn-asgi."""
    _compose("--profile", "faults", "up", "-d", "toxiproxy", check=True)
    # toxiproxy admin on host 8474; proxy on 8475 -> gunicorn-asgi:8000
    for _ in range(30):
        try:
            if requests.get("http://127.0.0.1:8474/version", timeout=2).ok:
                break
        except requests.RequestException:
            time.sleep(1)
    yield stack


def toxiproxy_reset():
    requests.post("http://127.0.0.1:8474/reset", timeout=5)


def add_toxic(name, toxic_type, attributes, stream="downstream", toxicity=1.0):
    body = {"name": name, "type": toxic_type, "stream": stream,
            "toxicity": toxicity, "attributes": attributes}
    r = requests.post("http://127.0.0.1:8474/proxies/asgi/toxics", json=body, timeout=5)
    r.raise_for_status()
    return r.json()


def pytest_configure(config):
    config.addinivalue_line("markers", "docker: requires a docker daemon")
    config.addinivalue_line("markers", "integration: end-to-end integration test")
    config.addinivalue_line("markers", "stress: k6 load/correctness scenarios")
    config.addinivalue_line("markers",
                            "stress_heavy: resilience and fault scenarios (opt-in)")


def pytest_collection_modifyitems(config, items):
    if HEAVY:
        return
    skip = pytest.mark.skip(reason="set GUNICORN_STRESS_HEAVY=1 to run heavy scenarios")
    for item in items:
        if "stress_heavy" in item.keywords:
            item.add_marker(skip)
