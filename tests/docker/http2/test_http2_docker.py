"""HTTP/2 Docker integration tests.

These tests verify HTTP/2 functionality with real connections to gunicorn
running in Docker containers, both directly and through an nginx proxy.
"""

import asyncio
import ssl
import socket

import pytest


# Mark all tests in this module as requiring Docker
pytestmark = [
    pytest.mark.docker,
    pytest.mark.http2,
    pytest.mark.integration,
]


class TestDirectHTTP2Connection:
    """Test direct HTTP/2 connections to gunicorn."""

    def test_simple_get(self, h2_client, gunicorn_url):
        """Test basic GET request over HTTP/2."""
        response = h2_client.get(f"{gunicorn_url}/")
        assert response.status_code == 200
        assert response.http_version == "HTTP/2"
        assert response.text == "Hello HTTP/2!"

    def test_health_endpoint(self, h2_client, gunicorn_url):
        """Test health check endpoint."""
        response = h2_client.get(f"{gunicorn_url}/health")
        assert response.status_code == 200
        assert response.text == "OK"

    def test_post_with_body(self, h2_client, gunicorn_url):
        """Test POST request with body."""
        data = b"test data for echo"
        response = h2_client.post(f"{gunicorn_url}/echo", content=data)
        assert response.status_code == 200
        assert response.content == data

    def test_post_large_body(self, h2_client, gunicorn_url):
        """Test POST with larger body."""
        data = b"X" * 65536  # 64KB
        response = h2_client.post(f"{gunicorn_url}/echo", content=data)
        assert response.status_code == 200
        assert response.content == data
        assert len(response.content) == 65536

    def test_headers_endpoint(self, h2_client, gunicorn_url):
        """Test that custom headers are received."""
        response = h2_client.get(
            f"{gunicorn_url}/headers",
            headers={"X-Custom-Header": "test-value"}
        )
        assert response.status_code == 200
        headers = response.json()
        assert "HTTP_X_CUSTOM_HEADER" in headers
        assert headers["HTTP_X_CUSTOM_HEADER"] == "test-value"

    def test_version_endpoint(self, h2_client, gunicorn_url):
        """Test server protocol version."""
        response = h2_client.get(f"{gunicorn_url}/version")
        assert response.status_code == 200
        # HTTP/2 should report as HTTP/2.0 or similar
        assert "HTTP" in response.text

    def test_large_response(self, h2_client, gunicorn_url):
        """Test receiving large response over HTTP/2."""
        response = h2_client.get(f"{gunicorn_url}/large")
        assert response.status_code == 200
        assert len(response.content) == 1024 * 1024  # 1MB
        assert response.content == b"X" * (1024 * 1024)

    def test_different_methods(self, h2_client, gunicorn_url):
        """Test various HTTP methods."""
        for method in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
            response = h2_client.request(method, f"{gunicorn_url}/method")
            assert response.status_code == 200
            assert response.text == method

    def test_status_codes(self, h2_client, gunicorn_url):
        """Test various HTTP status codes."""
        for code in [200, 201, 400, 404, 500]:
            response = h2_client.get(f"{gunicorn_url}/status?code={code}")
            assert response.status_code == code

    def test_not_found(self, h2_client, gunicorn_url):
        """Test 404 response."""
        response = h2_client.get(f"{gunicorn_url}/nonexistent")
        assert response.status_code == 404


