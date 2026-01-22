#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Tests for ASGI worker components.
"""

import asyncio
import io
import pytest
from unittest import mock

from gunicorn.asgi.unreader import AsyncUnreader
from gunicorn.asgi.message import AsyncRequest


class MockStreamReader:
    """Mock asyncio.StreamReader for testing."""

    def __init__(self, data):
        self.data = data
        self.pos = 0

    async def read(self, size=-1):
        if self.pos >= len(self.data):
            return b""
        if size < 0:
            result = self.data[self.pos:]
            self.pos = len(self.data)
        else:
            result = self.data[self.pos:self.pos + size]
            self.pos += size
        return result

    async def readexactly(self, n):
        if self.pos + n > len(self.data):
            raise asyncio.IncompleteReadError(
                self.data[self.pos:], n
            )
        result = self.data[self.pos:self.pos + n]
        self.pos += n
        return result


class MockConfig:
    """Mock gunicorn config for testing."""

    def __init__(self):
        self.is_ssl = False
        self.proxy_protocol = False
        self.proxy_allow_ips = ["127.0.0.1"]
        self.forwarded_allow_ips = ["127.0.0.1"]
        self.secure_scheme_headers = {}
        self.forwarder_headers = []
        self.limit_request_line = 8190
        self.limit_request_fields = 100
        self.limit_request_field_size = 8190
        self.permit_unconventional_http_method = False
        self.permit_unconventional_http_version = False
        self.permit_obsolete_folding = False
        self.casefold_http_method = False
        self.strip_header_spaces = False
        self.header_map = "refuse"


# AsyncUnreader Tests

@pytest.mark.asyncio
async def test_async_unreader_read_chunk():
    """Test basic chunk reading."""
    reader = MockStreamReader(b"hello world")
    unreader = AsyncUnreader(reader)
    data = await unreader.read()
    assert data == b"hello world"


@pytest.mark.asyncio
async def test_async_unreader_read_size():
    """Test reading specific size."""
    reader = MockStreamReader(b"hello world")
    unreader = AsyncUnreader(reader)
    data = await unreader.read(5)
    assert data == b"hello"


@pytest.mark.asyncio
async def test_async_unreader_unread():
    """Test unread functionality."""
    reader = MockStreamReader(b"hello world")
    unreader = AsyncUnreader(reader)

    # Read all data
    data = await unreader.read()
    assert data == b"hello world"

    # Unread some data
    unreader.unread(b"world")

    # Read again should get unread data
    data = await unreader.read()
    assert data == b"world"


@pytest.mark.asyncio
async def test_async_unreader_read_zero():
    """Test reading zero bytes."""
    reader = MockStreamReader(b"hello")
    unreader = AsyncUnreader(reader)
    data = await unreader.read(0)
    assert data == b""


@pytest.mark.asyncio
async def test_async_unreader_read_empty():
    """Test reading from empty stream."""
    reader = MockStreamReader(b"")
    unreader = AsyncUnreader(reader)
    data = await unreader.read()
    assert data == b""


# AsyncRequest Tests

@pytest.mark.asyncio
async def test_async_request_simple_get():
    """Test parsing a simple GET request."""
    request_data = b"GET /path HTTP/1.1\r\nHost: localhost\r\n\r\n"
    reader = MockStreamReader(request_data)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    request = await AsyncRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    assert request.method == "GET"
    assert request.path == "/path"
    assert request.version == (1, 1)
    assert ("HOST", "localhost") in request.headers


@pytest.mark.asyncio
async def test_async_request_with_query():
    """Test parsing request with query string."""
    request_data = b"GET /search?q=test&page=1 HTTP/1.1\r\nHost: localhost\r\n\r\n"
    reader = MockStreamReader(request_data)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    request = await AsyncRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    assert request.method == "GET"
    assert request.path == "/search"
    assert request.query == "q=test&page=1"


@pytest.mark.asyncio
async def test_async_request_post_with_body():
    """Test parsing POST request with body."""
    request_data = (
        b"POST /submit HTTP/1.1\r\n"
        b"Host: localhost\r\n"
        b"Content-Length: 11\r\n"
        b"\r\n"
        b"hello=world"
    )
    reader = MockStreamReader(request_data)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    request = await AsyncRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    assert request.method == "POST"
    assert request.path == "/submit"
    assert request.content_length == 11

    # Read body
    body = await request.read_body(100)
    assert body == b"hello=world"


@pytest.mark.asyncio
async def test_async_request_multiple_headers():
    """Test parsing request with multiple headers."""
    request_data = (
        b"GET / HTTP/1.1\r\n"
        b"Host: localhost\r\n"
        b"Accept: text/html\r\n"
        b"Accept-Language: en-US\r\n"
        b"Connection: keep-alive\r\n"
        b"\r\n"
    )
    reader = MockStreamReader(request_data)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    request = await AsyncRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    assert len(request.headers) == 4
    assert request.get_header("HOST") == "localhost"
    assert request.get_header("ACCEPT") == "text/html"


@pytest.mark.asyncio
async def test_async_request_should_close_http10():
    """Test connection close detection for HTTP/1.0."""
    request_data = b"GET / HTTP/1.0\r\nHost: localhost\r\n\r\n"
    reader = MockStreamReader(request_data)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    request = await AsyncRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    assert request.version == (1, 0)
    assert request.should_close() is True


@pytest.mark.asyncio
async def test_async_request_should_close_connection_header():
    """Test connection close detection with Connection header."""
    request_data = b"GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
    reader = MockStreamReader(request_data)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    request = await AsyncRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    assert request.should_close() is True


@pytest.mark.asyncio
async def test_async_request_keepalive():
    """Test keepalive detection."""
    request_data = b"GET / HTTP/1.1\r\nHost: localhost\r\nConnection: keep-alive\r\n\r\n"
    reader = MockStreamReader(request_data)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    request = await AsyncRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    assert request.should_close() is False


@pytest.mark.asyncio
async def test_async_request_no_body_for_get():
    """Test that GET requests have no body by default."""
    request_data = b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n"
    reader = MockStreamReader(request_data)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    request = await AsyncRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    assert request.content_length == 0
    body = await request.read_body()
    assert body == b""


# Error handling tests

@pytest.mark.asyncio
async def test_async_request_invalid_method():
    """Test invalid HTTP method detection."""
    from gunicorn.http.errors import InvalidRequestMethod

    request_data = b"ge!t / HTTP/1.1\r\nHost: localhost\r\n\r\n"
    reader = MockStreamReader(request_data)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    with pytest.raises(InvalidRequestMethod):
        await AsyncRequest.parse(cfg, unreader, ("127.0.0.1", 8000))


@pytest.mark.asyncio
async def test_async_request_invalid_http_version():
    """Test invalid HTTP version detection."""
    from gunicorn.http.errors import InvalidHTTPVersion

    request_data = b"GET / HTTP/2.0\r\nHost: localhost\r\n\r\n"
    reader = MockStreamReader(request_data)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    with pytest.raises(InvalidHTTPVersion):
        await AsyncRequest.parse(cfg, unreader, ("127.0.0.1", 8000))
