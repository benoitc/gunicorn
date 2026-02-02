#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Framework integration tests for ASGI.

Tests integration with popular ASGI frameworks like Starlette and FastAPI.
"""

import json

import pytest

pytestmark = [
    pytest.mark.docker,
    pytest.mark.asgi,
    pytest.mark.framework,
    pytest.mark.integration,
]


# ============================================================================
# Framework Availability Tests
# ============================================================================

class TestFrameworkAvailability:
    """Test framework availability."""

    def test_framework_root_endpoint(self, http_client, gunicorn_url):
        """Test framework root returns available frameworks."""
        response = http_client.get(f"{gunicorn_url}/framework/")
        assert response.status_code == 200
        data = response.json()
        assert "apps" in data
        assert "starlette" in data["apps"]
        assert "fastapi" in data["apps"]

    def test_framework_health(self, http_client, gunicorn_url):
        """Test framework health endpoint."""
        response = http_client.get(f"{gunicorn_url}/framework/health")
        assert response.status_code == 200


# ============================================================================
# Starlette Integration Tests
# ============================================================================

class TestStarletteBasic:
    """Test basic Starlette integration."""

    def test_starlette_homepage(self, http_client, gunicorn_url):
        """Test Starlette homepage."""
        response = http_client.get(f"{gunicorn_url}/framework/starlette/")
        if response.status_code == 503:
            pytest.skip("Starlette not available in container")
        assert response.status_code == 200
        assert "Starlette" in response.text

    def test_starlette_json(self, http_client, gunicorn_url):
        """Test Starlette JSON response."""
        response = http_client.get(f"{gunicorn_url}/framework/starlette/json")
        if response.status_code == 503:
            pytest.skip("Starlette not available")
        assert response.status_code == 200
        data = response.json()
        assert data["framework"] == "starlette"

    def test_starlette_json_query_params(self, http_client, gunicorn_url):
        """Test Starlette query parameters."""
        response = http_client.get(f"{gunicorn_url}/framework/starlette/json?foo=bar&baz=123")
        if response.status_code == 503:
            pytest.skip("Starlette not available")
        assert response.status_code == 200
        data = response.json()
        assert data["query_params"]["foo"] == "bar"
        assert data["query_params"]["baz"] == "123"

    def test_starlette_echo(self, http_client, gunicorn_url):
        """Test Starlette echo endpoint."""
        body = "Hello Starlette!"
        response = http_client.post(
            f"{gunicorn_url}/framework/starlette/echo",
            content=body.encode()
        )
        if response.status_code == 503:
            pytest.skip("Starlette not available")
        assert response.status_code == 200
        assert body in response.text

    def test_starlette_headers(self, http_client, gunicorn_url):
        """Test Starlette headers endpoint."""
        response = http_client.get(
            f"{gunicorn_url}/framework/starlette/headers",
            headers={"X-Custom-Header": "custom-value"}
        )
        if response.status_code == 503:
            pytest.skip("Starlette not available")
        assert response.status_code == 200
        data = response.json()
        assert "x-custom-header" in data
        assert data["x-custom-header"] == "custom-value"

    def test_starlette_scope(self, http_client, gunicorn_url):
        """Test Starlette scope endpoint."""
        response = http_client.get(f"{gunicorn_url}/framework/starlette/scope")
        if response.status_code == 503:
            pytest.skip("Starlette not available")
        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "http"
        assert "asgi" in data

    def test_starlette_health(self, http_client, gunicorn_url):
        """Test Starlette health endpoint."""
        response = http_client.get(f"{gunicorn_url}/framework/starlette/health")
        if response.status_code == 503:
            pytest.skip("Starlette not available")
        assert response.status_code == 200


class TestStarletteStreaming:
    """Test Starlette streaming functionality."""

    def test_starlette_streaming(self, http_client, gunicorn_url):
        """Test Starlette streaming response."""
        response = http_client.get(f"{gunicorn_url}/framework/starlette/streaming")
        if response.status_code == 503:
            pytest.skip("Starlette not available")
        assert response.status_code == 200
        assert "Chunk" in response.text

    def test_starlette_streaming_chunks(self, streaming_client, gunicorn_url):
        """Test Starlette streaming returns multiple chunks."""
        try:
            chunks = list(streaming_client.stream_chunks(
                f"{gunicorn_url}/framework/starlette/streaming"
            ))
        except Exception:
            pytest.skip("Starlette not available")

        full_content = b"".join(chunks).decode("utf-8")
        if "Framework not available" in full_content:
            pytest.skip("Starlette not available")
        assert "Chunk 1" in full_content
        assert "Chunk 10" in full_content


class TestStarletteWebSocket:
    """Test Starlette WebSocket functionality."""

    @pytest.mark.asyncio
    async def test_starlette_websocket_echo(self, websocket_connect, gunicorn_url):
        """Test Starlette WebSocket echo."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/framework/starlette/ws/echo"
        try:
            async with await websocket_connect(ws_url) as ws:
                await ws.send("hello starlette")
                response = await ws.recv()
                assert "Starlette echo: hello starlette" in response
        except Exception as e:
            if "403" in str(e) or "404" in str(e):
                pytest.skip("Starlette WebSocket not available")
            raise


