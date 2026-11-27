"""
Background Task Tests

Starlette and FastAPI run background tasks inside the application call,
after the response is sent. The next request on the same keep-alive
connection must not wait for them (issue #3819).
"""

import asyncio
import time

import httpx
import pytest


pytestmark = pytest.mark.http

TASK_SECONDS = 3


@pytest.fixture(params=["fastapi", "starlette"])
def framework(request, docker_services) -> str:
    """Only the frameworks with response background tasks."""
    return request.param


@pytest.fixture
async def one_connection(framework_url):
    """A client that sends every request over a single connection."""
    limits = httpx.Limits(max_connections=1, max_keepalive_connections=1)
    async with httpx.AsyncClient(
        base_url=framework_url, timeout=30.0, limits=limits
    ) as client:
        yield client


async def _completed(client):
    response = await client.get("/background/completed")
    assert response.status_code == 200
    return response.json()["count"]


class TestBackgroundTasks:
    """A background task does not hold up the connection."""

    async def test_next_request_not_blocked(self, one_connection):
        before = await _completed(one_connection)

        response = await one_connection.get(
            "/background", params={"seconds": TASK_SECONDS})
        assert response.status_code == 200
        assert response.text == "scheduled"

        start = time.monotonic()
        response = await one_connection.get("/health")
        elapsed = time.monotonic() - start
        assert response.status_code == 200
        assert elapsed < TASK_SECONDS / 2, (
            f"request waited {elapsed:.2f}s for the background task")

        # The task still runs to completion.
        deadline = time.monotonic() + TASK_SECONDS + 10
        while await _completed(one_connection) == before:
            assert time.monotonic() < deadline, "background task never finished"
            await asyncio.sleep(0.2)
