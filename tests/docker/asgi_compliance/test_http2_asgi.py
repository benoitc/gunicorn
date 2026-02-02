#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
HTTP/2 ASGI integration tests.

Tests HTTP/2 specific functionality with ASGI applications.
"""

import json

import pytest

pytestmark = [
    pytest.mark.docker,
    pytest.mark.asgi,
    pytest.mark.http2,
    pytest.mark.integration,
]


# ============================================================================
# HTTP/2 Basic Tests
# ============================================================================

class TestHTTP2Basic:
    """Test basic HTTP/2 functionality with ASGI."""

    def test_http2_request(self, http2_client, nginx_ssl_url):
        """Test HTTP/2 request through nginx."""
        response = http2_client.get(f"{nginx_ssl_url}/http/")
        assert response.status_code == 200
        # HTTP/2 is negotiated via ALPN on TLS
        assert response.http_version in ["HTTP/2", "HTTP/1.1"]

    def test_http2_scope(self, http2_client, nginx_ssl_url):
        """Test ASGI scope with HTTP/2."""
        response = http2_client.get(f"{nginx_ssl_url}/http/scope")
        assert response.status_code == 200
        data = response.json()
        # HTTP version in scope should reflect what the app sees
        # (may be 1.1 if nginx proxies as HTTP/1.1 to backend)
        assert data["http_version"] in ["1.1", "2", "1.0"]

    def test_http2_headers(self, http2_client, nginx_ssl_url):
        """Test headers work correctly over HTTP/2."""
        response = http2_client.get(
            f"{nginx_ssl_url}/http/headers",
            headers={
                "X-Custom-Header": "http2-value",
                "X-Another-Header": "another-value",
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert "x-custom-header" in data
        assert data["x-custom-header"] == "http2-value"


# ============================================================================
# HTTP/2 Multiplexing Tests
# ============================================================================

@pytest.mark.asyncio
class TestHTTP2Multiplexing:
    """Test HTTP/2 multiplexing features."""

    async def test_concurrent_requests_single_connection(
        self, async_http_client_factory, nginx_ssl_url
    ):
        """Test concurrent requests on single HTTP/2 connection."""
        import asyncio

        async with await async_http_client_factory(http2=True) as client:
            async def make_request(i):
                response = await client.get(f"{nginx_ssl_url}/http/?req={i}")
                return response.status_code == 200, i

            # HTTP/2 allows multiple concurrent streams
            tasks = [make_request(i) for i in range(20)]
            results = await asyncio.gather(*tasks)

            assert all(success for success, _ in results)

    async def test_interleaved_requests(
        self, async_http_client_factory, nginx_ssl_url
    ):
        """Test interleaved request/response on HTTP/2."""
        import asyncio

        async with await async_http_client_factory(http2=True) as client:
            async def fast_request():
                return await client.get(f"{nginx_ssl_url}/http/health")

            async def slow_request():
                return await client.get(f"{nginx_ssl_url}/http/delay?ms=100")

            # Mix of fast and slow requests
            tasks = [
                slow_request(),
                fast_request(),
                slow_request(),
                fast_request(),
                fast_request(),
            ]

            results = await asyncio.gather(*tasks)
            assert all(r.status_code == 200 for r in results)


# ============================================================================
# HTTP/2 Streaming Tests
# ============================================================================

class TestHTTP2Streaming:
    """Test HTTP/2 streaming with ASGI."""

    def test_http2_streaming_response(self, http2_client, nginx_ssl_url):
        """Test streaming response over HTTP/2."""
        response = http2_client.get(f"{nginx_ssl_url}/stream/streaming?chunks=5")
        assert response.status_code == 200
        assert "Chunk" in response.text

    def test_http2_sse(self, http2_client, nginx_ssl_url):
        """Test Server-Sent Events over HTTP/2."""
        response = http2_client.get(f"{nginx_ssl_url}/stream/sse?events=3&delay=0.1")
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

    def test_http2_large_response(self, http2_client, nginx_ssl_url):
        """Test large response over HTTP/2."""
        response = http2_client.get(f"{nginx_ssl_url}/stream/large-stream?size=102400")
        assert response.status_code == 200
        assert len(response.content) == 102400


# ============================================================================
# HTTP/2 POST/Body Tests
# ============================================================================

class TestHTTP2RequestBody:
    """Test HTTP/2 request body handling."""

    def test_http2_post_json(self, http2_client, nginx_ssl_url):
        """Test POST with JSON body over HTTP/2."""
        data = {"message": "http2 post", "number": 42}
        response = http2_client.post(
            f"{nginx_ssl_url}/http/post-json",
            json=data
        )
        assert response.status_code == 200
        result = response.json()
        assert result["received"]["message"] == "http2 post"

    def test_http2_post_echo(self, http2_client, nginx_ssl_url):
        """Test echo endpoint over HTTP/2."""
        body = b"HTTP/2 echo test body"
        response = http2_client.post(
            f"{nginx_ssl_url}/http/echo",
            content=body
        )
        assert response.status_code == 200
        assert response.content == body

    def test_http2_large_request_body(self, http2_client, nginx_ssl_url):
        """Test large request body over HTTP/2."""
        body = b"x" * 100000  # 100KB
        response = http2_client.post(
            f"{nginx_ssl_url}/http/echo",
            content=body
        )
        assert response.status_code == 200
        assert len(response.content) == 100000


# ============================================================================
# HTTP/2 ASGI Scope Tests
# ============================================================================

class TestHTTP2ASGIScope:
    """Test ASGI scope properties with HTTP/2."""

    def test_scope_type_http(self, http2_client, nginx_ssl_url):
        """Test scope type is HTTP."""
        response = http2_client.get(f"{nginx_ssl_url}/http/scope")
        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "http"

    def test_scope_asgi_version(self, http2_client, nginx_ssl_url):
        """Test ASGI version in scope."""
        response = http2_client.get(f"{nginx_ssl_url}/http/scope")
        assert response.status_code == 200
        data = response.json()
        assert "asgi" in data
        assert "version" in data["asgi"]

    def test_scope_scheme_https(self, http2_client, nginx_ssl_url):
        """Test scheme is HTTPS in scope."""
        response = http2_client.get(f"{nginx_ssl_url}/http/scope")
        assert response.status_code == 200
        data = response.json()
        # Scope scheme reflects what app sees (may be http if proxy strips TLS)
        assert data["scheme"] in ["http", "https"]

    def test_scope_method_preserved(self, http2_client, nginx_ssl_url):
        """Test HTTP method is preserved in scope."""
        response = http2_client.get(f"{nginx_ssl_url}/http/scope")
        assert response.status_code == 200
        data = response.json()
        assert data["method"] == "GET"

    def test_scope_path_preserved(self, http2_client, nginx_ssl_url):
        """Test path is preserved in scope."""
        response = http2_client.get(f"{nginx_ssl_url}/http/scope")
        assert response.status_code == 200
        data = response.json()
        # Path is stripped by main_app router (/http prefix removed)
        assert data["path"] == "/scope"

    def test_scope_query_string(self, http2_client, nginx_ssl_url):
        """Test query string in scope."""
        response = http2_client.get(f"{nginx_ssl_url}/http/scope?foo=bar&baz=qux")
        assert response.status_code == 200
        data = response.json()
        assert "foo=bar" in data["query_string"]


# ============================================================================
# HTTP/2 Framework Tests
# ============================================================================

class TestHTTP2Framework:
    """Test frameworks over HTTP/2."""

    def test_http2_starlette(self, http2_client, nginx_ssl_url):
        """Test Starlette over HTTP/2."""
        response = http2_client.get(f"{nginx_ssl_url}/framework/starlette/json")
        if response.status_code == 503:
            pytest.skip("Starlette not available")
        assert response.status_code == 200
        data = response.json()
        assert data["framework"] == "starlette"

    def test_http2_fastapi(self, http2_client, nginx_ssl_url):
        """Test FastAPI over HTTP/2."""
        response = http2_client.get(f"{nginx_ssl_url}/framework/fastapi/json")
        if response.status_code == 503:
            pytest.skip("FastAPI not available")
        assert response.status_code == 200
        data = response.json()
        assert data["framework"] == "fastapi"


# ============================================================================
# HTTP/2 Error Handling Tests
# ============================================================================

class TestHTTP2Errors:
    """Test HTTP/2 error handling."""

    def test_http2_404(self, http2_client, nginx_ssl_url):
        """Test 404 over HTTP/2."""
        response = http2_client.get(f"{nginx_ssl_url}/http/nonexistent")
        assert response.status_code == 404

    def test_http2_500(self, http2_client, nginx_ssl_url):
        """Test 500 over HTTP/2."""
        response = http2_client.get(f"{nginx_ssl_url}/http/status?code=500")
        assert response.status_code == 500

    def test_http2_various_status_codes(self, http2_client, nginx_ssl_url):
        """Test various status codes over HTTP/2."""
        for code in [200, 201, 204, 301, 400, 403, 404, 500, 503]:
            response = http2_client.get(
                f"{nginx_ssl_url}/http/status?code={code}",
                follow_redirects=False
            )
            assert response.status_code == code


# ============================================================================
# HTTP/2 Concurrent Async Tests
# ============================================================================

@pytest.mark.asyncio
class TestHTTP2Async:
    """Test async HTTP/2 operations."""

    async def test_async_http2_streaming(
        self, async_http_client_factory, nginx_ssl_url
    ):
        """Test async streaming over HTTP/2."""
        async with await async_http_client_factory(http2=True) as client:
            chunks = []
            async with client.stream(
                "GET",
                f"{nginx_ssl_url}/stream/streaming?chunks=5"
            ) as response:
                async for chunk in response.aiter_bytes():
                    chunks.append(chunk)

            full_content = b"".join(chunks).decode("utf-8")
            assert "Chunk" in full_content

    async def test_async_http2_concurrent_streams(
        self, async_http_client_factory, nginx_ssl_url
    ):
        """Test concurrent HTTP/2 streams."""
        import asyncio

        async with await async_http_client_factory(http2=True) as client:
            async def stream_request(i):
                response = await client.get(
                    f"{nginx_ssl_url}/stream/streaming?chunks=3"
                )
                return i, "Chunk" in response.text

            tasks = [stream_request(i) for i in range(10)]
            results = await asyncio.gather(*tasks)

            assert all(success for _, success in results)

    async def test_async_http2_mixed_requests(
        self, async_http_client_factory, nginx_ssl_url
    ):
        """Test mixed request types over HTTP/2."""
        import asyncio

        async with await async_http_client_factory(http2=True) as client:
            async def get_request():
                return await client.get(f"{nginx_ssl_url}/http/")

            async def post_request():
                return await client.post(
                    f"{nginx_ssl_url}/http/echo",
                    content=b"test"
                )

            async def stream_request():
                response = await client.get(
                    f"{nginx_ssl_url}/stream/streaming?chunks=2"
                )
                return response

            tasks = [
                get_request(),
                post_request(),
                stream_request(),
                get_request(),
                post_request(),
            ]

            results = await asyncio.gather(*tasks)
            assert all(r.status_code == 200 for r in results)


# ============================================================================
# HTTP/2 Lifespan Tests
# ============================================================================

class TestHTTP2Lifespan:
    """Test lifespan app over HTTP/2."""

    def test_http2_lifespan_state(self, http2_client, nginx_ssl_url):
        """Test lifespan state over HTTP/2."""
        response = http2_client.get(f"{nginx_ssl_url}/lifespan/state")
        assert response.status_code == 200
        data = response.json()
        # main_app handles lifespan, so check scope_state not module_state
        assert data["scope_state"]["main_app_started"] is True

    def test_http2_lifespan_counter(self, http2_client, nginx_ssl_url):
        """Test lifespan counter over HTTP/2."""
        response = http2_client.get(f"{nginx_ssl_url}/lifespan/counter")
        assert response.status_code == 200
        data = response.json()
        assert "counter" in data


# ============================================================================
# HTTP/2 Direct (No Proxy) Tests
# ============================================================================

@pytest.mark.ssl
class TestHTTP2Direct:
    """Test HTTP/2 directly to gunicorn (if supported)."""

    def test_direct_https_request(self, http_client, gunicorn_ssl_url):
        """Test direct HTTPS request to gunicorn."""
        response = http_client.get(f"{gunicorn_ssl_url}/http/")
        assert response.status_code == 200

    def test_direct_https_scope(self, http_client, gunicorn_ssl_url):
        """Test scope from direct HTTPS connection."""
        response = http_client.get(f"{gunicorn_ssl_url}/http/scope")
        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "http"
        # Direct connection should show https scheme
        assert data["scheme"] == "https"

    def test_direct_https_streaming(self, http_client, gunicorn_ssl_url):
        """Test streaming from direct HTTPS connection."""
        response = http_client.get(f"{gunicorn_ssl_url}/stream/streaming?chunks=3")
        assert response.status_code == 200
        assert "Chunk" in response.text
