#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Lifespan compliance integration tests for ASGI.

Tests the ASGI lifespan protocol including startup, shutdown,
and state sharing between lifespan and request handlers.
"""

import pytest

pytestmark = [
    pytest.mark.docker,
    pytest.mark.asgi,
    pytest.mark.lifespan,
    pytest.mark.integration,
]


# ============================================================================
# Basic Lifespan Tests
# ============================================================================

class TestLifespanStartup:
    """Test lifespan startup behavior."""

    def test_startup_complete(self, http_client, gunicorn_url):
        """Test that lifespan startup completed."""
        response = http_client.get(f"{gunicorn_url}/lifespan/state")
        assert response.status_code == 200
        data = response.json()
        # Check scope_state which is shared by main_app's lifespan handler
        assert data["scope_state_available"] is True
        assert data["scope_state"]["main_app_started"] is True

    def test_startup_called(self, http_client, gunicorn_url):
        """Test that startup was called (via scope state)."""
        response = http_client.get(f"{gunicorn_url}/lifespan/state")
        assert response.status_code == 200
        data = response.json()
        # Scope state indicates main_app handled lifespan startup
        assert data["scope_state"]["main_app_started"] is True

    def test_startup_time_recorded(self, http_client, gunicorn_url):
        """Test that startup time was recorded."""
        response = http_client.get(f"{gunicorn_url}/lifespan/state")
        assert response.status_code == 200
        data = response.json()
        # Startup time is recorded in scope_state by main_app
        assert data["scope_state"]["startup_time"] is not None

    def test_health_after_startup(self, http_client, gunicorn_url):
        """Test health endpoint returns OK."""
        # The main health endpoint is at /health, lifespan's is at /lifespan/health
        # but lifespan_app's health checks its own module_state which isn't set
        # Use the main app health instead
        response = http_client.get(f"{gunicorn_url}/health")
        assert response.status_code == 200
        assert response.text == "OK"


class TestLifespanInfo:
    """Test lifespan information endpoints."""

    def test_lifespan_info_endpoint(self, http_client, gunicorn_url):
        """Test lifespan info endpoint."""
        response = http_client.get(f"{gunicorn_url}/lifespan/lifespan-info")
        assert response.status_code == 200
        data = response.json()
        assert data["lifespan_supported"] is True
        # scope_state_present indicates lifespan was handled (by main_app)
        assert data["scope_state_present"] is True

    def test_uptime_tracking(self, http_client, gunicorn_url):
        """Test uptime is tracked via main app info endpoint."""
        # The lifespan_app's uptime won't be set since main_app handles lifespan
        # Use the main app's /info endpoint instead
        response = http_client.get(f"{gunicorn_url}/info")
        assert response.status_code == 200
        data = response.json()
        assert data["uptime"] is not None
        assert data["uptime"] >= 0


# ============================================================================
# State Sharing Tests
# ============================================================================

class TestStateSharing:
    """Test state sharing between lifespan and request handlers."""

    def test_state_endpoint(self, http_client, gunicorn_url):
        """Test state endpoint returns state info."""
        response = http_client.get(f"{gunicorn_url}/lifespan/state")
        assert response.status_code == 200
        data = response.json()
        assert "module_state" in data

    def test_request_count_increments(self, http_client, gunicorn_url):
        """Test request count increments across requests."""
        # Make first request
        response1 = http_client.get(f"{gunicorn_url}/lifespan/counter")
        assert response1.status_code == 200
        count1 = response1.json()["counter"]

        # Make second request
        response2 = http_client.get(f"{gunicorn_url}/lifespan/counter")
        assert response2.status_code == 200
        count2 = response2.json()["counter"]

        # Counter should have incremented
        assert count2 > count1



# ============================================================================
# Counter Tests
# ============================================================================

class TestCounter:
    """Test counter functionality for state persistence."""

    def test_counter_endpoint(self, http_client, gunicorn_url):
        """Test counter endpoint."""
        response = http_client.get(f"{gunicorn_url}/lifespan/counter")
        assert response.status_code == 200
        data = response.json()
        assert "counter" in data
        assert "source" in data

    def test_counter_increments_multiple_times(self, http_client, gunicorn_url):
        """Test counter increments across multiple requests."""
        counts = []
        for _ in range(5):
            response = http_client.get(f"{gunicorn_url}/lifespan/counter")
            counts.append(response.json()["counter"])

        # Each count should be greater than the previous
        for i in range(1, len(counts)):
            assert counts[i] > counts[i - 1]


# ============================================================================
# Root and Basic Endpoint Tests
# ============================================================================

class TestBasicEndpoints:
    """Test basic lifespan app endpoints."""

    def test_root_endpoint(self, http_client, gunicorn_url):
        """Test root endpoint."""
        response = http_client.get(f"{gunicorn_url}/lifespan/")
        assert response.status_code == 200
        assert response.text == "Lifespan Test App"

    def test_not_found(self, http_client, gunicorn_url):
        """Test 404 for unknown path."""
        response = http_client.get(f"{gunicorn_url}/lifespan/unknown-path")
        assert response.status_code == 404


# ============================================================================
# Proxy Lifespan Tests
# ============================================================================

class TestProxyLifespan:
    """Test lifespan through nginx proxy."""

    def test_proxy_health(self, http_client, nginx_url):
        """Test health through proxy."""
        response = http_client.get(f"{nginx_url}/health")
        assert response.status_code == 200
        assert response.text == "OK"

    def test_proxy_state(self, http_client, nginx_url):
        """Test state through proxy."""
        response = http_client.get(f"{nginx_url}/lifespan/state")
        assert response.status_code == 200
        data = response.json()
        assert data["scope_state"]["main_app_started"] is True

    def test_proxy_counter(self, http_client, nginx_url):
        """Test counter through proxy."""
        response = http_client.get(f"{nginx_url}/lifespan/counter")
        assert response.status_code == 200
        data = response.json()
        assert "counter" in data


# ============================================================================
# HTTPS Lifespan Tests
# ============================================================================

@pytest.mark.ssl
class TestHTTPSLifespan:
    """Test lifespan over HTTPS."""

    def test_https_health(self, http_client, gunicorn_ssl_url):
        """Test health over HTTPS."""
        response = http_client.get(f"{gunicorn_ssl_url}/health")
        assert response.status_code == 200

    def test_https_state(self, http_client, gunicorn_ssl_url):
        """Test state over HTTPS."""
        response = http_client.get(f"{gunicorn_ssl_url}/lifespan/state")
        assert response.status_code == 200
        data = response.json()
        assert data["scope_state"]["main_app_started"] is True

    def test_https_proxy_health(self, http_client, nginx_ssl_url):
        """Test health through HTTPS proxy."""
        response = http_client.get(f"{nginx_ssl_url}/health")
        assert response.status_code == 200


# ============================================================================
# Concurrent Access Tests
# ============================================================================

@pytest.mark.asyncio
class TestConcurrentLifespan:
    """Test concurrent access to lifespan state."""

    async def test_concurrent_counter_access(self, async_http_client_factory, gunicorn_url):
        """Test concurrent counter access."""
        import asyncio

        async with await async_http_client_factory() as client:
            async def get_counter():
                response = await client.get(f"{gunicorn_url}/lifespan/counter")
                return response.json()["counter"]

            # Run 10 concurrent requests
            tasks = [get_counter() for _ in range(10)]
            results = await asyncio.gather(*tasks)

            # All should be valid integers
            assert all(isinstance(r, int) for r in results)

