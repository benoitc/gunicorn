#!/usr/bin/env python
# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Reproduction and regression test for HTTP/2 ASGI body duplication.

https://github.com/benoitc/gunicorn/discussions/3567

Bug: When an HTTP/2 POST with a JSON body is sent to a gunicorn ASGI server,
the receive() closure reads the body via read_body_chunk() (streaming path),
but _body_complete is never set to True by _handle_stream_ended() in
async_connection.py, so the fast path re-reads the same data from BytesIO
- doubling the request body.

This test starts a real gunicorn ASGI server with TLS + HTTP/2, sends a POST
request with a JSON body, and verifies the server sees the correct body (not
doubled).
"""

import json
import os
import ssl
import subprocess
import sys
import tempfile
import time

import pytest

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

try:
    import h2  # noqa: F401
    H2_AVAILABLE = True
except ImportError:
    H2_AVAILABLE = False


pytestmark = [
    pytest.mark.skipif(not HTTPX_AVAILABLE, reason="httpx not available"),
    pytest.mark.skipif(not H2_AVAILABLE, reason="h2 not available"),
]


def _httpx_body_len(payload):
    """Return the byte length that httpx will actually send for a JSON payload.

    httpx uses compact JSON serialisation (no spaces), which differs from
    Python's default json.dumps().
    """
    req = httpx.Request("POST", "https://localhost/", json=payload)
    return len(req.content)


# --- Inline ASGI app (echoes the raw request body back) ---

ASGI_APP_CODE = '''
import json

async def app(scope, receive, send):
    """Minimal ASGI app that echoes the request body and its length."""
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return

    if scope["type"] != "http":
        return

    # Read the full request body
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if not message.get("more_body", False):
            break

    # Echo it back with metadata
    response = {
        "body_length": len(body),
        "body": body.decode("utf-8", errors="replace"),
    }
    response_body = json.dumps(response).encode("utf-8")

    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            [b"content-type", b"application/json"],
            [b"content-length", str(len(response_body)).encode()],
        ],
    })
    await send({
        "type": "http.response.body",
        "body": response_body,
    })
'''


@pytest.fixture(scope="module")
def tls_certs():
    """Generate self-signed TLS certificates for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ca_key = os.path.join(tmpdir, "ca.key")
        ca_crt = os.path.join(tmpdir, "ca.crt")
        server_key = os.path.join(tmpdir, "server.key")
        server_csr = os.path.join(tmpdir, "server.csr")
        server_crt = os.path.join(tmpdir, "server.crt")

        # Generate CA
        subprocess.run([
            "openssl", "genrsa", "-out", ca_key, "2048"
        ], check=True, capture_output=True)
        subprocess.run([
            "openssl", "req", "-x509", "-new", "-nodes",
            "-key", ca_key, "-sha256", "-days", "1",
            "-out", ca_crt, "-subj", "/CN=Test CA"
        ], check=True, capture_output=True)

        # Generate server cert
        subprocess.run([
            "openssl", "genrsa", "-out", server_key, "2048"
        ], check=True, capture_output=True)
        subprocess.run([
            "openssl", "req", "-new", "-key", server_key,
            "-out", server_csr, "-subj", "/CN=localhost",
            "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"
        ], check=True, capture_output=True)
        subprocess.run([
            "openssl", "x509", "-req", "-in", server_csr,
            "-CA", ca_crt, "-CAkey", ca_key, "-CAcreateserial",
            "-out", server_crt, "-days", "1", "-sha256",
            "-copy_extensions", "copyall"
        ], check=True, capture_output=True)

        yield {
            "ca_crt": ca_crt,
            "server_crt": server_crt,
            "server_key": server_key,
            "tmpdir": tmpdir,
        }


