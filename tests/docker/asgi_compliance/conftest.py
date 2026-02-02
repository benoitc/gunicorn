"""Pytest fixtures for ASGI compliance Docker integration tests."""

import subprocess
import time
import socket
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
            "-addext", "subjectAltName=DNS:localhost,DNS:gunicorn-asgi,DNS:gunicorn-asgi-ssl,IP:127.0.0.1"
        ],
        check=True,
        capture_output=True
    )
    # Set readable permissions
    cert_file.chmod(0o644)
    key_file.chmod(0o644)


def wait_for_http_service(host: str, port: int, timeout: int = 60) -> bool:
    """Wait for an HTTP service to become available."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.create_connection((host, port), timeout=5):
                return True
        except (socket.error, OSError):
            time.sleep(1)
    return False


def wait_for_https_service(host: str, port: int, timeout: int = 60) -> bool:
    """Wait for an HTTPS service to become available."""
    import ssl

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
        gunicorn_http_ready = wait_for_http_service("127.0.0.1", 8000, timeout=60)
        gunicorn_https_ready = wait_for_https_service("127.0.0.1", 8445, timeout=60)
        nginx_http_ready = wait_for_http_service("127.0.0.1", 8080, timeout=60)
        nginx_https_ready = wait_for_https_service("127.0.0.1", 8444, timeout=60)

        if not gunicorn_http_ready:
            result = subprocess.run(
                ["docker", "compose", "-f", compose_file, "logs", "gunicorn-asgi"],
                capture_output=True,
                text=True,
                cwd=DOCKER_DIR
            )
            pytest.fail(f"Gunicorn HTTP service failed to start. Logs:\n{result.stdout}\n{result.stderr}")

        if not gunicorn_https_ready:
            result = subprocess.run(
                ["docker", "compose", "-f", compose_file, "logs", "gunicorn-asgi-ssl"],
                capture_output=True,
                text=True,
                cwd=DOCKER_DIR
            )
            pytest.fail(f"Gunicorn HTTPS service failed to start. Logs:\n{result.stdout}\n{result.stderr}")

        if not nginx_http_ready or not nginx_https_ready:
            result = subprocess.run(
                ["docker", "compose", "-f", compose_file, "logs", "nginx-proxy"],
                capture_output=True,
                text=True,
                cwd=DOCKER_DIR
            )
            pytest.fail(f"Nginx service failed to start. Logs:\n{result.stdout}\n{result.stderr}")

        yield {
            "gunicorn_http": "http://127.0.0.1:8000",
            "gunicorn_https": "https://127.0.0.1:8445",
            "nginx_http": "http://127.0.0.1:8080",
            "nginx_https": "https://127.0.0.1:8444",
        }

    finally:
        # Stop and remove services
        subprocess.run(
            ["docker", "compose", "-f", compose_file, "down", "-v", "--remove-orphans"],
            cwd=DOCKER_DIR,
            capture_output=True
        )


# ============================================================================
# URL Fixtures
# ============================================================================

@pytest.fixture
def gunicorn_url(docker_services):
    """Return the gunicorn HTTP service URL."""
    return docker_services["gunicorn_http"]


@pytest.fixture
def gunicorn_ssl_url(docker_services):
    """Return the gunicorn HTTPS service URL."""
    return docker_services["gunicorn_https"]


@pytest.fixture
def nginx_url(docker_services):
    """Return the nginx HTTP proxy URL."""
    return docker_services["nginx_http"]


@pytest.fixture
def nginx_ssl_url(docker_services):
    """Return the nginx HTTPS proxy URL."""
    return docker_services["nginx_https"]


# ============================================================================
# HTTP Client Fixtures
# ============================================================================

@pytest.fixture
def http_client():
    """Create a standard HTTP client."""
    httpx = pytest.importorskip("httpx")
    client = httpx.Client(verify=False, timeout=30.0, follow_redirects=False)
    yield client
    client.close()


@pytest.fixture
def http2_client():
    """Create an HTTP/2 capable client."""
    httpx = pytest.importorskip("httpx")
    client = httpx.Client(http2=True, verify=False, timeout=30.0)
    yield client
    client.close()


@pytest.fixture
async def async_http_client():
    """Create an async HTTP client."""
    httpx = pytest.importorskip("httpx")
    async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
        yield client


@pytest.fixture
def async_http_client_factory():
    """Factory for creating async HTTP clients."""
    httpx = pytest.importorskip("httpx")

    async def create_client(**kwargs):
        defaults = {"verify": False, "timeout": 30.0}
        defaults.update(kwargs)
        return httpx.AsyncClient(**defaults)

    return create_client


# ============================================================================
# WebSocket Client Fixtures
# ============================================================================

@pytest.fixture
def websocket_connect():
    """Factory for creating WebSocket connections."""
    websockets = pytest.importorskip("websockets")

    async def connect(url, **kwargs):
        """Connect to a WebSocket endpoint.

        Args:
            url: WebSocket URL (ws:// or wss://)
            **kwargs: Additional arguments for websockets.connect()

        Returns:
            WebSocket connection
        """
        import ssl

        # Default SSL context for wss://
        if url.startswith("wss://") and "ssl" not in kwargs:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            kwargs["ssl"] = ssl_context

        return await websockets.connect(url, **kwargs)

    return connect


# ============================================================================
# Streaming Client Fixtures
# ============================================================================

@pytest.fixture
def sse_client():
    """Create a client for Server-Sent Events."""
    httpx = pytest.importorskip("httpx")

    class SSEClient:
        def __init__(self):
            self.client = httpx.Client(verify=False, timeout=60.0)

        def stream(self, url):
            """Stream SSE events from URL."""
            with self.client.stream("GET", url, headers={"Accept": "text/event-stream"}) as response:
                buffer = ""
                for chunk in response.iter_text():
                    buffer += chunk
                    while "\n\n" in buffer:
                        event, buffer = buffer.split("\n\n", 1)
                        yield self._parse_event(event)

        def _parse_event(self, event_text):
            """Parse an SSE event."""
            event = {"data": None, "event": None, "id": None}
            for line in event_text.strip().split("\n"):
                if line.startswith("data: "):
                    event["data"] = line[6:]
                elif line.startswith("event: "):
                    event["event"] = line[7:]
                elif line.startswith("id: "):
                    event["id"] = line[4:]
            return event

        def close(self):
            self.client.close()

    client = SSEClient()
    yield client
    client.close()


@pytest.fixture
def streaming_client():
    """Create a client for chunked/streaming responses."""
    httpx = pytest.importorskip("httpx")

    class StreamingClient:
        def __init__(self):
            self.client = httpx.Client(verify=False, timeout=60.0)

        def stream_chunks(self, url, method="GET", **kwargs):
            """Stream response chunks from URL."""
            with self.client.stream(method, url, **kwargs) as response:
                for chunk in response.iter_bytes():
                    if chunk:
                        yield chunk

        def stream_lines(self, url, method="GET", **kwargs):
            """Stream response lines from URL."""
            with self.client.stream(method, url, **kwargs) as response:
                for line in response.iter_lines():
                    yield line

        def close(self):
            self.client.close()

    client = StreamingClient()
    yield client
    client.close()


# ============================================================================
# Test Markers
# ============================================================================

def pytest_configure(config):
    """Configure custom pytest markers."""
    config.addinivalue_line("markers", "docker: tests requiring Docker")
    config.addinivalue_line("markers", "asgi: ASGI-related tests")
    config.addinivalue_line("markers", "websocket: WebSocket tests")
    config.addinivalue_line("markers", "streaming: Streaming response tests")
    config.addinivalue_line("markers", "lifespan: Lifespan protocol tests")
    config.addinivalue_line("markers", "framework: Framework integration tests")
    config.addinivalue_line("markers", "concurrency: Concurrency tests")
    config.addinivalue_line("markers", "http2: HTTP/2 specific tests")
    config.addinivalue_line("markers", "ssl: SSL/TLS tests")
    config.addinivalue_line("markers", "integration: Integration tests")
