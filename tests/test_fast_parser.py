#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Tests for the fast HTTP parser (gunicorn_h1c).
"""

import pytest
import asyncio

from gunicorn.config import Config
from gunicorn.http.fast_parser import (
    is_fast_parser_available,
    get_request_class,
    get_parser_class,
)
from gunicorn.http.message import Request
from gunicorn.http.parser import RequestParser


# Check if fast parser is available for conditional tests
FAST_PARSER_AVAILABLE = is_fast_parser_available()


class TestFastParserAvailability:
    """Test fast parser availability detection."""

    def test_is_fast_parser_available_returns_bool(self):
        """is_fast_parser_available() should return a boolean."""
        result = is_fast_parser_available()
        assert isinstance(result, bool)

    def test_availability_is_consistent(self):
        """Multiple calls should return the same result (cached)."""
        result1 = is_fast_parser_available()
        result2 = is_fast_parser_available()
        assert result1 == result2


class TestGetRequestClass:
    """Test get_request_class factory function."""

    def test_python_mode_returns_standard_request(self):
        """http_parser='python' should always return standard Request."""
        cfg = Config()
        cfg.set('http_parser', 'python')

        RequestClass = get_request_class(cfg, async_mode=False)
        assert RequestClass == Request

    def test_python_mode_returns_standard_async_request(self):
        """http_parser='python' should return standard AsyncRequest."""
        from gunicorn.asgi.message import AsyncRequest

        cfg = Config()
        cfg.set('http_parser', 'python')

        RequestClass = get_request_class(cfg, async_mode=True)
        assert RequestClass == AsyncRequest

    def test_fast_mode_fails_without_module(self):
        """http_parser='fast' should fail if gunicorn_h1c not installed."""
        if FAST_PARSER_AVAILABLE:
            pytest.skip("gunicorn_h1c is installed")

        cfg = Config()
        cfg.set('http_parser', 'fast')

        with pytest.raises(RuntimeError) as excinfo:
            get_request_class(cfg, async_mode=False)
        assert "gunicorn_h1c is not installed" in str(excinfo.value)

    @pytest.mark.skipif(not FAST_PARSER_AVAILABLE,
                        reason="gunicorn_h1c not installed")
    def test_fast_mode_returns_fast_request(self):
        """http_parser='fast' should return FastRequest when available."""
        from gunicorn.http.fast_message import FastRequest

        cfg = Config()
        cfg.set('http_parser', 'fast')

        RequestClass = get_request_class(cfg, async_mode=False)
        assert RequestClass == FastRequest

    @pytest.mark.skipif(not FAST_PARSER_AVAILABLE,
                        reason="gunicorn_h1c not installed")
    def test_fast_mode_returns_fast_async_request(self):
        """http_parser='fast' should return FastAsyncRequest when available."""
        from gunicorn.asgi.fast_message import FastAsyncRequest

        cfg = Config()
        cfg.set('http_parser', 'fast')

        RequestClass = get_request_class(cfg, async_mode=True)
        assert RequestClass == FastAsyncRequest

    def test_auto_mode_fallback(self):
        """http_parser='auto' should fallback to standard parser if unavailable."""
        if FAST_PARSER_AVAILABLE:
            pytest.skip("gunicorn_h1c is installed - cannot test fallback")

        cfg = Config()
        cfg.set('http_parser', 'auto')

        RequestClass = get_request_class(cfg, async_mode=False)
        assert RequestClass == Request

    @pytest.mark.skipif(not FAST_PARSER_AVAILABLE,
                        reason="gunicorn_h1c not installed")
    def test_auto_mode_uses_fast_when_available(self):
        """http_parser='auto' should use fast parser if available."""
        from gunicorn.http.fast_message import FastRequest

        cfg = Config()
        cfg.set('http_parser', 'auto')

        RequestClass = get_request_class(cfg, async_mode=False)
        assert RequestClass == FastRequest


class TestGetParserClass:
    """Test get_parser_class factory function."""

    def test_python_mode_returns_standard_parser(self):
        """http_parser='python' should always return RequestParser."""
        cfg = Config()
        cfg.set('http_parser', 'python')

        ParserClass = get_parser_class(cfg)
        assert ParserClass == RequestParser

    def test_fast_mode_fails_without_module(self):
        """http_parser='fast' should fail if gunicorn_h1c not installed."""
        if FAST_PARSER_AVAILABLE:
            pytest.skip("gunicorn_h1c is installed")

        cfg = Config()
        cfg.set('http_parser', 'fast')

        with pytest.raises(RuntimeError) as excinfo:
            get_parser_class(cfg)
        assert "gunicorn_h1c is not installed" in str(excinfo.value)

    @pytest.mark.skipif(not FAST_PARSER_AVAILABLE,
                        reason="gunicorn_h1c not installed")
    def test_fast_mode_returns_fast_parser(self):
        """http_parser='fast' should return FastRequestParser when available."""
        from gunicorn.http.fast_message import FastRequestParser

        cfg = Config()
        cfg.set('http_parser', 'fast')

        ParserClass = get_parser_class(cfg)
        assert ParserClass == FastRequestParser


@pytest.mark.skipif(not FAST_PARSER_AVAILABLE,
                    reason="gunicorn_h1c not installed")
class TestFastRequestParsing:
    """Test FastRequest parsing functionality."""

    def test_simple_get_request(self):
        """FastRequest should parse a simple GET request."""
        from gunicorn.http.fast_message import FastRequestParser

        cfg = Config()
        data = b"GET /path HTTP/1.1\r\nHost: example.com\r\n\r\n"
        parser = FastRequestParser(cfg, iter([data]), ('127.0.0.1', 8000))

        req = next(parser)
        assert req.method == "GET"
        assert req.path == "/path"
        assert req.version == (1, 1)
        assert ("HOST", "example.com") in req.headers

    def test_post_request_with_body(self):
        """FastRequest should parse POST request with body."""
        from gunicorn.http.fast_message import FastRequestParser

        cfg = Config()
        body = b"key=value"
        data = (
            b"POST /submit HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"Content-Type: application/x-www-form-urlencoded\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n"
            b"\r\n" + body
        )
        parser = FastRequestParser(cfg, iter([data]), ('127.0.0.1', 8000))

        req = next(parser)
        assert req.method == "POST"
        assert req.path == "/submit"
        assert req.body.read() == body

    def test_request_with_query_string(self):
        """FastRequest should parse query string correctly."""
        from gunicorn.http.fast_message import FastRequestParser

        cfg = Config()
        data = b"GET /search?q=test&page=1 HTTP/1.1\r\nHost: example.com\r\n\r\n"
        parser = FastRequestParser(cfg, iter([data]), ('127.0.0.1', 8000))

        req = next(parser)
        assert req.path == "/search"
        assert req.query == "q=test&page=1"

    def test_multiple_headers(self):
        """FastRequest should parse multiple headers."""
        from gunicorn.http.fast_message import FastRequestParser

        cfg = Config()
        data = (
            b"GET / HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"Accept: text/html\r\n"
            b"Accept-Language: en-US\r\n"
            b"User-Agent: TestClient/1.0\r\n"
            b"\r\n"
        )
        parser = FastRequestParser(cfg, iter([data]), ('127.0.0.1', 8000))

        req = next(parser)
        header_dict = dict(req.headers)
        assert header_dict["HOST"] == "example.com"
        assert header_dict["ACCEPT"] == "text/html"
        assert header_dict["ACCEPT-LANGUAGE"] == "en-US"
        assert header_dict["USER-AGENT"] == "TestClient/1.0"

    def test_http10_request(self):
        """FastRequest should parse HTTP/1.0 request."""
        from gunicorn.http.fast_message import FastRequestParser

        cfg = Config()
        data = b"GET / HTTP/1.0\r\nHost: example.com\r\n\r\n"
        parser = FastRequestParser(cfg, iter([data]), ('127.0.0.1', 8000))

        req = next(parser)
        assert req.version == (1, 0)


@pytest.mark.skipif(not FAST_PARSER_AVAILABLE,
                    reason="gunicorn_h1c not installed")
class TestFastAsyncRequestParsing:
    """Test FastAsyncRequest parsing functionality."""

    @pytest.fixture
    def event_loop(self):
        """Create an event loop for async tests."""
        loop = asyncio.new_event_loop()
        yield loop
        loop.close()

    @pytest.mark.asyncio
    async def test_simple_async_get_request(self):
        """FastAsyncRequest should parse a simple GET request."""
        from gunicorn.asgi.fast_message import FastAsyncRequest
        from gunicorn.asgi.unreader import AsyncUnreader

        cfg = Config()
        data = b"GET /path HTTP/1.1\r\nHost: example.com\r\n\r\n"

        class MockReader:
            def __init__(self, data):
                self._data = data
                self._read = False

            async def read(self, n=-1):
                if not self._read:
                    self._read = True
                    return self._data
                return b""

        reader = MockReader(data)
        unreader = AsyncUnreader(reader)

        req = await FastAsyncRequest.parse(cfg, unreader, ('127.0.0.1', 8000))
        assert req.method == "GET"
        assert req.path == "/path"
        assert req.version == (1, 1)

    @pytest.mark.asyncio
    async def test_async_request_with_headers(self):
        """FastAsyncRequest should parse headers correctly."""
        from gunicorn.asgi.fast_message import FastAsyncRequest
        from gunicorn.asgi.unreader import AsyncUnreader

        cfg = Config()
        data = (
            b"GET / HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"Content-Type: application/json\r\n"
            b"\r\n"
        )

        class MockReader:
            def __init__(self, data):
                self._data = data
                self._read = False

            async def read(self, n=-1):
                if not self._read:
                    self._read = True
                    return self._data
                return b""

        reader = MockReader(data)
        unreader = AsyncUnreader(reader)

        req = await FastAsyncRequest.parse(cfg, unreader, ('127.0.0.1', 8000))
        header_dict = dict(req.headers)
        assert header_dict["HOST"] == "example.com"
        assert header_dict["CONTENT-TYPE"] == "application/json"


@pytest.mark.skipif(not FAST_PARSER_AVAILABLE,
                    reason="gunicorn_h1c not installed")
class TestFastParserCompatibility:
    """Test that FastRequest produces same results as standard Request."""

    def test_parsing_compatibility(self):
        """FastRequest should produce same parsed values as Request."""
        from gunicorn.http.parser import RequestParser
        from gunicorn.http.fast_message import FastRequestParser

        cfg = Config()
        data = (
            b"POST /api/users?active=true HTTP/1.1\r\n"
            b"Host: api.example.com\r\n"
            b"Content-Type: application/json\r\n"
            b"Accept: application/json\r\n"
            b"Content-Length: 15\r\n"
            b"\r\n"
            b'{"name":"test"}'
        )

        # Parse with standard parser
        std_parser = RequestParser(cfg, iter([data]), ('127.0.0.1', 8000))
        std_req = next(std_parser)

        # Parse with fast parser
        fast_parser = FastRequestParser(cfg, iter([data]), ('127.0.0.1', 8000))
        fast_req = next(fast_parser)

        # Compare results
        assert fast_req.method == std_req.method
        assert fast_req.uri == std_req.uri
        assert fast_req.path == std_req.path
        assert fast_req.query == std_req.query
        assert fast_req.version == std_req.version
        assert fast_req.scheme == std_req.scheme

        # Compare headers (order may differ)
        std_headers = dict(std_req.headers)
        fast_headers = dict(fast_req.headers)
        assert fast_headers == std_headers

        # Compare body
        assert fast_req.body.read() == std_req.body.read()


class TestConfigHttpParser:
    """Test http_parser configuration setting."""

    def test_default_is_auto(self):
        """Default http_parser should be 'auto'."""
        cfg = Config()
        assert cfg.http_parser == 'auto'

    def test_set_python(self):
        """http_parser can be set to 'python'."""
        cfg = Config()
        cfg.set('http_parser', 'python')
        assert cfg.http_parser == 'python'

    def test_set_fast(self):
        """http_parser can be set to 'fast'."""
        cfg = Config()
        cfg.set('http_parser', 'fast')
        assert cfg.http_parser == 'fast'

    def test_set_auto(self):
        """http_parser can be set to 'auto'."""
        cfg = Config()
        cfg.set('http_parser', 'auto')
        assert cfg.http_parser == 'auto'

    def test_invalid_value_raises(self):
        """Invalid http_parser value should raise ValueError."""
        cfg = Config()
        with pytest.raises(ValueError):
            cfg.set('http_parser', 'invalid')

    def test_case_insensitive(self):
        """http_parser setting should be case-insensitive."""
        cfg = Config()
        cfg.set('http_parser', 'PYTHON')
        assert cfg.http_parser == 'python'

        cfg.set('http_parser', 'Fast')
        assert cfg.http_parser == 'fast'
