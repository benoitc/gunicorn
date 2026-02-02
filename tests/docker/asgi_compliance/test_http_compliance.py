#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
HTTP compliance integration tests for ASGI.

Tests HTTP request/response handling, headers, methods, status codes,
and ASGI scope correctness through actual HTTP requests.
"""

import json

import pytest

pytestmark = [
    pytest.mark.docker,
    pytest.mark.asgi,
    pytest.mark.integration,
]


# ============================================================================
# Basic HTTP Request/Response Tests
# ============================================================================

class TestBasicHTTPRequests:
    """Test basic HTTP request/response functionality."""

    def test_root_endpoint(self, http_client, gunicorn_url):
        """Test root endpoint returns expected response."""
        response = http_client.get(f"{gunicorn_url}/")
        assert response.status_code == 200
        assert "ASGI Compliance Testbed" in response.text

    def test_health_endpoint(self, http_client, gunicorn_url):
        """Test health check endpoint."""
        response = http_client.get(f"{gunicorn_url}/health")
        assert response.status_code == 200
        assert response.text == "OK"

    def test_http_app_root(self, http_client, gunicorn_url):
        """Test HTTP app root endpoint."""
        response = http_client.get(f"{gunicorn_url}/http/")
        assert response.status_code == 200
        assert response.text == "Hello, ASGI!"

    def test_not_found(self, http_client, gunicorn_url):
        """Test 404 response for unknown paths."""
        response = http_client.get(f"{gunicorn_url}/http/nonexistent")
        assert response.status_code == 404


class TestHTTPMethods:
    """Test various HTTP methods."""

    def test_get_method(self, http_client, gunicorn_url):
        """Test GET method."""
        response = http_client.get(f"{gunicorn_url}/http/method")
        assert response.status_code == 200
        data = response.json()
        assert data["method"] == "GET"

    def test_post_method(self, http_client, gunicorn_url):
        """Test POST method."""
        response = http_client.post(f"{gunicorn_url}/http/method")
        assert response.status_code == 200
        data = response.json()
        assert data["method"] == "POST"

    def test_put_method(self, http_client, gunicorn_url):
        """Test PUT method."""
        response = http_client.put(f"{gunicorn_url}/http/method")
        assert response.status_code == 200
        data = response.json()
        assert data["method"] == "PUT"

    def test_delete_method(self, http_client, gunicorn_url):
        """Test DELETE method."""
        response = http_client.delete(f"{gunicorn_url}/http/method")
        assert response.status_code == 200
        data = response.json()
        assert data["method"] == "DELETE"

    def test_patch_method(self, http_client, gunicorn_url):
        """Test PATCH method."""
        response = http_client.patch(f"{gunicorn_url}/http/method")
        assert response.status_code == 200
        data = response.json()
        assert data["method"] == "PATCH"

    def test_head_method(self, http_client, gunicorn_url):
        """Test HEAD method returns no body."""
        response = http_client.head(f"{gunicorn_url}/http/")
        assert response.status_code == 200
        assert response.content == b""

    def test_options_method(self, http_client, gunicorn_url):
        """Test OPTIONS method."""
        response = http_client.options(f"{gunicorn_url}/http/method")
        assert response.status_code == 200
        data = response.json()
        assert data["method"] == "OPTIONS"


class TestHTTPStatusCodes:
    """Test HTTP status code responses."""

    @pytest.mark.parametrize("status_code", [
        200, 201, 202, 204, 301, 302, 304, 400, 401, 403, 404, 405, 500, 502, 503
    ])
    def test_status_codes(self, http_client, gunicorn_url, status_code):
        """Test various HTTP status codes."""
        response = http_client.get(f"{gunicorn_url}/http/status?code={status_code}")
        assert response.status_code == status_code

    def test_invalid_status_code(self, http_client, gunicorn_url):
        """Test invalid status code returns 400."""
        response = http_client.get(f"{gunicorn_url}/http/status?code=999")
        assert response.status_code == 400


# ============================================================================
# Request/Response Body Tests
# ============================================================================

class TestRequestBody:
    """Test request body handling."""

    def test_echo_small_body(self, http_client, gunicorn_url):
        """Test echoing small request body."""
        body = b"Hello, World!"
        response = http_client.post(f"{gunicorn_url}/http/echo", content=body)
        assert response.status_code == 200
        assert response.content == body

    def test_echo_large_body(self, http_client, gunicorn_url):
        """Test echoing large request body (1MB)."""
        body = b"x" * (1024 * 1024)
        response = http_client.post(f"{gunicorn_url}/http/echo", content=body)
        assert response.status_code == 200
        assert len(response.content) == len(body)
        assert response.content == body

    def test_echo_empty_body(self, http_client, gunicorn_url):
        """Test echoing empty request body."""
        response = http_client.post(f"{gunicorn_url}/http/echo", content=b"")
        assert response.status_code == 200
        assert response.content == b""

    def test_post_json(self, http_client, gunicorn_url):
        """Test posting and receiving JSON."""
        data = {"name": "test", "value": 123, "nested": {"key": "value"}}
        response = http_client.post(
            f"{gunicorn_url}/http/post-json",
            json=data
        )
        assert response.status_code == 200
        result = response.json()
        assert result["received"] == data
        assert result["type"] == "dict"

    def test_post_json_array(self, http_client, gunicorn_url):
        """Test posting JSON array."""
        data = [1, 2, 3, "four", {"five": 5}]
        response = http_client.post(
            f"{gunicorn_url}/http/post-json",
            json=data
        )
        assert response.status_code == 200
        result = response.json()
        assert result["received"] == data
        assert result["type"] == "list"


class TestResponseBody:
    """Test response body handling."""

    def test_large_response(self, http_client, gunicorn_url):
        """Test receiving large response (1MB)."""
        response = http_client.get(f"{gunicorn_url}/http/large?size=1048576")
        assert response.status_code == 200
        assert len(response.content) == 1048576

    def test_large_response_custom_size(self, http_client, gunicorn_url):
        """Test receiving custom size response."""
        size = 500000
        response = http_client.get(f"{gunicorn_url}/http/large?size={size}")
        assert response.status_code == 200
        assert len(response.content) == size


# ============================================================================
# Header Tests
# ============================================================================

class TestRequestHeaders:
    """Test request header handling."""

    def test_headers_received(self, http_client, gunicorn_url):
        """Test that request headers are received correctly."""
        response = http_client.get(
            f"{gunicorn_url}/http/headers",
            headers={
                "X-Custom-Header": "custom-value",
                "X-Another-Header": "another-value",
            }
        )
        assert response.status_code == 200
        headers = response.json()
        assert headers.get("x-custom-header") == "custom-value"
        assert headers.get("x-another-header") == "another-value"

    def test_host_header(self, http_client, gunicorn_url):
        """Test Host header is received."""
        response = http_client.get(f"{gunicorn_url}/http/headers")
        assert response.status_code == 200
        headers = response.json()
        assert "host" in headers

    def test_user_agent_header(self, http_client, gunicorn_url):
        """Test User-Agent header is received."""
        response = http_client.get(
            f"{gunicorn_url}/http/headers",
            headers={"User-Agent": "TestClient/1.0"}
        )
        assert response.status_code == 200
        headers = response.json()
        assert headers.get("user-agent") == "TestClient/1.0"

    def test_content_type_header(self, http_client, gunicorn_url):
        """Test Content-Type header on POST."""
        response = http_client.post(
            f"{gunicorn_url}/http/headers",
            content=b"test",
            headers={"Content-Type": "application/octet-stream"}
        )
        assert response.status_code == 200
        headers = response.json()
        assert headers.get("content-type") == "application/octet-stream"


class TestResponseHeaders:
    """Test response header handling."""

    def test_content_type_response(self, http_client, gunicorn_url):
        """Test Content-Type in response."""
        response = http_client.get(f"{gunicorn_url}/http/headers")
        assert "application/json" in response.headers.get("content-type", "")

    def test_content_length_response(self, http_client, gunicorn_url):
        """Test Content-Length in response."""
        response = http_client.get(f"{gunicorn_url}/http/")
        assert "content-length" in response.headers


# ============================================================================
# ASGI Scope Tests
# ============================================================================

class TestASGIScope:
    """Test ASGI scope correctness."""

    def test_scope_type(self, http_client, gunicorn_url):
        """Test scope type is 'http'."""
        response = http_client.get(f"{gunicorn_url}/http/scope")
        assert response.status_code == 200
        scope = response.json()
        assert scope["type"] == "http"

    def test_scope_asgi_version(self, http_client, gunicorn_url):
        """Test ASGI version in scope."""
        response = http_client.get(f"{gunicorn_url}/http/scope")
        scope = response.json()
        assert "asgi" in scope
        assert scope["asgi"]["version"] == "3.0"

    def test_scope_http_version(self, http_client, gunicorn_url):
        """Test HTTP version in scope."""
        response = http_client.get(f"{gunicorn_url}/http/scope")
        scope = response.json()
        assert scope["http_version"] in ("1.0", "1.1", "2")

    def test_scope_method(self, http_client, gunicorn_url):
        """Test method in scope."""
        response = http_client.post(f"{gunicorn_url}/http/scope")
        scope = response.json()
        assert scope["method"] == "POST"

    def test_scope_scheme(self, http_client, gunicorn_url):
        """Test scheme in scope."""
        response = http_client.get(f"{gunicorn_url}/http/scope")
        scope = response.json()
        assert scope["scheme"] == "http"

    def test_scope_path(self, http_client, gunicorn_url):
        """Test path in scope."""
        response = http_client.get(f"{gunicorn_url}/http/scope")
        scope = response.json()
        assert scope["path"] == "/scope"

    def test_scope_query_string(self, http_client, gunicorn_url):
        """Test query string in scope."""
        response = http_client.get(f"{gunicorn_url}/http/scope?foo=bar&baz=qux")
        scope = response.json()
        assert scope["query_string"] == "foo=bar&baz=qux"

    def test_scope_headers_are_list(self, http_client, gunicorn_url):
        """Test headers in scope are list of 2-tuples."""
        response = http_client.get(f"{gunicorn_url}/http/scope")
        scope = response.json()
        assert isinstance(scope["headers"], list)
        for header in scope["headers"]:
            assert isinstance(header, list)
            assert len(header) == 2

    def test_scope_server(self, http_client, gunicorn_url):
        """Test server in scope."""
        response = http_client.get(f"{gunicorn_url}/http/scope")
        scope = response.json()
        assert scope["server"] is not None
        assert isinstance(scope["server"], list)
        assert len(scope["server"]) == 2

    def test_scope_client(self, http_client, gunicorn_url):
        """Test client in scope."""
        response = http_client.get(f"{gunicorn_url}/http/scope")
        scope = response.json()
        assert scope["client"] is not None
        assert isinstance(scope["client"], list)
        assert len(scope["client"]) == 2


# ============================================================================
# Query String Tests
# ============================================================================

class TestQueryStrings:
    """Test query string handling."""

    def test_simple_query(self, http_client, gunicorn_url):
        """Test simple query parameter."""
        response = http_client.get(f"{gunicorn_url}/http/query?name=test")
        assert response.status_code == 200
        data = response.json()
        assert data["params"]["name"] == "test"

    def test_multiple_params(self, http_client, gunicorn_url):
        """Test multiple query parameters."""
        response = http_client.get(f"{gunicorn_url}/http/query?a=1&b=2&c=3")
        assert response.status_code == 200
        data = response.json()
        assert data["params"]["a"] == "1"
        assert data["params"]["b"] == "2"
        assert data["params"]["c"] == "3"

    def test_empty_query(self, http_client, gunicorn_url):
        """Test empty query string."""
        response = http_client.get(f"{gunicorn_url}/http/query")
        assert response.status_code == 200
        data = response.json()
        assert data["raw"] == ""
        assert data["params"] == {}

    def test_url_encoded_query(self, http_client, gunicorn_url):
        """Test URL-encoded query parameters."""
        response = http_client.get(f"{gunicorn_url}/http/query?name=hello%20world")
        assert response.status_code == 200
        data = response.json()
        assert data["raw"] == "name=hello%20world"


# ============================================================================
# Cookie Tests
# ============================================================================

class TestCookies:
    """Test cookie handling."""

    def test_set_cookie(self, http_client, gunicorn_url):
        """Test setting cookies."""
        response = http_client.get(f"{gunicorn_url}/http/cookies?set=session=abc123")
        assert response.status_code == 200
        assert "set-cookie" in response.headers

    def test_receive_cookie(self, http_client, gunicorn_url):
        """Test receiving cookies."""
        response = http_client.get(
            f"{gunicorn_url}/http/cookies",
            cookies={"session": "test123"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["request_cookies"].get("session") == "test123"


# ============================================================================
# Redirect Tests
# ============================================================================

class TestRedirects:
    """Test redirect handling."""

    def test_redirect_302(self, http_client, gunicorn_url):
        """Test 302 redirect."""
        response = http_client.get(f"{gunicorn_url}/http/redirect?to=/http/&status=302")
        assert response.status_code == 302
        assert response.headers.get("location") == "/http/"

    def test_redirect_301(self, http_client, gunicorn_url):
        """Test 301 redirect."""
        response = http_client.get(f"{gunicorn_url}/http/redirect?to=/http/&status=301")
        assert response.status_code == 301

    def test_redirect_307(self, http_client, gunicorn_url):
        """Test 307 redirect."""
        response = http_client.get(f"{gunicorn_url}/http/redirect?to=/http/&status=307")
        assert response.status_code == 307


# ============================================================================
# Connection Tests
# ============================================================================

class TestConnections:
    """Test connection handling."""

    def test_multiple_requests_same_connection(self, http_client, gunicorn_url):
        """Test multiple requests on same connection (keep-alive)."""
        for i in range(5):
            response = http_client.get(f"{gunicorn_url}/http/")
            assert response.status_code == 200

    def test_concurrent_requests(self, http_client, gunicorn_url):
        """Test concurrent requests."""
        import concurrent.futures

        def make_request(i):
            httpx = pytest.importorskip("httpx")
            with httpx.Client(verify=False, timeout=30.0) as client:
                response = client.get(f"{gunicorn_url}/http/method")
                return response.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request, i) for i in range(20)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert all(status == 200 for status in results)


# ============================================================================
# Proxy Tests (via Nginx)
# ============================================================================

class TestProxyRequests:
    """Test requests through nginx proxy."""

    def test_proxy_basic_request(self, http_client, nginx_url):
        """Test basic request through proxy."""
        response = http_client.get(f"{nginx_url}/http/")
        assert response.status_code == 200
        assert response.text == "Hello, ASGI!"

    def test_proxy_headers_forwarded(self, http_client, nginx_url):
        """Test that proxy headers are forwarded."""
        response = http_client.get(f"{nginx_url}/http/headers")
        assert response.status_code == 200
        headers = response.json()
        # Nginx should add X-Forwarded-For
        assert "x-forwarded-for" in headers or "x-real-ip" in headers

    def test_proxy_large_request(self, http_client, nginx_url):
        """Test large request through proxy."""
        body = b"x" * (100 * 1024)  # 100KB
        response = http_client.post(f"{nginx_url}/http/echo", content=body)
        assert response.status_code == 200
        assert len(response.content) == len(body)

    def test_proxy_large_response(self, http_client, nginx_url):
        """Test large response through proxy."""
        response = http_client.get(f"{nginx_url}/http/large?size=1048576")
        assert response.status_code == 200
        assert len(response.content) == 1048576


# ============================================================================
# HTTPS Tests
# ============================================================================

@pytest.mark.ssl
class TestHTTPS:
    """Test HTTPS connections."""

    def test_https_basic_request(self, http_client, gunicorn_ssl_url):
        """Test basic HTTPS request."""
        response = http_client.get(f"{gunicorn_ssl_url}/http/")
        assert response.status_code == 200

    def test_https_scope_scheme(self, http_client, gunicorn_ssl_url):
        """Test scope scheme is https."""
        response = http_client.get(f"{gunicorn_ssl_url}/http/scope")
        assert response.status_code == 200
        scope = response.json()
        assert scope["scheme"] == "https"

    def test_https_via_proxy(self, http_client, nginx_ssl_url):
        """Test HTTPS through nginx proxy."""
        response = http_client.get(f"{nginx_ssl_url}/http/")
        assert response.status_code == 200


# ============================================================================
# Error Handling Tests
# ============================================================================

class TestErrorHandling:
    """Test error handling."""

    def test_invalid_json_body(self, http_client, gunicorn_url):
        """Test handling of invalid JSON body."""
        response = http_client.post(
            f"{gunicorn_url}/http/post-json",
            content=b"not valid json",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 400
        assert "Invalid JSON" in response.text

    def test_method_not_allowed(self, http_client, gunicorn_url):
        """Test method not allowed response."""
        response = http_client.get(f"{gunicorn_url}/http/post-json")
        assert response.status_code == 405
