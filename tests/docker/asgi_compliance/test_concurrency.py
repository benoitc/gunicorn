#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Concurrency integration tests for ASGI.

Tests concurrent connections, mixed protocols, and load handling.
"""

import asyncio
import json

import pytest

pytestmark = [
    pytest.mark.docker,
    pytest.mark.asgi,
    pytest.mark.concurrency,
    pytest.mark.integration,
]


# ============================================================================
# Concurrent HTTP Requests
# ============================================================================

@pytest.mark.asyncio
class TestConcurrentHTTP:
    """Test concurrent HTTP request handling."""

    async def test_concurrent_simple_requests(self, async_http_client_factory, gunicorn_url):
        """Test many concurrent simple requests."""
        async with await async_http_client_factory() as client:
            async def make_request(i):
                response = await client.get(f"{gunicorn_url}/http/")
                return response.status_code, i

            tasks = [make_request(i) for i in range(50)]
            results = await asyncio.gather(*tasks)

            # All should succeed
            assert all(status == 200 for status, _ in results)

    async def test_concurrent_echo_requests(self, async_http_client_factory, gunicorn_url):
        """Test concurrent echo requests with unique data."""
        async with await async_http_client_factory() as client:
            async def echo_request(i):
                data = f"request_{i}"
                response = await client.post(
                    f"{gunicorn_url}/http/echo",
                    content=data.encode()
                )
                return response.text == data, i

            tasks = [echo_request(i) for i in range(30)]
            results = await asyncio.gather(*tasks)

            # All should echo correctly
            assert all(success for success, _ in results)

    async def test_concurrent_different_endpoints(self, async_http_client_factory, gunicorn_url):
        """Test concurrent requests to different endpoints."""
        async with await async_http_client_factory() as client:
            async def get_root():
                return await client.get(f"{gunicorn_url}/http/")

            async def get_headers():
                return await client.get(f"{gunicorn_url}/http/headers")

            async def get_scope():
                return await client.get(f"{gunicorn_url}/http/scope")

            async def get_health():
                return await client.get(f"{gunicorn_url}/http/health")

            # Mix of different endpoints
            tasks = [
                get_root(), get_headers(), get_scope(), get_health(),
                get_root(), get_headers(), get_scope(), get_health(),
                get_root(), get_headers(), get_scope(), get_health(),
            ]

            results = await asyncio.gather(*tasks)
            assert all(r.status_code == 200 for r in results)

    async def test_concurrent_with_delays(self, async_http_client_factory, gunicorn_url):
        """Test concurrent requests with varying delays."""
        async with await async_http_client_factory(timeout=30.0) as client:
            async def delayed_request(delay_ms):
                response = await client.get(
                    f"{gunicorn_url}/http/delay?ms={delay_ms}"
                )
                return response.status_code == 200

            # Various delays
            delays = [100, 200, 50, 150, 100, 200, 50]
            tasks = [delayed_request(d) for d in delays]
            results = await asyncio.gather(*tasks)

            assert all(results)


# ============================================================================
# Concurrent WebSocket Connections
# ============================================================================

@pytest.mark.asyncio
class TestConcurrentWebSocket:
    """Test concurrent WebSocket connections."""

    async def test_many_concurrent_websockets(self, websocket_connect, gunicorn_url):
        """Test many concurrent WebSocket connections."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/echo"

        async def ws_echo(i):
            async with await websocket_connect(ws_url) as ws:
                message = f"concurrent_{i}"
                await ws.send(message)
                response = await ws.recv()
                return response == message

        tasks = [ws_echo(i) for i in range(20)]
        results = await asyncio.gather(*tasks)

        assert all(results)

    async def test_concurrent_websocket_many_messages(self, websocket_connect, gunicorn_url):
        """Test concurrent WebSocket connections with many messages each."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/echo"

        async def ws_multiple_messages(conn_id):
            async with await websocket_connect(ws_url) as ws:
                for i in range(10):
                    message = f"conn_{conn_id}_msg_{i}"
                    await ws.send(message)
                    response = await ws.recv()
                    if response != message:
                        return False
                return True

        tasks = [ws_multiple_messages(i) for i in range(10)]
        results = await asyncio.gather(*tasks)

        assert all(results)


# ============================================================================
# Mixed Protocol Tests
# ============================================================================

@pytest.mark.asyncio
class TestMixedProtocols:
    """Test mixed HTTP and WebSocket concurrent access."""

    async def test_http_and_websocket_concurrent(
        self, async_http_client_factory, websocket_connect, gunicorn_url
    ):
        """Test concurrent HTTP and WebSocket requests."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/echo"

        async def http_request(client):
            response = await client.get(f"{gunicorn_url}/http/")
            return response.status_code == 200

        async def websocket_echo():
            async with await websocket_connect(ws_url) as ws:
                await ws.send("mixed")
                response = await ws.recv()
                return response == "mixed"

        async with await async_http_client_factory() as client:
            # Interleaved HTTP and WebSocket tasks
            tasks = [
                http_request(client),
                websocket_echo(),
                http_request(client),
                websocket_echo(),
                http_request(client),
                websocket_echo(),
            ]

            results = await asyncio.gather(*tasks)
            assert all(results)

    async def test_streaming_and_http_concurrent(
        self, async_http_client_factory, gunicorn_url
    ):
        """Test concurrent streaming and regular HTTP requests."""
        async with await async_http_client_factory(timeout=60.0) as client:
            async def regular_request():
                response = await client.get(f"{gunicorn_url}/http/")
                return response.status_code == 200

            async def streaming_request():
                async with client.stream(
                    "GET",
                    f"{gunicorn_url}/stream/streaming?chunks=5"
                ) as response:
                    chunks = []
                    async for chunk in response.aiter_bytes():
                        chunks.append(chunk)
                    return len(chunks) > 0

            tasks = [
                regular_request(),
                streaming_request(),
                regular_request(),
                streaming_request(),
                regular_request(),
            ]

            results = await asyncio.gather(*tasks)
            assert all(results)


