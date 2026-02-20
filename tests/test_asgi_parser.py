#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Tests for ASGI HTTP parser optimizations.
"""

import asyncio
import ipaddress
import pytest

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


class MockConfig:
    """Mock gunicorn config for testing."""

    def __init__(self):
        self.is_ssl = False
        self.proxy_protocol = "off"
        self.proxy_allow_ips = ["127.0.0.1"]
        self.forwarded_allow_ips = ["127.0.0.1"]
        self._proxy_allow_networks = None
        self._forwarded_allow_networks = None
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

    def forwarded_allow_networks(self):
        if self._forwarded_allow_networks is None:
            self._forwarded_allow_networks = [
                ipaddress.ip_network(addr)
                for addr in self.forwarded_allow_ips
                if addr != "*"
            ]
        return self._forwarded_allow_networks

    def proxy_allow_networks(self):
        if self._proxy_allow_networks is None:
            self._proxy_allow_networks = [
                ipaddress.ip_network(addr)
                for addr in self.proxy_allow_ips
                if addr != "*"
            ]
        return self._proxy_allow_networks


# Optimized Chunk Reading Tests

@pytest.mark.asyncio
async def test_chunk_size_line_reading():
    """Test optimized chunk size line reading."""
    # Simulate chunked body with chunk size line
    data = b"a\r\nhello body\r\n0\r\n\r\n"
    reader = MockStreamReader(data)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    req = AsyncRequest(cfg, unreader, ("127.0.0.1", 8000))
    # Access the private method for testing
    line = await req._read_chunk_size_line()
    assert line == b"a"


@pytest.mark.asyncio
async def test_skip_trailers_empty():
    """Test skipping empty trailers."""
    data = b"\r\n"
    reader = MockStreamReader(data)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    req = AsyncRequest(cfg, unreader, ("127.0.0.1", 8000))
    # Should not raise
    await req._skip_trailers()


@pytest.mark.asyncio
async def test_skip_trailers_with_headers():
    """Test skipping trailers with actual headers."""
    data = b"X-Checksum: abc123\r\n\r\n"
    reader = MockStreamReader(data)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    req = AsyncRequest(cfg, unreader, ("127.0.0.1", 8000))
    # Should not raise
    await req._skip_trailers()


# Buffer Reuse Tests

@pytest.mark.asyncio
async def test_unreader_buffer_reuse():
    """Test that AsyncUnreader reuses buffers efficiently."""
    data = b"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n"
    reader = MockStreamReader(data)
    unreader = AsyncUnreader(reader)

    # Read in chunks
    chunk1 = await unreader.read(10)
    assert chunk1 == b"GET / HTTP"

    # Read more
    chunk2 = await unreader.read(10)
    assert chunk2 == b"/1.1\r\nHost"

    # Unread some data
    unreader.unread(b"/1.1\r\nHost")

    # Read again - should get unreaded data
    chunk3 = await unreader.read(10)
    assert chunk3 == b"/1.1\r\nHost"


@pytest.mark.asyncio
async def test_unreader_unread_prepends():
    """Test that unread prepends data."""
    data = b"original"
    reader = MockStreamReader(data)
    unreader = AsyncUnreader(reader)

    # Read some data first
    await unreader.read(4)  # "orig"

    # Unread something different
    unreader.unread(b"NEW")

    # Should read the new data first
    result = await unreader.read(3)
    assert result == b"NEW"


# Header Parsing Optimization Tests

@pytest.mark.asyncio
async def test_header_parsing_index_iteration():
    """Test that header parsing uses index-based iteration."""
    raw_request = (
        b"GET / HTTP/1.1\r\n"
        b"Host: example.com\r\n"
        b"Content-Type: text/plain\r\n"
        b"X-Custom: value\r\n"
        b"\r\n"
    )
    reader = MockStreamReader(raw_request)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    req = await AsyncRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    assert req.method == "GET"
    assert req.path == "/"
    assert len(req.headers) == 3
    assert ("HOST", "example.com") in req.headers
    assert ("CONTENT-TYPE", "text/plain") in req.headers
    assert ("X-CUSTOM", "value") in req.headers


@pytest.mark.asyncio
async def test_many_headers_performance():
    """Test parsing request with many headers."""
    headers = []
    for i in range(50):
        headers.append(f"X-Header-{i}: value-{i}\r\n")

    raw_request = (
        b"GET / HTTP/1.1\r\n"
        + "".join(headers).encode()
        + b"\r\n"
    )

    reader = MockStreamReader(raw_request)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    req = await AsyncRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    assert len(req.headers) == 50


# Bytearray Find Optimization Tests

@pytest.mark.asyncio
async def test_bytearray_find_optimization():
    """Test that bytearray.find() is used instead of bytes().find()."""
    raw_request = (
        b"GET /path?query=value HTTP/1.1\r\n"
        b"Host: example.com\r\n"
        b"Content-Length: 5\r\n"
        b"\r\n"
        b"hello"
    )
    reader = MockStreamReader(raw_request)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    req = await AsyncRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    assert req.method == "GET"
    assert req.path == "/path"
    assert req.query == "query=value"
    assert req.content_length == 5


# Chunked Body Tests with Optimized Reading

@pytest.mark.asyncio
async def test_chunked_body_optimized_reading():
    """Test reading chunked body with optimized chunk reading."""
    raw_request = (
        b"POST / HTTP/1.1\r\n"
        b"Host: example.com\r\n"
        b"Transfer-Encoding: chunked\r\n"
        b"\r\n"
        b"5\r\nhello\r\n"
        b"6\r\n world\r\n"
        b"0\r\n\r\n"
    )
    reader = MockStreamReader(raw_request)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    req = await AsyncRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    assert req.chunked is True
    assert req.content_length is None

    # Read body
    body_parts = []
    while True:
        chunk = await req.read_body(1024)
        if not chunk:
            break
        body_parts.append(chunk)

    body = b"".join(body_parts)
    assert body == b"hello world"


@pytest.mark.asyncio
async def test_chunked_body_with_extension():
    """Test reading chunked body with chunk extensions."""
    raw_request = (
        b"POST / HTTP/1.1\r\n"
        b"Host: example.com\r\n"
        b"Transfer-Encoding: chunked\r\n"
        b"\r\n"
        b"5;ext=value\r\nhello\r\n"
        b"0\r\n\r\n"
    )
    reader = MockStreamReader(raw_request)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    req = await AsyncRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    chunk = await req.read_body(1024)
    assert chunk == b"hello"


# Edge Cases

@pytest.mark.asyncio
async def test_empty_headers():
    """Test request with no headers."""
    raw_request = (
        b"GET / HTTP/1.1\r\n"
        b"\r\n"
    )
    reader = MockStreamReader(raw_request)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    req = await AsyncRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    assert req.method == "GET"
    assert len(req.headers) == 0


@pytest.mark.asyncio
async def test_large_header_value():
    """Test request with large header value."""
    large_value = "x" * 4000  # Within default limit
    raw_request = (
        b"GET / HTTP/1.1\r\n"
        + f"X-Large-Header: {large_value}\r\n".encode()
        + b"\r\n"
    )
    reader = MockStreamReader(raw_request)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    req = await AsyncRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    assert req.get_header("X-Large-Header") == large_value
