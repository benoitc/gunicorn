"""Pytest fixtures for HTTP/2 Docker integration tests."""

import subprocess
import time
from pathlib import Path

import pytest

# Directory containing this conftest.py
DOCKER_DIR = Path(__file__).parent
CERTS_DIR = DOCKER_DIR / "certs"


def generate_self_signed_cert(certs_dir: Path) -> None:
    """Generate self-signed SSL certificates for testing."""
    certs_dir.mkdir(parents=True, exist_ok=True)
    cert_file = certs_dir / "server.crt"
    key_file = certs_dir / "server.key"

    # Skip if certs already exist and are recent (less than 1 day old)
    if cert_file.exists() and key_file.exists():
        age = time.time() - cert_file.stat().st_mtime
        if age < 86400:  # 1 day
            return

    # Generate self-signed certificate
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", str(key_file),
            "-out", str(cert_file),
            "-days", "1",
            "-nodes",
            "-subj", "/CN=localhost/O=Gunicorn Test/C=US",
            "-addext", "subjectAltName=DNS:localhost,DNS:gunicorn-h2,IP:127.0.0.1"
        ],
        check=True,
        capture_output=True
    )
    # Set readable permissions
    cert_file.chmod(0o644)
    key_file.chmod(0o644)


def wait_for_service(url: str, timeout: int = 60) -> bool:
    """Wait for a service to become available."""
    import ssl
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or 'localhost'
    port = parsed.port or 443

    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            with socket.create_connection((host, port), timeout=5) as sock:
                with ctx.wrap_socket(sock, server_hostname=host):
                    return True
        except (socket.error, ssl.SSLError, OSError):
            time.sleep(1)
    return False


@pytest.fixture(scope="session")
def docker_compose_file():
    """Return the path to docker-compose.yml."""
    return DOCKER_DIR / "docker-compose.yml"


@pytest.fixture(scope="session")
def certs_dir():
    """Generate and return the certs directory."""
    generate_self_signed_cert(CERTS_DIR)
    return CERTS_DIR


@pytest.fixture(scope="session")
def docker_services(docker_compose_file, certs_dir):
    """Start Docker services for the test session."""
    compose_file = str(docker_compose_file)

    # Check if Docker is available
    try:
        subprocess.run(
            ["docker", "info"],
            check=True,
            capture_output=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("Docker is not available")

    # Check if docker compose is available
    try:
        subprocess.run(
            ["docker", "compose", "version"],
            check=True,
            capture_output=True
        )
    except subprocess.CalledProcessError:
        pytest.skip("Docker Compose is not available")

    # Build and start services
    try:
        subprocess.run(
            ["docker", "compose", "-f", compose_file, "build"],
            check=True,
            cwd=DOCKER_DIR
        )
        subprocess.run(
            ["docker", "compose", "-f", compose_file, "up", "-d"],
            check=True,
            cwd=DOCKER_DIR
        )

        # Wait for services to be healthy
        gunicorn_ready = wait_for_service("https://127.0.0.1:8443", timeout=60)
        nginx_ready = wait_for_service("https://127.0.0.1:8444", timeout=60)

        if not gunicorn_ready:
            # Get logs for debugging
            result = subprocess.run(
                ["docker", "compose", "-f", compose_file, "logs", "gunicorn-h2"],
                capture_output=True,
                text=True,
                cwd=DOCKER_DIR
            )
            pytest.fail(f"Gunicorn service failed to start. Logs:\n{result.stdout}\n{result.stderr}")

        if not nginx_ready:
            result = subprocess.run(
                ["docker", "compose", "-f", compose_file, "logs", "nginx-h2"],
                capture_output=True,
                text=True,
                cwd=DOCKER_DIR
            )
            pytest.fail(f"Nginx service failed to start. Logs:\n{result.stdout}\n{result.stderr}")

        yield {
            "gunicorn": "https://127.0.0.1:8443",
            "nginx": "https://127.0.0.1:8444"
        }

    finally:
        # Stop and remove services
        subprocess.run(
            ["docker", "compose", "-f", compose_file, "down", "-v", "--remove-orphans"],
            cwd=DOCKER_DIR,
            capture_output=True
        )


@pytest.fixture
def gunicorn_url(docker_services):
    """Return the gunicorn service URL."""
    return docker_services["gunicorn"]


@pytest.fixture
def nginx_url(docker_services):
    """Return the nginx proxy URL."""
    return docker_services["nginx"]


@pytest.fixture
def h2_client():
    """Create an HTTP/2 capable client."""
    httpx = pytest.importorskip("httpx")
    client = httpx.Client(http2=True, verify=False, timeout=30.0)
    yield client
    client.close()


@pytest.fixture
def h1_client():
    """Create an HTTP/1.1 only client."""
    httpx = pytest.importorskip("httpx")
    client = httpx.Client(http2=False, verify=False, timeout=30.0)
    yield client
    client.close()


@pytest.fixture
def async_h2_client():
    """Create an async HTTP/2 capable client."""
    httpx = pytest.importorskip("httpx")

    async def create_client():
        return httpx.AsyncClient(http2=True, verify=False, timeout=30.0)

    return create_client
