#!/usr/bin/env python
"""
Tests for HTTP/2 with gevent example.

Run with:
    # Start the server first
    docker compose up -d

    # Run tests
    python test_http2_gevent.py

    # Or with pytest
    pytest test_http2_gevent.py -v

Requirements:
    pip install httpx[http2] pytest pytest-asyncio
"""

import asyncio
import sys
import ssl
import socket
import time


def check_server_available(host='localhost', port=8443, timeout=30):
    """Wait for server to become available."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with socket.create_connection((host, port), timeout=2) as sock:
                with ctx.wrap_socket(sock, server_hostname=host):
                    return True
        except (socket.error, ssl.SSLError, OSError):
            time.sleep(1)
    return False


class TestHTTP2Gevent:
    """Test HTTP/2 functionality with gevent worker."""

    BASE_URL = "https://localhost:8443"

    @classmethod
    def setup_class(cls):
        """Check server is available before running tests."""
        if not check_server_available():
            raise RuntimeError(
                "Server not available. Start it with: docker compose up -d"
            )

    def get_client(self):
        """Create HTTP/2 client."""
        import httpx
        return httpx.Client(http2=True, verify=False, timeout=30.0)

    def test_root_endpoint(self):
        """Test basic GET request returns HTTP/2."""
        with self.get_client() as client:
            response = client.get(f"{self.BASE_URL}/")

            assert response.status_code == 200
            assert response.http_version == "HTTP/2"
            assert b"HTTP/2" in response.content or b"Gevent" in response.content

    def test_health_endpoint(self):
        """Test health check endpoint."""
        with self.get_client() as client:
            response = client.get(f"{self.BASE_URL}/health")

            assert response.status_code == 200
            assert response.text == "OK"

    def test_echo_post(self):
        """Test POST echo endpoint."""
        with self.get_client() as client:
            data = b"Hello HTTP/2 with Gevent!"
            response = client.post(f"{self.BASE_URL}/echo", content=data)

            assert response.status_code == 200
            assert response.content == data

    def test_echo_large_body(self):
        """Test POST with large body (tests flow control)."""
        with self.get_client() as client:
            # 100KB of data
            data = b"X" * (100 * 1024)
            response = client.post(f"{self.BASE_URL}/echo", content=data)

            assert response.status_code == 200
            assert len(response.content) == len(data)
            assert response.content == data

    def test_info_endpoint(self):
        """Test JSON info endpoint."""
        with self.get_client() as client:
            response = client.get(f"{self.BASE_URL}/info")

            assert response.status_code == 200
            info = response.json()
            assert info['method'] == 'GET'
            assert info['path'] == '/info'
            assert 'gevent' in info['server'].lower()

    def test_large_response(self):
        """Test large response (1MB) - tests streaming and flow control."""
        with self.get_client() as client:
            response = client.get(f"{self.BASE_URL}/large")

            assert response.status_code == 200
            assert len(response.content) == 1024 * 1024
            assert response.content == b"X" * (1024 * 1024)

    def test_streaming_response(self):
        """Test server-sent events style streaming."""
        with self.get_client() as client:
            response = client.get(f"{self.BASE_URL}/stream")

            assert response.status_code == 200
            assert b"chunk 0" in response.content
            assert b"chunk 9" in response.content

    def test_delay_endpoint(self):
        """Test delayed response."""
        with self.get_client() as client:
            start = time.time()
            response = client.get(f"{self.BASE_URL}/delay?seconds=0.5")
            elapsed = time.time() - start

            assert response.status_code == 200
            assert elapsed >= 0.4  # Allow some tolerance
            assert b"Delayed" in response.content

    def test_not_found(self):
        """Test 404 response."""
        with self.get_client() as client:
            response = client.get(f"{self.BASE_URL}/nonexistent")

            assert response.status_code == 404

    def test_gevent_worker_header(self):
        """Test that gevent worker header is present."""
        with self.get_client() as client:
            response = client.get(f"{self.BASE_URL}/")

            assert response.status_code == 200
            assert response.headers.get('x-worker-type') == 'gevent'


class TestHTTP2Concurrency:
    """Test HTTP/2 multiplexing with concurrent requests."""

    BASE_URL = "https://localhost:8443"

    @classmethod
    def setup_class(cls):
        """Check server is available."""
        if not check_server_available():
            raise RuntimeError("Server not available")

    def test_concurrent_requests_sync(self):
        """Test multiple concurrent requests using threads."""
        import httpx
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def make_request(i):
            with httpx.Client(http2=True, verify=False, timeout=30.0) as client:
                response = client.get(f"{self.BASE_URL}/delay?seconds=0.2")
                return i, response.status_code

        num_requests = 10
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request, i) for i in range(num_requests)]
            results = [f.result() for f in as_completed(futures)]

        assert len(results) == num_requests
        assert all(status == 200 for _, status in results)


class TestHTTP2ConcurrencyAsync:
    """Async tests for HTTP/2 multiplexing."""

    BASE_URL = "https://localhost:8443"

    @classmethod
    def setup_class(cls):
        """Check server is available."""
        if not check_server_available():
            raise RuntimeError("Server not available")

    def test_async_concurrent_requests(self):
        """Test concurrent requests with asyncio."""
        import httpx

        async def run_concurrent():
            async with httpx.AsyncClient(http2=True, verify=False, timeout=30.0) as client:
                # Make 10 concurrent requests
                tasks = [
                    client.get(f"{self.BASE_URL}/delay?seconds=0.2")
                    for _ in range(10)
                ]
                responses = await asyncio.gather(*tasks)
                return responses

        responses = asyncio.run(run_concurrent())

        assert len(responses) == 10
        assert all(r.status_code == 200 for r in responses)
        assert all(r.http_version == "HTTP/2" for r in responses)

    def test_async_multiple_streams(self):
        """Test that multiple concurrent streams work over single HTTP/2 connection.

        This test verifies that HTTP/2 can handle multiple concurrent requests,
        which is the foundation of multiplexing. Performance benefits depend on
        client library implementation and network conditions.
        """
        import httpx

        async def run_test():
            async with httpx.AsyncClient(http2=True, verify=False, timeout=30.0) as client:
                # Send multiple concurrent requests
                tasks = [
                    client.get(f"{self.BASE_URL}/info")
                    for _ in range(10)
                ]
                responses = await asyncio.gather(*tasks)
                return responses

        responses = asyncio.run(run_test())

        # Verify all requests succeeded with HTTP/2
        assert len(responses) == 10
        assert all(r.status_code == 200 for r in responses)
        assert all(r.http_version == "HTTP/2" for r in responses)


def run_basic_test():
    """Run a basic test without pytest."""
    print("Running basic HTTP/2 gevent test...")

    if not check_server_available():
        print("ERROR: Server not available at https://localhost:8443")
        print("Start it with: docker compose up -d")
        return False

    try:
        import httpx
    except ImportError:
        print("ERROR: httpx not installed. Run: pip install httpx[http2]")
        return False

    try:
        with httpx.Client(http2=True, verify=False, timeout=30.0) as client:
            # Test basic request
            print("  Testing root endpoint...", end=" ")
            response = client.get("https://localhost:8443/")
            assert response.status_code == 200
            assert response.http_version == "HTTP/2"
            print("OK")

            # Test echo
            print("  Testing echo endpoint...", end=" ")
            data = b"test data"
            response = client.post("https://localhost:8443/echo", content=data)
            assert response.content == data
            print("OK")

            # Test large response
            print("  Testing large response...", end=" ")
            response = client.get("https://localhost:8443/large")
            assert len(response.content) == 1024 * 1024
            print("OK")

            # Test worker header
            print("  Testing gevent worker...", end=" ")
            response = client.get("https://localhost:8443/")
            assert response.headers.get('x-worker-type') == 'gevent'
            print("OK")

        print("\nAll basic tests passed!")
        return True

    except Exception as e:
        print(f"\nERROR: {e}")
        return False


if __name__ == '__main__':
    # Check if pytest is available
    try:
        import pytest
        # Run with pytest if available
        sys.exit(pytest.main([__file__, '-v']))
    except ImportError:
        # Run basic tests without pytest
        success = run_basic_test()
        sys.exit(0 if success else 1)
