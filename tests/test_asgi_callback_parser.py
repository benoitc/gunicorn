#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for ASGI callback parsers.

Tests both PythonProtocol and H1CProtocol (if available) to ensure
consistent behavior across implementations.
"""

from gunicorn.asgi.parser import PythonProtocol


def get_parser_class(http_parser):
    """Get the appropriate parser class for the test parameter."""
    if http_parser == "fast":
        from gunicorn_h1c import H1CProtocol
        return H1CProtocol
    return PythonProtocol


def normalize_headers(headers):
    """Normalize headers to lowercase names for comparison.

    H1CProtocol preserves original case, PythonProtocol lowercases.
    """
    return {name.lower(): value for name, value in headers}


class TestRequestLineParsing:
    """Test request line parsing for both implementations."""

    def test_simple_get(self, http_parser):
        """Parse a simple GET request."""
        parser_class = get_parser_class(http_parser)
        events = []

        parser = parser_class(
            on_message_begin=lambda: events.append('begin'),
            on_url=lambda url: events.append(('url', url)),
            on_headers_complete=lambda: events.append('headers_complete'),
            on_message_complete=lambda: events.append('complete'),
        )

        parser.feed(b"GET /path HTTP/1.1\r\n\r\n")

        assert parser.method == b"GET"
        assert parser.path == b"/path"
        assert parser.http_version == (1, 1)
        assert parser.is_complete
        assert 'begin' in events
        assert ('url', b'/path') in events
        assert 'complete' in events

    def test_post_with_query(self, http_parser):
        """Parse a POST request with query string."""
        parser_class = get_parser_class(http_parser)

        parser = parser_class()
        parser.feed(b"POST /api/data?foo=bar&baz=qux HTTP/1.1\r\n\r\n")

        assert parser.method == b"POST"
        assert parser.path == b"/api/data?foo=bar&baz=qux"
        assert parser.http_version == (1, 1)
        assert parser.is_complete

    def test_http_10_version(self, http_parser):
        """Parse HTTP/1.0 request."""
        parser_class = get_parser_class(http_parser)

        parser = parser_class()
        parser.feed(b"GET / HTTP/1.0\r\n\r\n")

        assert parser.method == b"GET"
        assert parser.http_version == (1, 0)
        assert parser.is_complete

    def test_various_methods(self, http_parser):
        """Test parsing various HTTP methods."""
        parser_class = get_parser_class(http_parser)
        methods = [b"GET", b"POST", b"PUT", b"DELETE", b"PATCH", b"HEAD", b"OPTIONS"]

        for method in methods:
            parser = parser_class()
            parser.feed(method + b" / HTTP/1.1\r\n\r\n")
            assert parser.method == method


class TestHeaderParsing:
    """Test header parsing for both implementations."""

    def test_single_header(self, http_parser):
        """Parse a request with single header."""
        parser_class = get_parser_class(http_parser)
        headers = []

        parser = parser_class(
            on_header=lambda n, v: headers.append((n, v)),
        )
        parser.feed(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")

        assert len(parser.headers) == 1
        header_dict = normalize_headers(parser.headers)
        assert header_dict[b"host"] == b"localhost"
        callback_dict = normalize_headers(headers)
        assert callback_dict[b"host"] == b"localhost"

    def test_multiple_headers(self, http_parser):
        """Parse a request with multiple headers."""
        parser_class = get_parser_class(http_parser)

        parser = parser_class()
        parser.feed(
            b"GET / HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"User-Agent: TestClient\r\n"
            b"Accept: */*\r\n"
            b"\r\n"
        )

        assert len(parser.headers) == 3
        header_dict = normalize_headers(parser.headers)
        assert header_dict[b"host"] == b"localhost"
        assert header_dict[b"user-agent"] == b"TestClient"
        assert header_dict[b"accept"] == b"*/*"

    def test_header_with_spaces(self, http_parser):
        """Parse headers with leading/trailing spaces in values."""
        parser_class = get_parser_class(http_parser)

        parser = parser_class()
        parser.feed(
            b"GET / HTTP/1.1\r\n"
            b"Host:   localhost  \r\n"
            b"\r\n"
        )

        header_dict = normalize_headers(parser.headers)
        assert header_dict[b"host"] == b"localhost"

    def test_empty_header_value(self, http_parser):
        """Parse header with empty value."""
        parser_class = get_parser_class(http_parser)

        parser = parser_class()
        parser.feed(
            b"GET / HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"X-Empty:\r\n"
            b"\r\n"
        )

        header_dict = normalize_headers(parser.headers)
        assert header_dict[b"x-empty"] == b""

    def test_large_header_value(self, http_parser):
        """Parse header with large value."""
        parser_class = get_parser_class(http_parser)

        large_value = b"x" * 4096

        parser = parser_class()
        parser.feed(
            b"GET / HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"X-Large: " + large_value + b"\r\n"
            b"\r\n"
        )

        header_dict = normalize_headers(parser.headers)
        assert header_dict[b"x-large"] == large_value


class TestBodyHandling:
    """Test body parsing for both implementations."""

    def test_content_length_body(self, http_parser):
        """Parse request with Content-Length body."""
        parser_class = get_parser_class(http_parser)
        body_chunks = []

        parser = parser_class(
            on_body=lambda chunk: body_chunks.append(chunk),
        )
        parser.feed(
            b"POST /data HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Length: 13\r\n"
            b"\r\n"
            b"Hello, World!"
        )

        assert parser.content_length == 13
        assert not parser.is_chunked
        assert b"".join(body_chunks) == b"Hello, World!"
        assert parser.is_complete

    def test_content_length_incremental(self, http_parser):
        """Parse body arriving in multiple chunks."""
        parser_class = get_parser_class(http_parser)
        body_chunks = []

        parser = parser_class(
            on_body=lambda chunk: body_chunks.append(chunk),
        )

        # Send headers
        parser.feed(
            b"POST /data HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Length: 10\r\n"
            b"\r\n"
        )
        assert not parser.is_complete

        # Send body in parts
        parser.feed(b"Hello")
        assert not parser.is_complete
        parser.feed(b"World")
        assert parser.is_complete

        assert b"".join(body_chunks) == b"HelloWorld"

    def test_chunked_encoding(self, http_parser):
        """Parse chunked transfer-encoded body."""
        parser_class = get_parser_class(http_parser)
        body_chunks = []

        parser = parser_class(
            on_body=lambda chunk: body_chunks.append(chunk),
        )
        parser.feed(
            b"POST /data HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"5\r\n"
            b"Hello\r\n"
            b"6\r\n"
            b"World!\r\n"
            b"0\r\n"
            b"\r\n"
        )

        assert parser.is_chunked
        assert b"".join(body_chunks) == b"HelloWorld!"
        assert parser.is_complete

    def test_chunked_with_extensions(self, http_parser):
        """Parse chunked body with chunk extensions."""
        parser_class = get_parser_class(http_parser)
        body_chunks = []

        parser = parser_class(
            on_body=lambda chunk: body_chunks.append(chunk),
        )
        parser.feed(
            b"POST /data HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"5;ext=value\r\n"
            b"Hello\r\n"
            b"0\r\n"
            b"\r\n"
        )

        assert b"".join(body_chunks) == b"Hello"
        assert parser.is_complete

    def test_no_body_get(self, http_parser):
        """GET request has no body."""
        parser_class = get_parser_class(http_parser)
        body_chunks = []

        parser = parser_class(
            on_body=lambda chunk: body_chunks.append(chunk),
        )
        parser.feed(
            b"GET / HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"\r\n"
        )

        assert parser.content_length is None
        assert not parser.is_chunked
        assert body_chunks == []
        assert parser.is_complete


class TestConnectionHandling:
    """Test connection handling and keep-alive for both implementations."""

    def test_http11_keepalive_default(self, http_parser):
        """HTTP/1.1 defaults to keep-alive."""
        parser_class = get_parser_class(http_parser)

        parser = parser_class()
        parser.feed(
            b"GET / HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"\r\n"
        )

        assert parser.should_keep_alive is True

    def test_http11_connection_close(self, http_parser):
        """HTTP/1.1 with Connection: close."""
        parser_class = get_parser_class(http_parser)

        parser = parser_class()
        parser.feed(
            b"GET / HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Connection: close\r\n"
            b"\r\n"
        )

        assert parser.should_keep_alive is False

    def test_http10_no_keepalive(self, http_parser):
        """HTTP/1.0 defaults to no keep-alive."""
        parser_class = get_parser_class(http_parser)

        parser = parser_class()
        parser.feed(
            b"GET / HTTP/1.0\r\n"
            b"Host: localhost\r\n"
            b"\r\n"
        )

        assert parser.should_keep_alive is False

    def test_http10_with_keepalive(self, http_parser):
        """HTTP/1.0 with Connection: keep-alive."""
        parser_class = get_parser_class(http_parser)

        parser = parser_class()
        parser.feed(
            b"GET / HTTP/1.0\r\n"
            b"Host: localhost\r\n"
            b"Connection: keep-alive\r\n"
            b"\r\n"
        )

        assert parser.should_keep_alive is True


class TestParserReset:
    """Test parser reset for keep-alive connections."""

    def test_reset_after_request(self, http_parser):
        """Parser can be reset for a new request."""
        parser_class = get_parser_class(http_parser)
        complete_count = [0]

        parser = parser_class(
            on_message_complete=lambda: complete_count.__setitem__(0, complete_count[0] + 1),
        )

        # First request
        parser.feed(b"GET /first HTTP/1.1\r\n\r\n")
        assert parser.path == b"/first"
        assert parser.is_complete

        # Reset and send second request
        parser.reset()
        assert not parser.is_complete
        # H1CProtocol resets to b'', PythonProtocol to None
        assert not parser.method

        parser.feed(b"GET /second HTTP/1.1\r\n\r\n")
        assert parser.path == b"/second"
        assert parser.is_complete

        assert complete_count[0] == 2


class TestCallbackBehavior:
    """Test callback behavior consistency."""

    def test_all_callbacks_fire(self, http_parser):
        """All callbacks fire in correct order."""
        parser_class = get_parser_class(http_parser)
        events = []

        parser = parser_class(
            on_message_begin=lambda: events.append('begin'),
            on_url=lambda url: events.append(('url', url)),
            on_header=lambda n, v: events.append(('header', n.lower(), v)),
            on_headers_complete=lambda: events.append('headers_complete'),
            on_body=lambda chunk: events.append(('body', chunk)),
            on_message_complete=lambda: events.append('complete'),
        )

        parser.feed(
            b"POST / HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Length: 4\r\n"
            b"\r\n"
            b"test"
        )

        assert events[0] == 'begin'
        assert events[1] == ('url', b'/')
        assert ('header', b'host', b'localhost') in events
        assert ('header', b'content-length', b'4') in events
        assert 'headers_complete' in events
        assert ('body', b'test') in events
        assert events[-1] == 'complete'

    def test_skip_body_on_headers_complete(self, http_parser):
        """Return True from on_headers_complete skips body parsing."""
        parser_class = get_parser_class(http_parser)
        body_chunks = []

        parser = parser_class(
            on_headers_complete=lambda: True,  # Skip body
            on_body=lambda chunk: body_chunks.append(chunk),
        )

        parser.feed(
            b"POST / HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Content-Length: 10\r\n"
            b"\r\n"
            b"0123456789"
        )

        assert parser.is_complete
        assert body_chunks == []  # Body was skipped


class TestCallbackRequest:
    """Test CallbackRequest building from parser state."""

    def test_non_ascii_path_decoding(self, http_parser):
        """Test that percent-encoded UTF-8 paths are decoded correctly.

        Per ASGI spec:
        - path: percent-decoded UTF-8 string
        - raw_path: original bytes as received
        """
        from gunicorn.asgi.parser import CallbackRequest

        parser_class = get_parser_class(http_parser)
        parser = parser_class()

        # ö = %C3%B6 in UTF-8 percent-encoded
        parser.feed(b"GET /%C3%B6/ HTTP/1.1\r\nHost: test\r\n\r\n")

        request = CallbackRequest.from_parser(parser)

        # path should be percent-decoded UTF-8 string
        assert request.path == "/\u00f6/"  # /ö/
        # raw_path should be original bytes
        assert request.raw_path == b"/%C3%B6/"

    def test_non_ascii_path_with_query(self, http_parser):
        """Test percent-encoded path with query string."""
        from gunicorn.asgi.parser import CallbackRequest

        parser_class = get_parser_class(http_parser)
        parser = parser_class()

        # Japanese: /日本/ = /%E6%97%A5%E6%9C%AC/
        parser.feed(b"GET /%E6%97%A5%E6%9C%AC/?q=test HTTP/1.1\r\nHost: test\r\n\r\n")

        request = CallbackRequest.from_parser(parser)

        assert request.path == "/\u65e5\u672c/"  # /日本/
        assert request.raw_path == b"/%E6%97%A5%E6%9C%AC/"
        assert request.query == "q=test"

    def test_invalid_utf8_path(self, http_parser):
        """Test that invalid UTF-8 sequences use replacement character."""
        from gunicorn.asgi.parser import CallbackRequest

        parser_class = get_parser_class(http_parser)
        parser = parser_class()

        # %FF is invalid UTF-8
        parser.feed(b"GET /%FF HTTP/1.1\r\nHost: test\r\n\r\n")

        request = CallbackRequest.from_parser(parser)

        # Should use replacement character for invalid bytes
        assert "\ufffd" in request.path
        assert request.raw_path == b"/%FF"

    def test_simple_ascii_path(self, http_parser):
        """Test that simple ASCII paths work unchanged."""
        from gunicorn.asgi.parser import CallbackRequest

        parser_class = get_parser_class(http_parser)
        parser = parser_class()

        parser.feed(b"GET /api/users HTTP/1.1\r\nHost: test\r\n\r\n")

        request = CallbackRequest.from_parser(parser)

        assert request.path == "/api/users"
        assert request.raw_path == b"/api/users"

    def test_percent_encoded_ascii(self, http_parser):
        """Test percent-encoded ASCII characters."""
        from gunicorn.asgi.parser import CallbackRequest

        parser_class = get_parser_class(http_parser)
        parser = parser_class()

        # Space encoded as %20
        parser.feed(b"GET /hello%20world HTTP/1.1\r\nHost: test\r\n\r\n")

        request = CallbackRequest.from_parser(parser)

        assert request.path == "/hello world"
        assert request.raw_path == b"/hello%20world"