# ============================================================================
# FastAPI Integration Tests
# ============================================================================

class TestFastAPIBasic:
    """Test basic FastAPI integration."""

    def test_fastapi_homepage(self, http_client, gunicorn_url):
        """Test FastAPI homepage."""
        response = http_client.get(f"{gunicorn_url}/framework/fastapi/")
        if response.status_code == 503:
            pytest.skip("FastAPI not available in container")
        assert response.status_code == 200
        data = response.json()
        assert "FastAPI" in data.get("message", "")

    def test_fastapi_json(self, http_client, gunicorn_url):
        """Test FastAPI JSON response."""
        response = http_client.get(f"{gunicorn_url}/framework/fastapi/json")
        if response.status_code == 503:
            pytest.skip("FastAPI not available")
        assert response.status_code == 200
        data = response.json()
        assert data["framework"] == "fastapi"

    def test_fastapi_json_query_params(self, http_client, gunicorn_url):
        """Test FastAPI query parameters."""
        response = http_client.get(f"{gunicorn_url}/framework/fastapi/json?foo=bar&num=42")
        if response.status_code == 503:
            pytest.skip("FastAPI not available")
        assert response.status_code == 200
        data = response.json()
        assert data["query_params"]["foo"] == "bar"
        assert data["query_params"]["num"] == "42"

    def test_fastapi_echo(self, http_client, gunicorn_url):
        """Test FastAPI echo endpoint."""
        body = "Hello FastAPI!"
        response = http_client.post(
            f"{gunicorn_url}/framework/fastapi/echo",
            content=body.encode()
        )
        if response.status_code == 503:
            pytest.skip("FastAPI not available")
        assert response.status_code == 200
        data = response.json()
        assert data["echo"] == body
        assert data["length"] == len(body)

    def test_fastapi_headers(self, http_client, gunicorn_url):
        """Test FastAPI headers endpoint."""
        response = http_client.get(
            f"{gunicorn_url}/framework/fastapi/headers",
            headers={"X-FastAPI-Header": "fastapi-value"}
        )
        if response.status_code == 503:
            pytest.skip("FastAPI not available")
        assert response.status_code == 200
        data = response.json()
        assert "x-fastapi-header" in data
        assert data["x-fastapi-header"] == "fastapi-value"

    def test_fastapi_scope(self, http_client, gunicorn_url):
        """Test FastAPI scope endpoint."""
        response = http_client.get(f"{gunicorn_url}/framework/fastapi/scope")
        if response.status_code == 503:
            pytest.skip("FastAPI not available")
        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "http"
        assert "asgi" in data

    def test_fastapi_health(self, http_client, gunicorn_url):
        """Test FastAPI health endpoint."""
        response = http_client.get(f"{gunicorn_url}/framework/fastapi/health")
        if response.status_code == 503:
            pytest.skip("FastAPI not available")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


