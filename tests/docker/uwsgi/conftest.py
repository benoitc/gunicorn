#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
pytest fixtures for uWSGI Docker integration tests.
"""

import os
import subprocess
import time

import pytest
import requests


COMPOSE_FILE = os.path.join(os.path.dirname(__file__), 'docker-compose.yml')
NGINX_URL = 'http://127.0.0.1:8080'
STARTUP_TIMEOUT = 60  # seconds


def is_docker_available():
    """Check if Docker is available."""
    try:
        result = subprocess.run(
            ['docker', 'info'],
            capture_output=True,
            timeout=10
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def is_compose_available():
    """Check if docker compose is available."""
    try:
        result = subprocess.run(
            ['docker', 'compose', 'version'],
            capture_output=True,
            timeout=10
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


docker_available = pytest.mark.skipif(
    not is_docker_available() or not is_compose_available(),
    reason="Docker or docker compose not available"
)


@pytest.fixture(scope='session')
def docker_services():
    """
    Start Docker Compose services for the test session.

    This fixture builds and starts the gunicorn and nginx containers,
    waits for them to be healthy, and tears them down after all tests.
    """
    if not is_docker_available() or not is_compose_available():
        pytest.skip("Docker or docker compose not available")

    # Build and start services
    subprocess.run(
        ['docker', 'compose', '-f', COMPOSE_FILE, 'build'],
        check=True,
        capture_output=True
    )

    subprocess.run(
        ['docker', 'compose', '-f', COMPOSE_FILE, 'up', '-d'],
        check=True,
        capture_output=True
    )

    # Wait for services to be healthy
    start_time = time.time()
    while time.time() - start_time < STARTUP_TIMEOUT:
        try:
            response = requests.get(f'{NGINX_URL}/', timeout=2)
            if response.status_code == 200:
                break
        except requests.RequestException:
            pass
        time.sleep(1)
    else:
        # Get logs for debugging
        logs = subprocess.run(
            ['docker', 'compose', '-f', COMPOSE_FILE, 'logs'],
            capture_output=True,
            text=True
        )
        subprocess.run(
            ['docker', 'compose', '-f', COMPOSE_FILE, 'down', '-v'],
            capture_output=True
        )
        pytest.fail(
            f"Services did not become healthy within {STARTUP_TIMEOUT}s.\n"
            f"Logs:\n{logs.stdout}\n{logs.stderr}"
        )

    yield

    # Teardown
    subprocess.run(
        ['docker', 'compose', '-f', COMPOSE_FILE, 'down', '-v'],
        capture_output=True
    )


@pytest.fixture
def nginx_url(docker_services):
    """Return the nginx base URL."""
    return NGINX_URL


@pytest.fixture
def session(docker_services):
    """Return a requests Session with keep-alive enabled."""
    with requests.Session() as s:
        # Enable keep-alive
        s.headers['Connection'] = 'keep-alive'
        yield s
