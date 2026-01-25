#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Tests for ASGI uWSGI protocol parser.
"""

import pytest

from gunicorn.asgi.unreader import AsyncUnreader
from gunicorn.asgi.uwsgi import AsyncUWSGIRequest
from gunicorn.uwsgi.errors import (
    InvalidUWSGIHeader,
    UnsupportedModifier,
    ForbiddenUWSGIRequest,
)


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
        self.uwsgi_allow_ips = ['*']  # Allow all for most tests


def build_uwsgi_packet(vars_dict, modifier1=0, modifier2=0):
    """Build a uWSGI packet from a dictionary of variables.

    Args:
        vars_dict: Dictionary of uWSGI variables
        modifier1: uWSGI modifier1 (default 0 for WSGI)
        modifier2: uWSGI modifier2 (default 0)

    Returns:
        bytes: Complete uWSGI packet
    """
    vars_data = b""
    for key, value in vars_dict.items():
        key_bytes = key.encode('latin-1')
        value_bytes = value.encode('latin-1')
        vars_data += len(key_bytes).to_bytes(2, 'little')
        vars_data += key_bytes
        vars_data += len(value_bytes).to_bytes(2, 'little')
        vars_data += value_bytes

    # Build header: modifier1 (1 byte) + datasize (2 bytes LE) + modifier2 (1 byte)
    header = bytes([modifier1])
    header += len(vars_data).to_bytes(2, 'little')
    header += bytes([modifier2])

    return header + vars_data


# Basic parsing tests

@pytest.mark.asyncio
async def test_parse_simple_get():
    """Test parsing a simple GET request."""
    vars_dict = {
        'REQUEST_METHOD': 'GET',
        'PATH_INFO': '/test',
        'QUERY_STRING': '',
        'HTTP_HOST': 'localhost',
    }
    packet = build_uwsgi_packet(vars_dict)
    reader = MockStreamReader(packet)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    request = await AsyncUWSGIRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    assert request.method == "GET"
    assert request.path == "/test"
    assert request.query == ""
    assert request.uri == "/test"
    assert request.version == (1, 1)


@pytest.mark.asyncio
async def test_parse_get_with_query():
    """Test parsing GET request with query string."""
    vars_dict = {
        'REQUEST_METHOD': 'GET',
        'PATH_INFO': '/search',
        'QUERY_STRING': 'q=test&page=1',
    }
    packet = build_uwsgi_packet(vars_dict)
    reader = MockStreamReader(packet)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    request = await AsyncUWSGIRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    assert request.method == "GET"
    assert request.path == "/search"
    assert request.query == "q=test&page=1"
    assert request.uri == "/search?q=test&page=1"


@pytest.mark.asyncio
async def test_parse_post_with_content_length():
    """Test parsing POST request with content length."""
    body = b"hello=world"
    vars_dict = {
        'REQUEST_METHOD': 'POST',
        'PATH_INFO': '/submit',
        'CONTENT_LENGTH': str(len(body)),
        'CONTENT_TYPE': 'application/x-www-form-urlencoded',
    }
    packet = build_uwsgi_packet(vars_dict) + body
    reader = MockStreamReader(packet)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    request = await AsyncUWSGIRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    assert request.method == "POST"
    assert request.path == "/submit"
    assert request.content_length == len(body)

    # Read body
    read_body = await request.read_body(100)
    assert read_body == body


@pytest.mark.asyncio
async def test_parse_headers():
    """Test that HTTP headers are correctly extracted."""
    vars_dict = {
        'REQUEST_METHOD': 'GET',
        'PATH_INFO': '/',
        'HTTP_HOST': 'example.com',
        'HTTP_ACCEPT': 'text/html',
        'HTTP_X_CUSTOM_HEADER': 'custom-value',
        'CONTENT_TYPE': 'text/plain',
        'CONTENT_LENGTH': '0',
    }
    packet = build_uwsgi_packet(vars_dict)
    reader = MockStreamReader(packet)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    request = await AsyncUWSGIRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    # Check headers were extracted correctly
    assert request.get_header('HOST') == 'example.com'
    assert request.get_header('ACCEPT') == 'text/html'
    assert request.get_header('X-CUSTOM-HEADER') == 'custom-value'
    assert request.get_header('CONTENT-TYPE') == 'text/plain'
    assert request.get_header('CONTENT-LENGTH') == '0'


@pytest.mark.asyncio
async def test_parse_https_scheme():
    """Test HTTPS scheme detection."""
    vars_dict = {
        'REQUEST_METHOD': 'GET',
        'PATH_INFO': '/',
        'HTTPS': 'on',
    }
    packet = build_uwsgi_packet(vars_dict)
    reader = MockStreamReader(packet)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    request = await AsyncUWSGIRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    assert request.scheme == 'https'


@pytest.mark.asyncio
async def test_parse_wsgi_url_scheme():
    """Test wsgi.url_scheme variable."""
    vars_dict = {
        'REQUEST_METHOD': 'GET',
        'PATH_INFO': '/',
        'wsgi.url_scheme': 'https',
    }
    packet = build_uwsgi_packet(vars_dict)
    reader = MockStreamReader(packet)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    request = await AsyncUWSGIRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    assert request.scheme == 'https'


# Body reading tests

@pytest.mark.asyncio
async def test_read_body_chunks():
    """Test reading body in chunks."""
    body = b"a" * 100
    vars_dict = {
        'REQUEST_METHOD': 'POST',
        'PATH_INFO': '/',
        'CONTENT_LENGTH': str(len(body)),
    }
    packet = build_uwsgi_packet(vars_dict) + body
    reader = MockStreamReader(packet)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    request = await AsyncUWSGIRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    # Read in chunks
    chunks = []
    while True:
        chunk = await request.read_body(30)
        if not chunk:
            break
        chunks.append(chunk)

    assert b"".join(chunks) == body


@pytest.mark.asyncio
async def test_drain_body():
    """Test draining unread body."""
    body = b"x" * 50
    vars_dict = {
        'REQUEST_METHOD': 'POST',
        'PATH_INFO': '/',
        'CONTENT_LENGTH': str(len(body)),
    }
    packet = build_uwsgi_packet(vars_dict) + body
    reader = MockStreamReader(packet)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    request = await AsyncUWSGIRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    # Drain without reading
    await request.drain_body()

    # Further reads should return empty
    chunk = await request.read_body()
    assert chunk == b""


@pytest.mark.asyncio
async def test_no_body():
    """Test request with no body."""
    vars_dict = {
        'REQUEST_METHOD': 'GET',
        'PATH_INFO': '/',
    }
    packet = build_uwsgi_packet(vars_dict)
    reader = MockStreamReader(packet)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    request = await AsyncUWSGIRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    assert request.content_length == 0
    chunk = await request.read_body()
    assert chunk == b""


# Connection handling tests

@pytest.mark.asyncio
async def test_should_close_default():
    """Test default keepalive behavior."""
    vars_dict = {
        'REQUEST_METHOD': 'GET',
        'PATH_INFO': '/',
    }
    packet = build_uwsgi_packet(vars_dict)
    reader = MockStreamReader(packet)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    request = await AsyncUWSGIRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    # Default should be keep-alive (HTTP/1.1 behavior)
    assert request.should_close() is False


@pytest.mark.asyncio
async def test_should_close_connection_close():
    """Test connection close header."""
    vars_dict = {
        'REQUEST_METHOD': 'GET',
        'PATH_INFO': '/',
        'HTTP_CONNECTION': 'close',
    }
    packet = build_uwsgi_packet(vars_dict)
    reader = MockStreamReader(packet)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    request = await AsyncUWSGIRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    assert request.should_close() is True


@pytest.mark.asyncio
async def test_should_close_keepalive():
    """Test connection keep-alive header."""
    vars_dict = {
        'REQUEST_METHOD': 'GET',
        'PATH_INFO': '/',
        'HTTP_CONNECTION': 'keep-alive',
    }
    packet = build_uwsgi_packet(vars_dict)
    reader = MockStreamReader(packet)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    request = await AsyncUWSGIRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    assert request.should_close() is False


# Error handling tests

@pytest.mark.asyncio
async def test_incomplete_header():
    """Test incomplete header raises error."""
    # Only 2 bytes instead of 4
    data = b"\x00\x00"
    reader = MockStreamReader(data)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    with pytest.raises(InvalidUWSGIHeader):
        await AsyncUWSGIRequest.parse(cfg, unreader, ("127.0.0.1", 8000))


@pytest.mark.asyncio
async def test_unsupported_modifier():
    """Test unsupported modifier1 raises error."""
    # modifier1 = 1 (not WSGI)
    header = bytes([1, 0, 0, 0])  # modifier1=1, datasize=0, modifier2=0
    reader = MockStreamReader(header)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    with pytest.raises(UnsupportedModifier):
        await AsyncUWSGIRequest.parse(cfg, unreader, ("127.0.0.1", 8000))


@pytest.mark.asyncio
async def test_incomplete_vars_block():
    """Test incomplete vars block raises error."""
    # Header says 100 bytes of vars, but only 10 provided
    header = bytes([0])  # modifier1=0
    header += (100).to_bytes(2, 'little')  # datasize=100
    header += bytes([0])  # modifier2=0
    header += b"x" * 10  # Only 10 bytes

    reader = MockStreamReader(header)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    with pytest.raises(InvalidUWSGIHeader):
        await AsyncUWSGIRequest.parse(cfg, unreader, ("127.0.0.1", 8000))


@pytest.mark.asyncio
async def test_forbidden_ip():
    """Test forbidden IP raises error."""
    vars_dict = {
        'REQUEST_METHOD': 'GET',
        'PATH_INFO': '/',
    }
    packet = build_uwsgi_packet(vars_dict)
    reader = MockStreamReader(packet)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()
    cfg.uwsgi_allow_ips = ['10.0.0.1']  # Only allow 10.0.0.1

    with pytest.raises(ForbiddenUWSGIRequest):
        await AsyncUWSGIRequest.parse(cfg, unreader, ("192.168.1.1", 8000))


@pytest.mark.asyncio
async def test_allowed_ip():
    """Test allowed IP succeeds."""
    vars_dict = {
        'REQUEST_METHOD': 'GET',
        'PATH_INFO': '/',
    }
    packet = build_uwsgi_packet(vars_dict)
    reader = MockStreamReader(packet)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()
    cfg.uwsgi_allow_ips = ['192.168.1.1']

    # Should not raise
    request = await AsyncUWSGIRequest.parse(cfg, unreader, ("192.168.1.1", 8000))
    assert request.method == "GET"


@pytest.mark.asyncio
async def test_unix_socket_allowed():
    """Test UNIX socket connections are always allowed."""
    vars_dict = {
        'REQUEST_METHOD': 'GET',
        'PATH_INFO': '/',
    }
    packet = build_uwsgi_packet(vars_dict)
    reader = MockStreamReader(packet)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()
    cfg.uwsgi_allow_ips = ['10.0.0.1']  # Restrictive IP list

    # UNIX socket peer_addr is not a tuple
    request = await AsyncUWSGIRequest.parse(cfg, unreader, "/tmp/gunicorn.sock")
    assert request.method == "GET"


# Empty vars block test

@pytest.mark.asyncio
async def test_empty_vars_block():
    """Test request with empty vars block uses defaults."""
    # Header with datasize=0
    header = bytes([0, 0, 0, 0])
    reader = MockStreamReader(header)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()

    request = await AsyncUWSGIRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    # Should use defaults
    assert request.method == "GET"
    assert request.path == "/"
    assert request.query == ""


# SSL config test

@pytest.mark.asyncio
async def test_ssl_config_scheme():
    """Test SSL config sets https scheme."""
    vars_dict = {
        'REQUEST_METHOD': 'GET',
        'PATH_INFO': '/',
    }
    packet = build_uwsgi_packet(vars_dict)
    reader = MockStreamReader(packet)
    unreader = AsyncUnreader(reader)
    cfg = MockConfig()
    cfg.is_ssl = True

    request = await AsyncUWSGIRequest.parse(cfg, unreader, ("127.0.0.1", 8000))

    assert request.scheme == 'https'