# ============================================================================
# Connection Reuse Tests
# ============================================================================

@pytest.mark.asyncio
class TestConnectionReuse:
    """Test connection reuse and keep-alive."""

    async def test_many_requests_single_client(
        self, async_http_client_factory, gunicorn_url
    ):
        """Test many sequential requests on single client."""
        async with await async_http_client_factory() as client:
            for i in range(100):
                response = await client.get(f"{gunicorn_url}/http/?iter={i}")
                assert response.status_code == 200

    async def test_keep_alive_stress(self, async_http_client_factory, gunicorn_url):
        """Test keep-alive under stress."""
        async with await async_http_client_factory() as client:
            # Rapid sequential requests
            for _ in range(50):
                tasks = [
                    client.get(f"{gunicorn_url}/http/"),
                    client.get(f"{gunicorn_url}/http/headers"),
                ]
                results = await asyncio.gather(*tasks)
                assert all(r.status_code == 200 for r in results)


# ============================================================================
# Load Tests
# ============================================================================

@pytest.mark.asyncio
class TestLoad:
    """Test load handling."""

    async def test_burst_requests(self, async_http_client_factory, gunicorn_url):
        """Test handling burst of requests."""
        async with await async_http_client_factory() as client:
            async def burst():
                tasks = [
                    client.get(f"{gunicorn_url}/http/")
                    for _ in range(100)
                ]
                return await asyncio.gather(*tasks, return_exceptions=True)

            results = await burst()

            # Count successful responses
            success = sum(
                1 for r in results
                if not isinstance(r, Exception) and r.status_code == 200
            )

            # Most should succeed (allow for some failures under load)
            assert success >= 90, f"Only {success}/100 requests succeeded"

    async def test_sustained_load(self, async_http_client_factory, gunicorn_url):
        """Test sustained load over time."""
        async with await async_http_client_factory() as client:
            success_count = 0
            total = 0

            # 5 iterations of 20 concurrent requests
            for _ in range(5):
                tasks = [
                    client.get(f"{gunicorn_url}/http/")
                    for _ in range(20)
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for r in results:
                    total += 1
                    if not isinstance(r, Exception) and r.status_code == 200:
                        success_count += 1

                # Small delay between batches
                await asyncio.sleep(0.1)

            # High success rate expected
            assert success_count / total >= 0.95


# ============================================================================
# Resource Exhaustion Tests
# ============================================================================

@pytest.mark.asyncio
class TestResourceHandling:
    """Test handling of resource constraints."""

    async def test_many_small_requests(self, async_http_client_factory, gunicorn_url):
        """Test many small requests."""
        async with await async_http_client_factory() as client:
            tasks = [
                client.get(f"{gunicorn_url}/http/health")
                for _ in range(200)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            success = sum(
                1 for r in results
                if not isinstance(r, Exception) and r.status_code == 200
            )
            assert success >= 180  # Allow some failures

    async def test_concurrent_large_responses(
        self, async_http_client_factory, gunicorn_url
    ):
        """Test concurrent large response handling."""
        async with await async_http_client_factory(timeout=60.0) as client:
            async def large_request():
                response = await client.get(
                    f"{gunicorn_url}/stream/large-stream?size=102400"  # 100KB
                )
                return len(response.content) == 102400

            tasks = [large_request() for _ in range(10)]
            results = await asyncio.gather(*tasks)

            assert all(results)


# ============================================================================
# Proxy Concurrency Tests
# ============================================================================

@pytest.mark.asyncio
class TestProxyConcurrency:
    """Test concurrent access through proxy."""

    async def test_proxy_concurrent_http(self, async_http_client_factory, nginx_url):
        """Test concurrent HTTP through proxy."""
        async with await async_http_client_factory() as client:
            tasks = [
                client.get(f"{nginx_url}/http/")
                for _ in range(30)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Allow for some failures in concurrent proxy requests
            successes = [r for r in results if not isinstance(r, Exception) and r.status_code == 200]
            assert len(successes) >= 25  # At least 25/30 should succeed

    async def test_proxy_concurrent_websocket(self, websocket_connect, nginx_url):
        """Test concurrent WebSocket through proxy."""
        ws_url = nginx_url.replace("http://", "ws://") + "/ws/echo"

        async def ws_echo(i):
            async with await websocket_connect(ws_url) as ws:
                await ws.send(f"proxy_{i}")
                response = await ws.recv()
                return response == f"proxy_{i}"

        tasks = [ws_echo(i) for i in range(10)]
        results = await asyncio.gather(*tasks)

        assert all(results)


# ============================================================================
# HTTPS Concurrency Tests
# ============================================================================

@pytest.mark.ssl
@pytest.mark.asyncio
class TestHTTPSConcurrency:
    """Test concurrent HTTPS access."""

    async def test_https_concurrent_http(
        self, async_http_client_factory, gunicorn_ssl_url
    ):
        """Test concurrent HTTPS requests."""
        async with await async_http_client_factory() as client:
            tasks = [
                client.get(f"{gunicorn_ssl_url}/http/")
                for _ in range(20)
            ]
            results = await asyncio.gather(*tasks)

            assert all(r.status_code == 200 for r in results)

    async def test_https_concurrent_websocket(
        self, websocket_connect, gunicorn_ssl_url
    ):
        """Test concurrent WebSocket over HTTPS."""
        ws_url = gunicorn_ssl_url.replace("https://", "wss://") + "/ws/echo"

        async def ws_echo(i):
            async with await websocket_connect(ws_url) as ws:
                await ws.send(f"secure_{i}")
                response = await ws.recv()
                return response == f"secure_{i}"

        tasks = [ws_echo(i) for i in range(10)]
        results = await asyncio.gather(*tasks)

        assert all(results)


# ============================================================================
# Stress Tests
# ============================================================================

@pytest.mark.asyncio
class TestStress:
    """Stress tests for edge cases."""

    async def test_rapid_connect_disconnect(
        self, async_http_client_factory, gunicorn_url
    ):
        """Test rapid connection and disconnection."""
        for _ in range(20):
            async with await async_http_client_factory() as client:
                response = await client.get(f"{gunicorn_url}/http/")
                assert response.status_code == 200

    async def test_rapid_websocket_connect_disconnect(
        self, websocket_connect, gunicorn_url
    ):
        """Test rapid WebSocket connect/disconnect."""
        ws_url = gunicorn_url.replace("http://", "ws://") + "/ws/echo"

        for i in range(20):
            async with await websocket_connect(ws_url) as ws:
                await ws.send(f"rapid_{i}")
                response = await ws.recv()
                assert response == f"rapid_{i}"

    async def test_mixed_success_and_error_paths(
        self, async_http_client_factory, gunicorn_url
    ):
        """Test mixed success and error responses concurrently."""
        async with await async_http_client_factory() as client:
            async def success_request():
                return await client.get(f"{gunicorn_url}/http/")

            async def error_request():
                return await client.get(f"{gunicorn_url}/http/status?code=500")

            async def not_found_request():
                return await client.get(f"{gunicorn_url}/http/nonexistent")

            tasks = [
                success_request(),
                error_request(),
                not_found_request(),
                success_request(),
                error_request(),
                not_found_request(),
            ]

            results = await asyncio.gather(*tasks)

            # Check expected status codes
            expected = [200, 500, 404, 200, 500, 404]
            for result, expected_status in zip(results, expected):
                assert result.status_code == expected_status