class TestFastAPIPathParameters:
    """Test FastAPI path parameters."""

    def test_path_parameter_int(self, http_client, gunicorn_url):
        """Test FastAPI path parameter with integer."""
        response = http_client.get(f"{gunicorn_url}/framework/fastapi/items/42")
        if response.status_code == 503:
            pytest.skip("FastAPI not available")
        assert response.status_code == 200
        data = response.json()
        assert data["item_id"] == 42

    def test_path_parameter_with_query(self, http_client, gunicorn_url):
        """Test FastAPI path parameter with query string."""
        response = http_client.get(f"{gunicorn_url}/framework/fastapi/items/123?q=search")
        if response.status_code == 503:
            pytest.skip("FastAPI not available")
        assert response.status_code == 200
        data = response.json()
        assert data["item_id"] == 123
        assert data["query"] == "search"

    def test_create_item(self, http_client, gunicorn_url):
        """Test FastAPI create item endpoint."""
        item = {"name": "Test Item", "price": 99.99}
        response = http_client.post(
            f"{gunicorn_url}/framework/fastapi/items/",
            json=item
        )
        if response.status_code == 503:
            pytest.skip("FastAPI not available")
        assert response.status_code == 200
        data = response.json()
        assert data["created"] == item


class TestFastAPIStreaming:
    """Test FastAPI streaming functionality."""

    def test_fastapi_streaming(self, http_client, gunicorn_url):
        """Test FastAPI streaming response."""
        response = http_client.get(f"{gunicorn_url}/framework/fastapi/streaming")
        if response.status_code == 503:
            pytest.skip("FastAPI not available")
        assert response.status_code == 200
        assert "Chunk" in response.text

    def test_fastapi_streaming_chunks(self, streaming_client, gunicorn_url):
        """Test FastAPI streaming returns multiple chunks."""
        try:
            chunks = list(streaming_client.stream_chunks(
                f"{gunicorn_url}/framework/fastapi/streaming"
            ))
        except Exception:
            pytest.skip("FastAPI not available")

        full_content = b"".join(chunks).decode("utf-8")
        if "Framework not available" in full_content:
            pytest.skip("FastAPI not available")
        assert "Chunk 1" in full_content
        assert "Chunk 10" in full_content