class TestConcurrentStreams:
    """Test HTTP/2 multiplexing with concurrent streams."""

    @pytest.mark.asyncio
    async def test_concurrent_requests(self, async_h2_client, gunicorn_url):
        """Test multiple concurrent requests over single connection."""
        httpx = pytest.importorskip("httpx")

        async with httpx.AsyncClient(http2=True, verify=False, timeout=30.0) as client:
            # Send 10 concurrent requests
            tasks = [
                client.get(f"{gunicorn_url}/")
                for _ in range(10)
            ]
            responses = await asyncio.gather(*tasks)

        assert len(responses) == 10
        assert all(r.status_code == 200 for r in responses)
        assert all(r.http_version == "HTTP/2" for r in responses)
        assert all(r.text == "Hello HTTP/2!" for r in responses)

    @pytest.mark.asyncio
    async def test_concurrent_mixed_requests(self, async_h2_client, gunicorn_url):
        """Test concurrent requests to different endpoints."""
        httpx = pytest.importorskip("httpx")

        async with httpx.AsyncClient(http2=True, verify=False, timeout=30.0) as client:
            tasks = [
                client.get(f"{gunicorn_url}/"),
                client.get(f"{gunicorn_url}/headers"),
                client.get(f"{gunicorn_url}/version"),
                client.post(f"{gunicorn_url}/echo", content=b"test"),
                client.get(f"{gunicorn_url}/health"),
            ]
            responses = await asyncio.gather(*tasks)

        assert len(responses) == 5
        assert all(r.status_code == 200 for r in responses)

    @pytest.mark.asyncio
    async def test_many_concurrent_streams(self, async_h2_client, gunicorn_url):
        """Test many concurrent streams (up to HTTP/2 limit)."""
        httpx = pytest.importorskip("httpx")

        async with httpx.AsyncClient(http2=True, verify=False, timeout=60.0) as client:
            # Send 50 concurrent requests
            tasks = [
                client.get(f"{gunicorn_url}/")
                for _ in range(50)
            ]
            responses = await asyncio.gather(*tasks)

        assert len(responses) == 50
        assert all(r.status_code == 200 for r in responses)


class TestHTTP2BehindProxy:
    """Test HTTP/2 through nginx proxy."""

    def test_simple_get_via_proxy(self, h2_client, nginx_url):
        """Test basic GET through nginx proxy."""
        response = h2_client.get(f"{nginx_url}/")
        assert response.status_code == 200
        assert response.http_version == "HTTP/2"
        assert response.text == "Hello HTTP/2!"

    def test_post_via_proxy(self, h2_client, nginx_url):
        """Test POST through nginx proxy."""
        data = b"proxied data"
        response = h2_client.post(f"{nginx_url}/echo", content=data)
        assert response.status_code == 200
        assert response.content == data

    def test_headers_preserved(self, h2_client, nginx_url):
        """Test that custom headers pass through proxy."""
        response = h2_client.get(
            f"{nginx_url}/headers",
            headers={"X-Custom": "test-value"}
        )
        assert response.status_code == 200
        headers = response.json()
        assert "HTTP_X_CUSTOM" in headers
        assert headers["HTTP_X_CUSTOM"] == "test-value"

    def test_forwarded_headers(self, h2_client, nginx_url):
        """Test that proxy adds forwarded headers."""
        response = h2_client.get(f"{nginx_url}/headers")
        assert response.status_code == 200
        headers = response.json()
        # Nginx should add X-Forwarded-* headers
        assert "HTTP_X_FORWARDED_FOR" in headers
        assert "HTTP_X_FORWARDED_PROTO" in headers
        assert headers["HTTP_X_FORWARDED_PROTO"] == "https"

    def test_large_response_via_proxy(self, h2_client, nginx_url):
        """Test large response through proxy."""
        response = h2_client.get(f"{nginx_url}/large")
        assert response.status_code == 200
        assert len(response.content) == 1024 * 1024

    @pytest.mark.asyncio
    async def test_concurrent_via_proxy(self, async_h2_client, nginx_url):
        """Test concurrent requests through proxy."""
        httpx = pytest.importorskip("httpx")

        async with httpx.AsyncClient(http2=True, verify=False, timeout=30.0) as client:
            tasks = [
                client.get(f"{nginx_url}/")
                for _ in range(10)
            ]
            responses = await asyncio.gather(*tasks)

        assert len(responses) == 10
        assert all(r.status_code == 200 for r in responses)
        assert all(r.http_version == "HTTP/2" for r in responses)


