"""Integration tests for gthread worker."""
import os
import signal
import socket
import subprocess
import sys
import time

import pytest


# Timeout for CI environments
CI_TIMEOUT = 30


# Simple WSGI app
SIMPLE_APP = '''
def application(environ, start_response):
    """Basic hello world response."""
    status = '200 OK'
    body = b'Hello, World!'
    headers = [
        ('Content-Type', 'text/plain'),
        ('Content-Length', str(len(body))),
    ]
    start_response(status, headers)
    return [body]
'''


def find_free_port():
    """Find a free port to bind to."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def wait_for_server(host, port, timeout=CI_TIMEOUT):
    """Wait until server is accepting connections."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (ConnectionRefusedError, socket.timeout, OSError):
            time.sleep(0.1)
    return False


def make_request(host, port, path='/', sleep_after_create_connection=0):
    """Make a simple HTTP request and return the response body.

    Raises ConnectionError if the server closes the connection unexpectedly
    (e.g. due to pending request timeout).
    """
    with socket.create_connection((host, port), timeout=5) as sock:
        # emulate stalled connection
        time.sleep(sleep_after_create_connection)

        request = f'GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n'
        sock.sendall(request.encode())

        # Signal that we're done sending; helps detect connection loss on write
        try:
            sock.shutdown(socket.SHUT_WR)
        except OSError:
            # Server already closed the connection before or during our send
            raise ConnectionError("Server closed the connection before completing the request")

        response = b''
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk

        if not response:
            raise ConnectionError(
                "Server closed the connection unexpectedly; no response received"
            )

        return response


@pytest.fixture
def app_module(tmp_path):
    """Create a temporary app module."""
    app_file = tmp_path / "app.py"
    app_file.write_text(SIMPLE_APP)
    return str(app_file.parent), "app:application"


def start_gunicorn(app_dir, app_name, port, keepalive=None):
    """Start a gunicorn server with specified worker class and control socket."""
    cmd = [
        sys.executable, '-m', 'gunicorn',
        '--bind', f'127.0.0.1:{port}',
        '--workers', '1',
        '--worker-class', 'gthread',
        '--threads', '2',
        '--access-logfile', '-',
        '--error-logfile', '-',
        '--log-level', 'debug',
        '--timeout', '30',
        '--no-control-socket',
    ]
    if keepalive is not None:
        cmd += ['--keep-alive', str(keepalive)]

    cmd += [app_name]

    proc = subprocess.Popen(
        cmd,
        cwd=app_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, 'PYTHONPATH': app_dir},
        preexec_fn=os.setsid
    )

    return proc


def cleanup_gunicorn(proc):
    """Clean up a gunicorn process."""
    if proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            proc.wait()


class TestPendingRequestLifecycle:
    """Test pending requests safety in gthread worker."""

    @pytest.mark.parametrize(
        ('keepalive', 'sleep_after_create_connection'), [
        (None, 3),      # used DEFAULT_PENDING_REQUEST_MIN_WAIT_TIMEOUT
        (2, 3),         # used DEFAULT_PENDING_REQUEST_MIN_WAIT_TIMEOUT
        (8, 6),         # used keep-alive timeout
    ])
    def test_send_request_inside_pending_request_timeout(
            self,
            app_module,
            tmp_path,
            keepalive,
            sleep_after_create_connection,
    ):
        """Request succeeds when client sends data within the pending request window."""

        app_dir, app_name = app_module
        port = find_free_port()

        proc = start_gunicorn(app_dir, app_name, port, keepalive=keepalive)

        try:
            # Wait for server to start - should not deadlock
            if not wait_for_server('127.0.0.1', port, timeout=15):
                stdout, stderr = proc.communicate(timeout=1)
                pytest.fail(
                    f"Gthread worker deadlocked during startup:\n"
                    f"stdout: {stdout.decode()}\n"
                    f"stderr: {stderr.decode()}"
                )

            # Verify server responds
            response = make_request(
                host='127.0.0.1',
                port=port,
                sleep_after_create_connection=sleep_after_create_connection,
            )

            assert b'Hello, World!' in response

        finally:
            cleanup_gunicorn(proc)

    @pytest.mark.parametrize(
        ('keepalive', 'sleep_after_create_connection'), [
        (None, 7),      # used DEFAULT_PENDING_REQUEST_MIN_WAIT_TIMEOUT
        (2, 7),         # used DEFAULT_PENDING_REQUEST_MIN_WAIT_TIMEOUT
        (8, 10),        # used keep-alive timeout
    ])
    def test_send_request_outside_pending_request_timeout(
            self,
            app_module,
            tmp_path,
            keepalive,
            sleep_after_create_connection,
    ):
        """Client gets a connection error when data arrives after the pending request window."""

        app_dir, app_name = app_module
        port = find_free_port()

        proc = start_gunicorn(app_dir, app_name, port, keepalive=keepalive)

        try:
            # Wait for server to start - should not deadlock
            if not wait_for_server('127.0.0.1', port, timeout=15):
                stdout, stderr = proc.communicate(timeout=1)
                pytest.fail(
                    f"Gthread worker deadlocked during startup:\n"
                    f"stdout: {stdout.decode()}\n"
                    f"stderr: {stderr.decode()}"
                )

            with pytest.raises(ConnectionError):
                make_request(
                    host='127.0.0.1',
                    port=port,
                    sleep_after_create_connection=sleep_after_create_connection,
                )

        finally:
            cleanup_gunicorn(proc)
