"""
Lifespan Protocol Tests

Tests ASGI 3.0 lifespan protocol compliance across frameworks.
"""

import pytest


pytestmark = pytest.mark.lifespan


class TestLifespanStartup:
    """Test lifespan startup handling."""

    async def test_startup_was_called(self, http_client):
        """Startup handler was called."""
        response = await http_client.get("/lifespan/state")
        assert response.status_code == 200
        data = response.json()
        assert data.get("startup_called") is True

    async def test_startup_time_set(self, http_client):
        """Startup time was recorded."""
        response = await http_client.get("/lifespan/state")
        data = response.json()
        assert data.get("startup_time") is not None
        assert isinstance(data["startup_time"], (int, float))

    async def test_startup_custom_data(self, http_client):
        """Custom data set during startup is available."""
        response = await http_client.get("/lifespan/state")
        data = response.json()
        custom_data = data.get("custom_data", {})
        assert custom_data.get("initialized") is True


class TestLifespanState:
    """Test lifespan state persistence."""

    async def test_counter_initial_value(self, http_client):
        """Counter starts at expected initial value."""
        # First get the state to see current counter
        response = await http_client.get("/lifespan/state")
        initial = response.json().get("counter", 0)

        # Increment once
        response = await http_client.get("/lifespan/counter")
        data = response.json()
        assert data["counter"] == initial + 1

    async def test_counter_increments(self, http_client):
        """Counter increments on each request."""
        # Get first value
        response1 = await http_client.get("/lifespan/counter")
        value1 = response1.json()["counter"]

        # Get second value
        response2 = await http_client.get("/lifespan/counter")
        value2 = response2.json()["counter"]

        # Should have incremented
        assert value2 == value1 + 1

    async def test_state_persists_across_requests(self, http_client):
        """State persists across multiple requests."""
        # Make several requests
        values = []
        for _ in range(3):
            response = await http_client.get("/lifespan/counter")
            values.append(response.json()["counter"])

        # Each should be incrementing
        assert values[1] == values[0] + 1
        assert values[2] == values[1] + 1


class TestLifespanStateSharing:
    """Test state sharing between lifespan and request handlers."""

    async def test_lifespan_state_accessible(self, http_client):
        """Lifespan state is accessible from request handlers."""
        response = await http_client.get("/lifespan/state")
        assert response.status_code == 200
        data = response.json()
        # Should have the startup marker
        assert "startup_called" in data

    async def test_state_modifications_persist(self, http_client):
        """Modifications to state persist."""
        # Increment counter
        await http_client.get("/lifespan/counter")

        # Check state still shows startup was called
        response = await http_client.get("/lifespan/state")
        data = response.json()
        assert data.get("startup_called") is True
        # Counter should be > 0
        assert data.get("counter", 0) > 0