class TestHTTP2Protocol:
    """Test HTTP/2 specific protocol behaviors."""

    def test_alpn_negotiation(self, gunicorn_url):
        """Verify ALPN negotiates h2 protocol."""
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_alpn_protocols(['h2', 'http/1.1'])

        with socket.create_connection(('127.0.0.1', 8443), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname='localhost') as ssock:
                selected = ssock.selected_alpn_protocol()
                assert selected == 'h2', f"Expected h2, got {selected}"

    def test_alpn_http11_fallback(self, gunicorn_url):
        """Test that server accepts HTTP/1.1 via ALPN."""
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_alpn_protocols(['http/1.1'])

        with socket.create_connection(('127.0.0.1', 8443), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname='localhost') as ssock:
                selected = ssock.selected_alpn_protocol()
                assert selected == 'http/1.1', f"Expected http/1.1, got {selected}"

    def test_http11_client_works(self, h1_client, gunicorn_url):
        """Test that HTTP/1.1 client can still connect."""
        response = h1_client.get(f"{gunicorn_url}/")
        assert response.status_code == 200
        assert response.http_version == "HTTP/1.1"
        assert response.text == "Hello HTTP/2!"

    def test_tls_version(self, gunicorn_url):
        """Verify TLS 1.2+ is used."""
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        with socket.create_connection(('127.0.0.1', 8443), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname='localhost') as ssock:
                version = ssock.version()
                assert version in ('TLSv1.2', 'TLSv1.3'), f"Unexpected TLS version: {version}"


class TestHTTP2ErrorHandling:
    """Test HTTP/2 error handling."""

    def test_invalid_path(self, h2_client, gunicorn_url):
        """Test request to non-existent path."""
        response = h2_client.get(f"{gunicorn_url}/does/not/exist")
        assert response.status_code == 404
        assert response.http_version == "HTTP/2"

    def test_server_error(self, h2_client, gunicorn_url):
        """Test server error response."""
        response = h2_client.get(f"{gunicorn_url}/status?code=500")
        assert response.status_code == 500
        assert response.http_version == "HTTP/2"

    @pytest.mark.asyncio
    async def test_connection_reuse_after_error(self, async_h2_client, gunicorn_url):
        """Test that connection is reused after error response."""
        httpx = pytest.importorskip("httpx")

        async with httpx.AsyncClient(http2=True, verify=False, timeout=30.0) as client:
            # First request - error
            r1 = await client.get(f"{gunicorn_url}/status?code=500")
            assert r1.status_code == 500

            # Second request - should work on same connection
            r2 = await client.get(f"{gunicorn_url}/")
            assert r2.status_code == 200
            assert r2.text == "Hello HTTP/2!"


class TestHTTP2Headers:
    """Test HTTP/2 header handling."""

    def test_response_headers(self, h2_client, gunicorn_url):
        """Test that response headers are correctly received."""
        response = h2_client.get(f"{gunicorn_url}/")
        assert "content-type" in response.headers
        assert "content-length" in response.headers
        assert response.headers["x-request-path"] == "/"
        assert response.headers["x-request-method"] == "GET"

    def test_many_request_headers(self, h2_client, gunicorn_url):
        """Test sending many headers."""
        headers = {f"X-Custom-{i}": f"value-{i}" for i in range(20)}
        response = h2_client.get(f"{gunicorn_url}/headers", headers=headers)
        assert response.status_code == 200
        received = response.json()
        for i in range(20):
            key = f"HTTP_X_CUSTOM_{i}"
            assert key in received
            assert received[key] == f"value-{i}"

    def test_header_case_insensitivity(self, h2_client, gunicorn_url):
        """Test HTTP/2 header case handling."""
        response = h2_client.get(
            f"{gunicorn_url}/headers",
            headers={"X-Mixed-Case-Header": "test"}
        )
        assert response.status_code == 200
        # HTTP/2 lowercases headers, but WSGI uppercases them
        headers = response.json()
        assert "HTTP_X_MIXED_CASE_HEADER" in headers


class TestHTTP2Performance:
    """Performance-related HTTP/2 tests."""

    @pytest.mark.asyncio
    async def test_parallel_large_requests(self, async_h2_client, gunicorn_url):
        """Test parallel requests with large responses."""
        httpx = pytest.importorskip("httpx")

        async with httpx.AsyncClient(http2=True, verify=False, timeout=60.0) as client:
            tasks = [
                client.get(f"{gunicorn_url}/large")
                for _ in range(5)
            ]
            responses = await asyncio.gather(*tasks)

        assert len(responses) == 5
        assert all(r.status_code == 200 for r in responses)
        assert all(len(r.content) == 1024 * 1024 for r in responses)

    def test_connection_keepalive(self, h2_client, gunicorn_url):
        """Test that connections are kept alive."""
        # Multiple requests should reuse the same connection
        for _ in range(5):
            response = h2_client.get(f"{gunicorn_url}/")
            assert response.status_code == 200
            assert response.http_version == "HTTP/2"
