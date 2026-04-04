"""
HTTP Message Type Tests

Tests ASGI 3.0 HTTP request/response message handling.
"""

import pytest


pytestmark = pytest.mark.http


class TestHttpRequestBody:
    """Test HTTP request body handling."""

    async def test_echo_empty_body(self, http_client):
        """Echo endpoint handles empty body."""
        response = await http_client.post("/echo", content=b"")
        assert response.status_code == 200
        assert response.content == b""

    async def test_echo_text_body(self, http_client):
        """Echo endpoint returns text body."""
        body = "Hello, World!"
        response = await http_client.post(
            "/echo",
            content=body,
            headers={"Content-Type": "text/plain"},
        )
        assert response.status_code == 200
        assert response.text == body

    async def test_echo_binary_body(self, http_client):
        """Echo endpoint returns binary body."""
        body = b"\x00\x01\x02\x03\xff\xfe"
        response = await http_client.post(
            "/echo",
            content=body,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert response.status_code == 200
        assert response.content == body

    async def test_echo_json_body(self, http_client):
        """Echo endpoint returns JSON body."""
        body = '{"key": "value", "number": 42}'
        response = await http_client.post(
            "/echo",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        assert response.json() == {"key": "value", "number": 42}

    async def test_echo_large_body(self, http_client, large_body):
        """Echo endpoint handles large body."""
        body = large_body(100 * 1024)  # 100KB
        response = await http_client.post(
            "/echo",
            content=body,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert response.status_code == 200
        assert len(response.content) == len(body)


class TestHttpResponseStatus:
    """Test HTTP response status codes."""

    @pytest.mark.parametrize("code", [200, 201, 204, 301, 400, 404, 500, 503])
    async def test_status_codes(self, http_client, code):
        """Status endpoint returns correct status code."""
        response = await http_client.get(f"/status/{code}")
        assert response.status_code == code

    @pytest.mark.skip(reason="HTTP 100 Continue cannot be a final response per RFC 7231")
    async def test_status_100_continue(self, http_client):
        """Handle 100 status (may not be supported by all frameworks)."""
        # HTTP 100 Continue is an informational response that must be followed
        # by a final response. Using it as a final response is invalid.
        response = await http_client.get("/status/100")
        assert response.status_code in (100, 200)


class TestHttpResponseHeaders:
    """Test HTTP response header handling."""

    async def test_content_type_header(self, http_client):
        """Response has Content-Type header."""
        response = await http_client.get("/scope")
        assert "content-type" in response.headers
        assert "application/json" in response.headers["content-type"]

    async def test_headers_preserved(self, http_client):
        """Custom headers in request are accessible."""
        response = await http_client.get("/headers", headers={"X-Custom": "test123"})
        data = response.json()
        assert data.get("x-custom") == "test123"


class TestHttpDisconnect:
    """Test HTTP disconnect handling."""

    async def test_delay_can_be_cancelled(self, http_client):
        """Long delay can be interrupted (timeout behavior)."""
        import httpx

        # This tests that the server handles client disconnects gracefully
        with pytest.raises(httpx.TimeoutException):
            await http_client.get("/delay?seconds=30", timeout=0.5)


class TestHttpResponseBody:
    """Test HTTP response body handling."""

    async def test_large_response_body(self, http_client):
        """Large response body endpoint works."""
        size = 100 * 1024  # 100KB
        response = await http_client.get(f"/large?size={size}")
        assert response.status_code == 200
        assert len(response.content) == size

    async def test_very_large_response_body(self, http_client):
        """Very large response body endpoint works."""
        size = 1024 * 1024  # 1MB
        response = await http_client.get(f"/large?size={size}")
        assert response.status_code == 200
        assert len(response.content) == size
