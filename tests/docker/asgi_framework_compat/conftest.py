"""
Pytest configuration for ASGI Framework Compatibility Tests

This module provides fixtures for parameterized testing across multiple
ASGI frameworks running in Docker containers with gunicorn's ASGI worker.
"""

import asyncio
import json
import os
import subprocess
import time
from typing import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
import websockets

# Framework configuration
FRAMEWORKS = {
    "django": {"port": 8001, "websocket_support": True},
    "fastapi": {"port": 8002, "websocket_support": True},
    "starlette": {"port": 8003, "websocket_support": True},
    "quart": {"port": 8004, "websocket_support": True},
    "litestar": {"port": 8005, "websocket_support": True},
    "blacksheep": {"port": 8006, "websocket_support": True},
}

# Host for docker containers
DOCKER_HOST = os.environ.get("DOCKER_HOST_IP", "127.0.0.1")


def pytest_addoption(parser):
    """Add command line options for framework selection."""
    parser.addoption(
        "--framework",
        action="store",
        default=None,
        help="Run tests only for specific framework (django, fastapi, etc.)",
    )
    parser.addoption(
        "--skip-docker-check",
        action="store_true",
        default=False,
        help="Skip Docker container health checks",
    )


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "framework(name): mark test to run only for specific framework"
    )


def pytest_collection_modifyitems(config, items):
    """Filter tests based on framework selection."""
    framework_filter = config.getoption("--framework")
    if framework_filter:
        skip_other = pytest.mark.skip(
            reason=f"Only running tests for {framework_filter}"
        )
        for item in items:
            markers = [m for m in item.iter_markers(name="framework")]
            if markers:
                framework_names = [m.args[0] for m in markers]
                if framework_filter not in framework_names:
                    item.add_marker(skip_other)


@pytest.fixture(scope="session")
def docker_compose_file():
    """Return path to docker-compose file."""
    return os.path.join(os.path.dirname(__file__), "docker-compose.yml")


def wait_for_service(url: str, timeout: int = 60) -> bool:
    """Wait for a service to become healthy."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            response = httpx.get(f"{url}/health", timeout=5.0)
            if response.status_code == 200:
                return True
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        time.sleep(1)
    return False


@pytest.fixture(scope="session")
def docker_services(docker_compose_file, request):
    """Start Docker services for testing."""
    if request.config.getoption("--skip-docker-check"):
        yield
        return

    # Check if containers are already running
    all_healthy = True
    for name, config in FRAMEWORKS.items():
        url = f"http://{DOCKER_HOST}:{config['port']}"
        try:
            response = httpx.get(f"{url}/health", timeout=2.0)
            if response.status_code != 200:
                all_healthy = False
                break
        except (httpx.ConnectError, httpx.TimeoutException):
            all_healthy = False
            break

    if all_healthy:
        yield
        return

    # Start containers
    compose_dir = os.path.dirname(docker_compose_file)
    subprocess.run(
        ["docker", "compose", "up", "-d", "--build"],
        cwd=compose_dir,
        check=True,
    )

    # Wait for all services to be healthy
    for name, config in FRAMEWORKS.items():
        url = f"http://{DOCKER_HOST}:{config['port']}"
        if not wait_for_service(url):
            pytest.fail(f"Service {name} failed to start")

    yield

    # Optionally stop containers after tests
    if os.environ.get("CLEANUP_DOCKER", "0") == "1":
        subprocess.run(
            ["docker", "compose", "down"],
            cwd=compose_dir,
            check=True,
        )


@pytest.fixture(params=list(FRAMEWORKS.keys()))
def framework(request, docker_services) -> str:
    """Parameterized fixture that yields each framework name."""
    return request.param


@pytest.fixture
def framework_config(framework) -> dict:
    """Return configuration for current framework."""
    return FRAMEWORKS[framework]


@pytest.fixture
def framework_url(framework) -> str:
    """Return HTTP URL for current framework."""
    port = FRAMEWORKS[framework]["port"]
    return f"http://{DOCKER_HOST}:{port}"


@pytest.fixture
def framework_ws_url(framework) -> str:
    """Return WebSocket URL for current framework."""
    port = FRAMEWORKS[framework]["port"]
    return f"ws://{DOCKER_HOST}:{port}"


@pytest_asyncio.fixture
async def http_client(framework_url) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Async HTTP client for testing."""
    async with httpx.AsyncClient(base_url=framework_url, timeout=30.0) as client:
        yield client


@pytest.fixture
def ws_client(framework_ws_url):
    """WebSocket client factory for testing."""

    async def connect(path: str, **kwargs):
        uri = f"{framework_ws_url}{path}"
        return await websockets.connect(uri, **kwargs)

    return connect


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Store test report for result recording."""
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)


# Utility fixtures
@pytest.fixture
def random_bytes():
    """Generate random bytes for testing."""

    def _generate(size: int) -> bytes:
        return os.urandom(size)

    return _generate


@pytest.fixture
def large_body():
    """Generate large request/response body."""

    def _generate(size: int) -> bytes:
        return b"x" * size

    return _generate
