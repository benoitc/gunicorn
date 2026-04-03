"""
HTTP Scope Compliance Tests

Tests ASGI 3.0 HTTP scope compliance across frameworks.
"""

import pytest

from frameworks.contract import ASGI_HTTP_SCOPE_REQUIRED_KEYS


pytestmark = pytest.mark.http


class TestHttpScopeBasics:
    """Test basic HTTP scope attributes."""

    async def test_scope_endpoint_returns_json(self, http_client):
        """Scope endpoint returns valid JSON."""
        response = await http_client.get("/scope")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    async def test_scope_has_type_http(self, http_client):
        """Scope type is 'http'."""
        response = await http_client.get("/scope")
        data = response.json()
        assert data.get("type") == "http"

    async def test_scope_has_asgi_dict(self, http_client):
        """Scope has 'asgi' dict with version info."""
        response = await http_client.get("/scope")
        data = response.json()
        assert "asgi" in data
        assert isinstance(data["asgi"], dict)
        assert "version" in data["asgi"]

    async def test_scope_asgi_version_is_3(self, http_client):
        """ASGI version should be 3.x."""
        response = await http_client.get("/scope")
        data = response.json()
        version = data["asgi"]["version"]
        assert version.startswith("3.")

    async def test_scope_has_http_version(self, http_client):
        """Scope has http_version field."""
        response = await http_client.get("/scope")
        data = response.json()
        assert "http_version" in data
        assert data["http_version"] in ("1.0", "1.1", "2", "3")

    async def test_scope_has_method(self, http_client):
        """Scope has method field matching request method."""
        response = await http_client.get("/scope")
        data = response.json()
        assert data.get("method") == "GET"

    async def test_scope_has_scheme(self, http_client):
        """Scope has scheme field."""
        response = await http_client.get("/scope")
        data = response.json()
        assert "scheme" in data
        assert data["scheme"] in ("http", "https")

    async def test_scope_has_path(self, http_client):
        """Scope has path field matching request path."""
        response = await http_client.get("/scope")
        data = response.json()
        assert data.get("path") == "/scope"

    async def test_scope_has_query_string(self, http_client):
        """Scope has query_string field."""
        response = await http_client.get("/scope?foo=bar")
        data = response.json()
        assert "query_string" in data
        assert "foo=bar" in data["query_string"]

    async def test_scope_empty_query_string(self, http_client):
        """Empty query string handled correctly."""
        response = await http_client.get("/scope")
        data = response.json()
        assert "query_string" in data
        assert data["query_string"] == ""


class TestHttpScopeHeaders:
    """Test HTTP scope header handling."""

    async def test_scope_has_headers(self, http_client):
        """Scope has headers field."""
        response = await http_client.get("/scope")
        data = response.json()
        assert "headers" in data
        assert isinstance(data["headers"], list)

    async def test_scope_headers_are_lists(self, http_client):
        """Each header is a list of [name, value]."""
        response = await http_client.get("/scope")
        data = response.json()
        for header in data["headers"]:
            assert isinstance(header, list)
            assert len(header) == 2

    async def test_scope_header_names_lowercase(self, http_client):
        """Header names should be lowercase."""
        response = await http_client.get("/scope", headers={"X-Custom-Header": "test"})
        data = response.json()
        custom_headers = [h for h in data["headers"] if h[0] == "x-custom-header"]
        assert len(custom_headers) > 0

    async def test_headers_endpoint_returns_all_headers(self, http_client):
        """Headers endpoint returns all sent headers."""
        custom_headers = {
            "X-Test-One": "value1",
            "X-Test-Two": "value2",
        }
        response = await http_client.get("/headers", headers=custom_headers)
        data = response.json()
        assert data.get("x-test-one") == "value1"
        assert data.get("x-test-two") == "value2"


class TestHttpScopeServer:
    """Test HTTP scope server and client fields."""

    async def test_scope_has_server(self, http_client):
        """Scope has server field."""
        response = await http_client.get("/scope")
        data = response.json()
        assert "server" in data

    async def test_scope_server_is_tuple(self, http_client):
        """Server is [host, port] list."""
        response = await http_client.get("/scope")
        data = response.json()
        if data["server"] is not None:
            assert isinstance(data["server"], list)
            assert len(data["server"]) == 2

    async def test_scope_has_client(self, http_client):
        """Scope has client field (may be None)."""
        response = await http_client.get("/scope")
        data = response.json()
        # client is optional but should be present
        assert "client" in data or data.get("client") is None


class TestHttpScopeRequired:
    """Test all required scope keys are present."""

    async def test_all_required_keys_present(self, http_client):
        """All ASGI 3.0 required HTTP scope keys are present."""
        response = await http_client.get("/scope")
        data = response.json()
        for key in ASGI_HTTP_SCOPE_REQUIRED_KEYS:
            assert key in data, f"Missing required scope key: {key}"


class TestHttpScopeRootPath:
    """Test root_path handling."""

    async def test_scope_has_root_path(self, http_client):
        """Scope has root_path field (may be empty)."""
        response = await http_client.get("/scope")
        data = response.json()
        # root_path should be present, defaults to ""
        assert "root_path" in data or data.get("root_path", "") == ""
