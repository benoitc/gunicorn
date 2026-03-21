#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Tests for PythonProtocol callback-based HTTP parser.
"""

import pytest
from gunicorn.asgi.parser import PythonProtocol, CallbackRequest, ParseError


class TestPythonProtocolBasic:
    """Test basic request parsing."""

    def test_simple_get_request(self):
        """Test parsing a simple GET request."""
        headers_complete = []
        message_complete = []

        parser = PythonProtocol(
            on_headers_complete=lambda: headers_complete.append(True),
            on_message_complete=lambda: message_complete.append(True),
        )

        data = b"GET /path HTTP/1.1\r\nHost: example.com\r\n\r\n"
        parser.feed(data)

        assert parser.method == b"GET"
        assert parser.path == b"/path"
        assert parser.http_version == (1, 1)
        assert len(parser.headers) == 1
        assert parser.headers[0] == (b"host", b"example.com")
        assert parser.is_complete is True
        assert len(headers_complete) == 1
        assert len(message_complete) == 1

    def test_get_with_query_string(self):
        """Test parsing GET with query string."""
        parser = PythonProtocol()

        data = b"GET /search?q=test&page=1 HTTP/1.1\r\nHost: example.com\r\n\r\n"
        parser.feed(data)

        assert parser.method == b"GET"
        assert parser.path == b"/search?q=test&page=1"
        assert parser.is_complete is True

    def test_http_10_request(self):
        """Test parsing HTTP/1.0 request."""
        parser = PythonProtocol()

        data = b"GET / HTTP/1.0\r\nHost: example.com\r\n\r\n"
        parser.feed(data)

        assert parser.http_version == (1, 0)
        assert parser.should_keep_alive is False  # HTTP/1.0 default

    def test_http_10_with_keepalive(self):
        """Test HTTP/1.0 with explicit keep-alive."""
        parser = PythonProtocol()

        data = b"GET / HTTP/1.0\r\nHost: example.com\r\nConnection: keep-alive\r\n\r\n"
        parser.feed(data)

        assert parser.http_version == (1, 0)
        assert parser.should_keep_alive is True

    def test_multiple_headers(self):
        """Test parsing multiple headers."""
        parser = PythonProtocol()

        data = (
            b"GET / HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"Accept: text/html\r\n"
            b"Accept-Language: en-US\r\n"
            b"User-Agent: Test/1.0\r\n"
            b"\r\n"
        )
        parser.feed(data)

        assert len(parser.headers) == 4
        header_names = [h[0] for h in parser.headers]
        assert b"host" in header_names
        assert b"accept" in header_names
        assert b"accept-language" in header_names
        assert b"user-agent" in header_names


class TestPythonProtocolBody:
    """Test request body parsing."""

    def test_post_with_content_length(self):
        """Test POST with Content-Length body."""
        body_chunks = []

        parser = PythonProtocol(
            on_body=lambda chunk: body_chunks.append(chunk),
        )

        data = (
            b"POST /submit HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"Content-Length: 13\r\n"
            b"\r\n"
            b"name=testuser"
        )
        parser.feed(data)

        assert parser.method == b"POST"
        assert parser.content_length == 13
        assert parser.is_complete is True
        assert b"".join(body_chunks) == b"name=testuser"

    def test_chunked_body(self):
        """Test chunked transfer encoding."""
        body_chunks = []

        parser = PythonProtocol(
            on_body=lambda chunk: body_chunks.append(chunk),
        )

        data = (
            b"POST / HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"5\r\nhello\r\n"
            b"6\r\n world\r\n"
            b"0\r\n\r\n"
        )
        parser.feed(data)

        assert parser.is_chunked is True
        assert parser.is_complete is True
        assert b"".join(body_chunks) == b"hello world"

    def test_chunked_with_extension(self):
        """Test chunked with chunk extension."""
        body_chunks = []

        parser = PythonProtocol(
            on_body=lambda chunk: body_chunks.append(chunk),
        )

        data = (
            b"POST / HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"5;ext=value\r\nhello\r\n"
            b"0\r\n\r\n"
        )
        parser.feed(data)

        assert b"".join(body_chunks) == b"hello"


class TestPythonProtocolIncremental:
    """Test incremental/partial data feeding."""

    def test_partial_request_line(self):
        """Test feeding partial request line."""
        parser = PythonProtocol()

        # Feed partial request line
        parser.feed(b"GET /path ")
        assert parser.method is None
        assert parser.is_complete is False

        # Complete the request line and headers
        parser.feed(b"HTTP/1.1\r\nHost: example.com\r\n\r\n")
        assert parser.method == b"GET"
        assert parser.is_complete is True

    def test_partial_headers(self):
        """Test feeding partial headers."""
        parser = PythonProtocol()

        parser.feed(b"GET / HTTP/1.1\r\n")
        parser.feed(b"Host: exa")
        assert parser.is_complete is False

        parser.feed(b"mple.com\r\n\r\n")
        assert parser.is_complete is True
        assert parser.headers[0] == (b"host", b"example.com")

    def test_partial_body(self):
        """Test feeding partial body."""
        body_chunks = []

        parser = PythonProtocol(
            on_body=lambda chunk: body_chunks.append(chunk),
        )

        parser.feed(
            b"POST / HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"Content-Length: 10\r\n"
            b"\r\n"
            b"hello"
        )
        assert parser.is_complete is False

        parser.feed(b"world")
        assert parser.is_complete is True
        assert b"".join(body_chunks) == b"helloworld"

    def test_partial_chunked_body(self):
        """Test feeding partial chunked body."""
        body_chunks = []

        parser = PythonProtocol(
            on_body=lambda chunk: body_chunks.append(chunk),
        )

        parser.feed(
            b"POST / HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"5\r\nhel"
        )
        assert parser.is_complete is False

        parser.feed(b"lo\r\n0\r\n\r\n")
        assert parser.is_complete is True
        assert b"".join(body_chunks) == b"hello"


class TestPythonProtocolErrors:
    """Test error handling."""

    def test_invalid_request_line(self):
        """Test invalid request line."""
        parser = PythonProtocol()

        with pytest.raises(ParseError):
            parser.feed(b"INVALID\r\n")

    def test_invalid_header(self):
        """Test invalid header (no colon)."""
        parser = PythonProtocol()

        with pytest.raises(ParseError):
            parser.feed(b"GET / HTTP/1.1\r\nBadHeader\r\n\r\n")

    def test_unsupported_http_version(self):
        """Test unsupported HTTP version."""
        parser = PythonProtocol()

        with pytest.raises(ParseError):
            parser.feed(b"GET / HTTP/2.0\r\n\r\n")

    def test_invalid_chunk_size(self):
        """Test invalid chunk size."""
        parser = PythonProtocol()

        with pytest.raises(ParseError):
            parser.feed(
                b"POST / HTTP/1.1\r\n"
                b"Transfer-Encoding: chunked\r\n"
                b"\r\n"
                b"XYZ\r\n"  # Invalid hex
            )


class TestPythonProtocolReset:
    """Test parser reset for keepalive."""

    def test_reset_clears_state(self):
        """Test that reset clears all state."""
        parser = PythonProtocol()

        parser.feed(b"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n")
        assert parser.is_complete is True
        assert parser.method == b"GET"

        parser.reset()

        assert parser.method is None
        assert parser.path is None
        assert parser.http_version is None
        assert parser.headers == []
        assert parser.content_length is None
        assert parser.is_chunked is False
        assert parser.is_complete is False

    def test_multiple_requests_keepalive(self):
        """Test handling multiple requests on keepalive connection."""
        parser = PythonProtocol()

        # First request
        parser.feed(b"GET /first HTTP/1.1\r\nHost: example.com\r\n\r\n")
        assert parser.path == b"/first"
        assert parser.is_complete is True

        parser.reset()

        # Second request
        parser.feed(b"GET /second HTTP/1.1\r\nHost: example.com\r\n\r\n")
        assert parser.path == b"/second"
        assert parser.is_complete is True


class TestPythonProtocolCallbacks:
    """Test callback firing."""

    def test_all_callbacks(self):
        """Test all callbacks fire in correct order."""
        events = []

        parser = PythonProtocol(
            on_message_begin=lambda: events.append("begin"),
            on_url=lambda url: events.append(("url", url)),
            on_header=lambda n, v: events.append(("header", n, v)),
            on_headers_complete=lambda: events.append("headers_complete"),
            on_body=lambda chunk: events.append(("body", chunk)),
            on_message_complete=lambda: events.append("complete"),
        )

        parser.feed(
            b"POST / HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"Content-Length: 5\r\n"
            b"\r\n"
            b"hello"
        )

        assert events[0] == "begin"
        assert events[1] == ("url", b"/")
        assert events[2] == ("header", b"host", b"example.com")
        assert events[3] == ("header", b"content-length", b"5")
        assert events[4] == "headers_complete"
        assert events[5] == ("body", b"hello")
        assert events[6] == "complete"

    def test_skip_body_callback(self):
        """Test on_headers_complete returning True skips body."""
        body_chunks = []

        parser = PythonProtocol(
            on_headers_complete=lambda: True,  # Skip body
            on_body=lambda chunk: body_chunks.append(chunk),
        )

        parser.feed(
            b"POST / HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"Content-Length: 5\r\n"
            b"\r\n"
            b"hello"
        )

        # Body should be skipped
        assert parser.is_complete is True
        assert len(body_chunks) == 0


class TestCallbackRequest:
    """Test CallbackRequest adapter."""

    def test_from_parser_simple(self):
        """Test creating request from parser state."""
        parser = PythonProtocol()
        parser.feed(b"GET /path?query=value HTTP/1.1\r\nHost: example.com\r\n\r\n")

        request = CallbackRequest.from_parser(parser)

        assert request.method == "GET"
        assert request.path == "/path"
        assert request.query == "query=value"
        assert request.uri == "/path?query=value"
        assert request.version == (1, 1)
        assert request.scheme == "http"

    def test_from_parser_ssl(self):
        """Test SSL scheme detection."""
        parser = PythonProtocol()
        parser.feed(b"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n")

        request = CallbackRequest.from_parser(parser, is_ssl=True)

        assert request.scheme == "https"

    def test_from_parser_headers(self):
        """Test header conversion."""
        parser = PythonProtocol()
        parser.feed(
            b"GET / HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"Content-Type: text/plain\r\n"
            b"\r\n"
        )

        request = CallbackRequest.from_parser(parser)

        # String headers (uppercase)
        assert ("HOST", "example.com") in request.headers
        assert ("CONTENT-TYPE", "text/plain") in request.headers

        # Bytes headers (lowercase)
        assert (b"host", b"example.com") in request.headers_bytes
        assert (b"content-type", b"text/plain") in request.headers_bytes

    def test_from_parser_body_info(self):
        """Test body info extraction."""
        parser = PythonProtocol()
        parser.feed(
            b"POST / HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"Content-Length: 10\r\n"
            b"\r\n"
        )

        request = CallbackRequest.from_parser(parser)

        assert request.content_length == 10
        assert request.chunked is False

    def test_from_parser_chunked(self):
        """Test chunked transfer detection."""
        parser = PythonProtocol()
        parser.feed(
            b"POST / HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
        )

        request = CallbackRequest.from_parser(parser)

        assert request.chunked is True

    def test_should_close(self):
        """Test should_close method."""
        # HTTP/1.1 with Connection: close
        parser = PythonProtocol()
        parser.feed(b"GET / HTTP/1.1\r\nConnection: close\r\n\r\n")
        request = CallbackRequest.from_parser(parser)
        assert request.should_close() is True

        # HTTP/1.1 keep-alive (default)
        parser = PythonProtocol()
        parser.feed(b"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n")
        request = CallbackRequest.from_parser(parser)
        assert request.should_close() is False

        # HTTP/1.0 (default close)
        parser = PythonProtocol()
        parser.feed(b"GET / HTTP/1.0\r\n\r\n")
        request = CallbackRequest.from_parser(parser)
        assert request.should_close() is True

    def test_get_header(self):
        """Test get_header method."""
        parser = PythonProtocol()
        parser.feed(
            b"GET / HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"X-Custom: value\r\n"
            b"\r\n"
        )

        request = CallbackRequest.from_parser(parser)

        assert request.get_header("Host") == "example.com"
        assert request.get_header("x-custom") == "value"
        assert request.get_header("X-CUSTOM") == "value"
        assert request.get_header("X-Missing") is None

    def test_expect_100_continue(self):
        """Test Expect: 100-continue detection."""
        parser = PythonProtocol()
        parser.feed(
            b"POST / HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"Expect: 100-continue\r\n"
            b"Content-Length: 10\r\n"
            b"\r\n"
        )

        request = CallbackRequest.from_parser(parser)

        assert request._expect_100_continue is True


class TestPythonProtocolConnectionClose:
    """Test connection close handling."""

    def test_connection_close_header(self):
        """Test Connection: close header."""
        parser = PythonProtocol()
        parser.feed(b"GET / HTTP/1.1\r\nConnection: close\r\n\r\n")

        assert parser.should_keep_alive is False

    def test_connection_keepalive_header(self):
        """Test Connection: keep-alive header."""
        parser = PythonProtocol()
        parser.feed(b"GET / HTTP/1.1\r\nConnection: keep-alive\r\n\r\n")

        assert parser.should_keep_alive is True

    def test_http11_default_keepalive(self):
        """Test HTTP/1.1 defaults to keep-alive."""
        parser = PythonProtocol()
        parser.feed(b"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n")

        assert parser.should_keep_alive is True

    def test_http10_default_close(self):
        """Test HTTP/1.0 defaults to close."""
        parser = PythonProtocol()
        parser.feed(b"GET / HTTP/1.0\r\nHost: example.com\r\n\r\n")

        assert parser.should_keep_alive is False