@pytest.fixture(scope="module")
def gunicorn_server(tls_certs):
    """Start a gunicorn ASGI server with TLS and HTTP/2."""
    # Write the ASGI app to a temp file
    app_file = os.path.join(tls_certs["tmpdir"], "asgi_app.py")
    with open(app_file, "w") as f:
        f.write(ASGI_APP_CODE)

    port = 9443  # Use a high port to avoid conflicts

    env = os.environ.copy()
    # Ensure the temp dir is on the Python path so gunicorn can import the app
    env["PYTHONPATH"] = tls_certs["tmpdir"]

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "gunicorn",
            "--worker-class", "gunicorn.workers.gasgi.ASGIWorker",
            "--bind", f"127.0.0.1:{port}",
            "--certfile", tls_certs["server_crt"],
            "--keyfile", tls_certs["server_key"],
            "--http-protocols", "h2,h1",
            "--workers", "1",
            "--log-level", "debug",
            "--chdir", tls_certs["tmpdir"],
            "asgi_app:app",
        ],
        cwd=tls_certs["tmpdir"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for server to start
    ca_ctx = ssl.create_default_context(cafile=tls_certs["ca_crt"])
    base_url = f"https://127.0.0.1:{port}"

    for _ in range(40):  # Up to 8 seconds
        time.sleep(0.2)
        try:
            with httpx.Client(verify=ca_ctx, timeout=2.0) as client:
                resp = client.get(base_url + "/")
                if resp.status_code in (200, 404):
                    break
        except Exception:
            if proc.poll() is not None:
                stdout = proc.stdout.read().decode()
                stderr = proc.stderr.read().decode()
                pytest.fail(
                    f"gunicorn exited early (code {proc.returncode}).\n"
                    f"stdout: {stdout}\nstderr: {stderr}"
                )
            continue
    else:
        proc.terminate()
        proc.wait()
        stdout = proc.stdout.read().decode()
        stderr = proc.stderr.read().decode()
        pytest.fail(
            f"gunicorn did not start within 8 seconds.\n"
            f"stdout: {stdout}\nstderr: {stderr}"
        )

    yield {"base_url": base_url, "ca_crt": tls_certs["ca_crt"]}

    proc.terminate()
    proc.wait(timeout=5)


class TestH2BodyDuplicationFix:
    """End-to-end tests proving HTTP/2 POST body is not duplicated."""

    def test_h2_post_json_body_not_duplicated(self, gunicorn_server):
        """POST a JSON body over HTTP/2 and verify it arrives intact.

        Before the fix, the server would see the body twice:
          {"input":["hello world"]}{"input":["hello world"]}
        causing a JSON decode error.
        """
        ca_ctx = ssl.create_default_context(
            cafile=gunicorn_server["ca_crt"]
        )
        body = {"input": ["hello world"]}
        expected_len = _httpx_body_len(body)

        with httpx.Client(http2=True, verify=ca_ctx, timeout=10.0) as client:
            resp = client.post(
                gunicorn_server["base_url"] + "/",
                json=body,
            )

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        assert resp.http_version == "HTTP/2", (
            f"Expected HTTP/2, got {resp.http_version} - "
            "test is not exercising the h2 code path"
        )

        data = resp.json()
        assert data["body_length"] == expected_len, (
            f"Body length mismatch: server received {data['body_length']} bytes "
            f"but sent {expected_len} bytes. "
            f"Server saw: {data['body']!r}"
        )
        # Verify the JSON round-trips correctly
        assert json.loads(data["body"]) == body

    def test_h2_post_json_round_trip(self, gunicorn_server):
        """Verify JSON payload round-trips correctly over HTTP/2."""
        ca_ctx = ssl.create_default_context(
            cafile=gunicorn_server["ca_crt"]
        )
        body = {"input": ["hello world"], "model": "voyage-3"}

        with httpx.Client(http2=True, verify=ca_ctx, timeout=10.0) as client:
            resp = client.post(
                gunicorn_server["base_url"] + "/",
                json=body,
            )

        assert resp.status_code == 200
        assert resp.http_version == "HTTP/2"
        data = resp.json()
        assert json.loads(data["body"]) == body

    def test_h2_multiple_sequential_posts(self, gunicorn_server):
        """Multiple POSTs on the same connection must all succeed."""
        ca_ctx = ssl.create_default_context(
            cafile=gunicorn_server["ca_crt"]
        )

        with httpx.Client(http2=True, verify=ca_ctx, timeout=10.0) as client:
            for i in range(5):
                body = {"request_number": i, "input": [f"test {i}"]}
                expected_len = _httpx_body_len(body)

                resp = client.post(
                    gunicorn_server["base_url"] + "/",
                    json=body,
                )

                assert resp.status_code == 200, f"Request {i} failed: {resp.text}"
                assert resp.http_version == "HTTP/2"
                data = resp.json()
                assert data["body_length"] == expected_len, (
                    f"Request {i}: body length mismatch "
                    f"({data['body_length']} != {expected_len})"
                )
                assert json.loads(data["body"]) == body

    def test_h1_post_still_works(self, gunicorn_server):
        """HTTP/1.1 POST must continue to work (no regression)."""
        ca_ctx = ssl.create_default_context(
            cafile=gunicorn_server["ca_crt"]
        )
        body = {"input": ["hello world"]}
        expected_len = _httpx_body_len(body)

        # http2=False forces HTTP/1.1
        with httpx.Client(http2=False, verify=ca_ctx, timeout=10.0) as client:
            resp = client.post(
                gunicorn_server["base_url"] + "/",
                json=body,
            )

        assert resp.status_code == 200
        assert resp.http_version == "HTTP/1.1"
        data = resp.json()
        assert data["body_length"] == expected_len
        assert json.loads(data["body"]) == body
