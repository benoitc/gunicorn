#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.
"""
Integration tests for control socket fork safety.

These tests verify that the control socket server properly handles fork()
with different worker types (sync, gthread, gevent) without causing deadlocks.
"""

import os
import signal
import socket
import subprocess
import sys
import time
import tempfile

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


def wait_for_socket(socket_path, timeout=CI_TIMEOUT):
    """Wait until Unix socket exists."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if os.path.exists(socket_path):
            return True
        time.sleep(0.1)
    return False


def make_request(host, port, path='/'):
    """Make a simple HTTP request and return the response body."""
    with socket.create_connection((host, port), timeout=5) as sock:
        request = f'GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n'
        sock.sendall(request.encode())
        response = b''
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk
        return response


@pytest.fixture
def app_module(tmp_path):
    """Create a temporary app module."""
    app_file = tmp_path / "app.py"
    app_file.write_text(SIMPLE_APP)
    return str(app_file.parent), "app:application"


def start_gunicorn(app_dir, app_name, worker_class, port, control_socket_path):
    """Start a gunicorn server with specified worker class and control socket."""
    cmd = [
        sys.executable, '-m', 'gunicorn',
        '--bind', f'127.0.0.1:{port}',
        '--workers', '2',
        '--worker-class', worker_class,
        '--access-logfile', '-',
        '--error-logfile', '-',
        '--log-level', 'debug',
        '--timeout', '30',
        '--control-socket', control_socket_path,
        app_name
    ]

    # Add threads for gthread worker
    if worker_class == 'gthread':
        cmd.extend(['--threads', '2'])

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


def get_short_socket_path(prefix):
    """Get a short socket path that won't exceed Unix socket path limits.

    macOS limits Unix socket paths to ~104 characters, so we use /tmp directly.
    """
    import uuid
    return f"/tmp/gunicorn-{prefix}-{uuid.uuid4().hex[:8]}.ctl"


class TestControlSocketForkSafetySyncWorker:
    """Test control socket fork safety with sync worker."""

    def test_sync_worker_boots_with_control_socket(self, app_module, tmp_path):
        """Verify sync worker boots without deadlock when control socket is enabled."""
        app_dir, app_name = app_module
        port = find_free_port()
        # Use short path to avoid Unix socket path length limits (104 chars on macOS)
        control_socket = get_short_socket_path("sync")

        proc = start_gunicorn(app_dir, app_name, 'sync', port, control_socket)

        try:
            # Wait for server to start - should not deadlock
            if not wait_for_server('127.0.0.1', port, timeout=15):
                stdout, stderr = proc.communicate(timeout=1)
                pytest.fail(
                    f"Sync worker deadlocked during startup:\n"
                    f"stdout: {stdout.decode()}\n"
                    f"stderr: {stderr.decode()}"
                )

            # Verify server responds
            response = make_request('127.0.0.1', port)
            assert b'Hello, World!' in response

            # Wait for control socket to be created (started after workers spawn)
            assert wait_for_socket(control_socket, timeout=5), \
                f"Control socket was not created at {control_socket}"

        finally:
            cleanup_gunicorn(proc)
            # Clean up socket file
            if os.path.exists(control_socket):
                os.unlink(control_socket)


class TestControlSocketForkSafetyGthreadWorker:
    """Test control socket fork safety with gthread worker."""

    def test_gthread_worker_boots_with_control_socket(self, app_module, tmp_path):
        """Verify gthread worker boots without deadlock when control socket is enabled."""
        app_dir, app_name = app_module
        port = find_free_port()
        control_socket = get_short_socket_path("gthread")

        proc = start_gunicorn(app_dir, app_name, 'gthread', port, control_socket)

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
            response = make_request('127.0.0.1', port)
            assert b'Hello, World!' in response

            # Wait for control socket to be created (started after workers spawn)
            assert wait_for_socket(control_socket, timeout=5), \
                f"Control socket was not created at {control_socket}"

        finally:
            cleanup_gunicorn(proc)
            if os.path.exists(control_socket):
                os.unlink(control_socket)


def is_gevent_available():
    """Check if gevent is available."""
    try:
        import gevent  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not is_gevent_available(), reason="gevent not installed")
class TestControlSocketForkSafetyGeventWorker:
    """Test control socket fork safety with gevent worker."""

    def test_gevent_worker_boots_with_control_socket(self, app_module, tmp_path):
        """Verify gevent worker boots without deadlock when control socket is enabled.

        This test is critical for issue #3509 - the gevent worker uses monkey
        patching which can interact badly with asyncio in the control socket thread.
        """
        app_dir, app_name = app_module
        port = find_free_port()
        control_socket = get_short_socket_path("gevent")

        proc = start_gunicorn(app_dir, app_name, 'gevent', port, control_socket)

        try:
            # Wait for server to start - should not deadlock
            # Gevent workers may take slightly longer to boot
            if not wait_for_server('127.0.0.1', port, timeout=20):
                stdout, stderr = proc.communicate(timeout=1)
                pytest.fail(
                    f"Gevent worker deadlocked during startup:\n"
                    f"stdout: {stdout.decode()}\n"
                    f"stderr: {stderr.decode()}"
                )

            # Verify server responds
            response = make_request('127.0.0.1', port)
            assert b'Hello, World!' in response

            # Wait for control socket to be created (started after workers spawn)
            assert wait_for_socket(control_socket, timeout=5), \
                f"Control socket was not created at {control_socket}"

        finally:
            cleanup_gunicorn(proc)
            if os.path.exists(control_socket):
                os.unlink(control_socket)

    def test_gevent_worker_handles_multiple_requests(self, app_module, tmp_path):
        """Verify gevent worker handles multiple requests with control socket enabled."""
        app_dir, app_name = app_module
        port = find_free_port()
        control_socket = get_short_socket_path("gevent2")

        proc = start_gunicorn(app_dir, app_name, 'gevent', port, control_socket)

        try:
            if not wait_for_server('127.0.0.1', port, timeout=20):
                stdout, stderr = proc.communicate(timeout=1)
                pytest.fail(
                    f"Gevent worker deadlocked during startup:\n"
                    f"stdout: {stdout.decode()}\n"
                    f"stderr: {stderr.decode()}"
                )

            # Make multiple requests
            for _ in range(10):
                response = make_request('127.0.0.1', port)
                assert b'Hello, World!' in response

            # Verify server is still running
            assert proc.poll() is None, "Server died unexpectedly"

        finally:
            cleanup_gunicorn(proc)
            if os.path.exists(control_socket):
                os.unlink(control_socket)


class TestControlSocketDisabled:
    """Test that disabling control socket works."""

    def test_no_control_socket_flag(self, app_module, tmp_path):
        """Verify --no-control-socket flag disables control socket."""
        app_dir, app_name = app_module
        port = find_free_port()
        control_socket = str(tmp_path / "gunicorn.ctl")

        cmd = [
            sys.executable, '-m', 'gunicorn',
            '--bind', f'127.0.0.1:{port}',
            '--workers', '1',
            '--worker-class', 'sync',
            '--access-logfile', '-',
            '--error-logfile', '-',
            '--log-level', 'debug',
            '--no-control-socket',
            app_name
        ]

        proc = subprocess.Popen(
            cmd,
            cwd=app_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, 'PYTHONPATH': app_dir},
            preexec_fn=os.setsid
        )

        try:
            if not wait_for_server('127.0.0.1', port, timeout=15):
                stdout, stderr = proc.communicate(timeout=1)
                pytest.fail(
                    f"Server failed to start:\n"
                    f"stdout: {stdout.decode()}\n"
                    f"stderr: {stderr.decode()}"
                )

            # Verify server responds
            response = make_request('127.0.0.1', port)
            assert b'Hello, World!' in response

            # Verify control socket does NOT exist
            assert not os.path.exists(control_socket), "Control socket should not exist"

        finally:
            cleanup_gunicorn(proc)


class TestControlSocketAfterReload:
    """Test control socket survives reload."""

    def test_control_socket_after_sighup(self, app_module, tmp_path):
        """Verify control socket still works after SIGHUP reload."""
        app_dir, app_name = app_module
        port = find_free_port()
        control_socket = get_short_socket_path("reload")

        proc = start_gunicorn(app_dir, app_name, 'sync', port, control_socket)

        try:
            if not wait_for_server('127.0.0.1', port, timeout=15):
                stdout, stderr = proc.communicate(timeout=1)
                pytest.fail(
                    f"Server failed to start:\n"
                    f"stdout: {stdout.decode()}\n"
                    f"stderr: {stderr.decode()}"
                )

            # Verify server and control socket work
            response = make_request('127.0.0.1', port)
            assert b'Hello, World!' in response
            assert wait_for_socket(control_socket, timeout=5), \
                f"Control socket was not created at {control_socket}"

            # Send SIGHUP to trigger reload
            proc.send_signal(signal.SIGHUP)

            # Wait for reload to complete
            time.sleep(2)

            # Verify server still works after reload
            assert proc.poll() is None, "Server died after SIGHUP"
            response = make_request('127.0.0.1', port)
            assert b'Hello, World!' in response

            # Verify control socket still exists
            assert os.path.exists(control_socket), "Control socket disappeared after reload"

        finally:
            cleanup_gunicorn(proc)
            if os.path.exists(control_socket):
                os.unlink(control_socket)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