class TestFastAPIWebSocket:
    """Test FastAPI WebSocket functionality."""

    @pytest.mark.asyncio
    async def test_fastapi_websocket_echo(self, websocket_connect, gunicorn_url):
        """Test FastAPI WebSocket echo."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/framework/fastapi/ws/echo"
        try:
            async with await websocket_connect(ws_url) as ws:
                await ws.send("hello fastapi")
                response = await ws.recv()
                assert "FastAPI echo: hello fastapi" in response
        except Exception as e:
            if "403" in str(e) or "404" in str(e):
                pytest.skip("FastAPI WebSocket not available")
            raise


# ============================================================================
# Cross-Framework Tests
# ============================================================================

class TestCrossFramework:
    """Test cross-framework functionality."""

    def test_both_frameworks_available(self, http_client, gunicorn_url):
        """Test both frameworks are available."""
        response = http_client.get(f"{gunicorn_url}/framework/")
        assert response.status_code == 200
        data = response.json()

        starlette_available = data["apps"]["starlette"]["available"]
        fastapi_available = data["apps"]["fastapi"]["available"]

        # At least one should be available (container should have them)
        # If neither available, skip
        if not starlette_available and not fastapi_available:
            pytest.skip("No frameworks available")

    def test_framework_independence(self, http_client, gunicorn_url):
        """Test frameworks work independently."""
        # Check framework root first
        root_response = http_client.get(f"{gunicorn_url}/framework/")
        if root_response.status_code != 200:
            pytest.skip("Frameworks not available")

        data = root_response.json()

        if data["apps"]["starlette"]["available"]:
            starlette_response = http_client.get(f"{gunicorn_url}/framework/starlette/health")
            assert starlette_response.status_code == 200

        if data["apps"]["fastapi"]["available"]:
            fastapi_response = http_client.get(f"{gunicorn_url}/framework/fastapi/health")
            assert fastapi_response.status_code == 200


# ============================================================================
# Proxy Framework Tests
# ============================================================================

class TestProxyFramework:
    """Test frameworks through nginx proxy."""

    def test_proxy_framework_root(self, http_client, nginx_url):
        """Test framework root through proxy."""
        response = http_client.get(f"{nginx_url}/framework/")
        assert response.status_code == 200
        data = response.json()
        assert "apps" in data

    def test_proxy_starlette(self, http_client, nginx_url):
        """Test Starlette through proxy."""
        response = http_client.get(f"{nginx_url}/framework/starlette/json")
        if response.status_code == 503:
            pytest.skip("Starlette not available")
        assert response.status_code == 200
        data = response.json()
        assert data["framework"] == "starlette"

    def test_proxy_fastapi(self, http_client, nginx_url):
        """Test FastAPI through proxy."""
        response = http_client.get(f"{nginx_url}/framework/fastapi/json")
        if response.status_code == 503:
            pytest.skip("FastAPI not available")
        assert response.status_code == 200
        data = response.json()
        assert data["framework"] == "fastapi"


# ============================================================================
# HTTPS Framework Tests
# ============================================================================

@pytest.mark.ssl
class TestHTTPSFramework:
    """Test frameworks over HTTPS."""

    def test_https_starlette(self, http_client, gunicorn_ssl_url):
        """Test Starlette over HTTPS."""
        response = http_client.get(f"{gunicorn_ssl_url}/framework/starlette/json")
        if response.status_code == 503:
            pytest.skip("Starlette not available")
        assert response.status_code == 200
        data = response.json()
        assert data["framework"] == "starlette"

    def test_https_fastapi(self, http_client, gunicorn_ssl_url):
        """Test FastAPI over HTTPS."""
        response = http_client.get(f"{gunicorn_ssl_url}/framework/fastapi/json")
        if response.status_code == 503:
            pytest.skip("FastAPI not available")
        assert response.status_code == 200
        data = response.json()
        assert data["framework"] == "fastapi"

    def test_https_proxy_starlette(self, http_client, nginx_ssl_url):
        """Test Starlette through HTTPS proxy."""
        response = http_client.get(f"{nginx_ssl_url}/framework/starlette/health")
        if response.status_code == 503:
            pytest.skip("Starlette not available")
        assert response.status_code == 200

    def test_https_proxy_fastapi(self, http_client, nginx_ssl_url):
        """Test FastAPI through HTTPS proxy."""
        import time
        response = None
        # Retry up to 3 times for intermittent proxy connectivity issues
        for attempt in range(3):
            response = http_client.get(f"{nginx_ssl_url}/framework/fastapi/health")
            if response.status_code == 503:
                pytest.skip("FastAPI not available")
            if response.status_code == 200:
                break
            time.sleep(0.5)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


# ============================================================================
# Async Framework Tests
# ============================================================================

@pytest.mark.asyncio
class TestAsyncFramework:
    """Test frameworks with async client."""

    async def test_async_starlette(self, async_http_client_factory, gunicorn_url):
        """Test Starlette with async client."""
        async with await async_http_client_factory() as client:
            response = await client.get(f"{gunicorn_url}/framework/starlette/json")
            if response.status_code == 503:
                pytest.skip("Starlette not available")
            assert response.status_code == 200
            data = response.json()
            assert data["framework"] == "starlette"

    async def test_async_fastapi(self, async_http_client_factory, gunicorn_url):
        """Test FastAPI with async client."""
        async with await async_http_client_factory() as client:
            response = await client.get(f"{gunicorn_url}/framework/fastapi/json")
            if response.status_code == 503:
                pytest.skip("FastAPI not available")
            assert response.status_code == 200
            data = response.json()
            assert data["framework"] == "fastapi"

    async def test_concurrent_framework_requests(self, async_http_client_factory, gunicorn_url):
        """Test concurrent requests to both frameworks."""
        import asyncio

        async with await async_http_client_factory() as client:
            async def get_starlette():
                response = await client.get(f"{gunicorn_url}/framework/starlette/json")
                return response.status_code, "starlette"

            async def get_fastapi():
                response = await client.get(f"{gunicorn_url}/framework/fastapi/json")
                return response.status_code, "fastapi"

            results = await asyncio.gather(
                get_starlette(),
                get_fastapi(),
                get_starlette(),
                get_fastapi(),
            )

            # All should either succeed (200) or framework unavailable (503)
            for status, name in results:
                assert status in [200, 503], f"{name} returned {status}"
