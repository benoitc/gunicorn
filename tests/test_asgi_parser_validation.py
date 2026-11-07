#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for ASGI callback parser header validation.

These tests verify that PythonProtocol correctly validates HTTP headers
and body framing according to RFC 9110 and RFC 9112.
"""

import pytest

from gunicorn.asgi.parser import (
    PythonProtocol,
    InvalidHeader,
    InvalidHeaderName,
    InvalidChunkSize,
    ChunkMissingTerminator,
    InvalidRequestLine,
    LimitRequestHeaders,
    LimitRequestLine,
    UnsupportedTransferCoding,
    ParseError,
)


class TestContentLengthTransferEncodingConflict:
    """Test rejection of requests with both CL and TE headers."""

    def test_cl_te_conflict_rejected(self):
        """Request with both Content-Length and Transfer-Encoding must be rejected."""
        parser = PythonProtocol()

        with pytest.raises(InvalidHeader, match="Content-Length with Transfer-Encoding"):
            parser.feed(
                b"POST /test HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"Content-Length: 10\r\n"
                b"Transfer-Encoding: chunked\r\n"
                b"\r\n"
            )

    def test_te_cl_conflict_rejected(self):
        """Order doesn't matter - TE before CL also rejected."""
        parser = PythonProtocol()

        with pytest.raises(InvalidHeader, match="Content-Length with Transfer-Encoding"):
            parser.feed(
                b"POST /test HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"Transfer-Encoding: chunked\r\n"
                b"Content-Length: 10\r\n"
                b"\r\n"
            )

    def test_invalid_te_with_cl_rejected(self):
        """Invalid T-E value combined with CL must be rejected."""
        parser = PythonProtocol()

        # This should fail due to invalid T-E value (identity;chunked=not)
        with pytest.raises((InvalidHeader, UnsupportedTransferCoding)):
            parser.feed(
                b"POST /headers HTTP/1.0\r\n"
                b"Connection: keep-alive\r\n"
                b"Transfer-Encoding: identity;chunked=not\r\n"
                b"Content-Length: -999\r\n"
                b"\r\n"
            )


class TestDuplicateContentLength:
    """Test rejection of duplicate Content-Length headers."""

    def test_duplicate_cl_rejected(self):
        """Duplicate Content-Length headers must be rejected."""
        parser = PythonProtocol()

        with pytest.raises(InvalidHeader, match="Duplicate Content-Length"):
            parser.feed(
                b"POST /test HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"Content-Length: 10\r\n"
                b"Content-Length: 10\r\n"
                b"\r\n"
            )

    def test_different_cl_values_rejected(self):
        """Different Content-Length values must be rejected."""
        parser = PythonProtocol()

        with pytest.raises(InvalidHeader, match="Duplicate Content-Length"):
            parser.feed(
                b"POST /test HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"Content-Length: 10\r\n"
                b"Content-Length: 20\r\n"
                b"\r\n"
            )

    def test_negative_cl_rejected(self):
        """Negative Content-Length must be rejected."""
        parser = PythonProtocol()

        with pytest.raises(InvalidHeader, match="Invalid Content-Length"):
            parser.feed(
                b"POST /test HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"Content-Length: -999\r\n"
                b"\r\n"
            )

    @pytest.mark.parametrize("value", [b"+5", b"1_0"])
    def test_non_digit_cl_rejected(self, value):
        """Content-Length is 1*DIGIT; forms int() alone would take are rejected."""
        parser = PythonProtocol()

        with pytest.raises(InvalidHeader, match="Invalid Content-Length"):
            parser.feed(
                b"POST /test HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"Content-Length: " + value + b"\r\n"
                b"\r\n"
            )

    def test_non_numeric_cl_rejected(self):
        """Non-numeric Content-Length must be rejected."""
        parser = PythonProtocol()

        with pytest.raises(InvalidHeader, match="Invalid Content-Length"):
            parser.feed(
                b"POST /test HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"Content-Length: abc\r\n"
                b"\r\n"
            )

    def test_cl_with_spaces_rejected(self):
        """Content-Length with embedded spaces must be rejected."""
        parser = PythonProtocol()

        with pytest.raises(InvalidHeader):
            parser.feed(
                b"GET /test HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"Content-Length: 0 1\r\n"
                b"\r\n"
            )


class TestChunkedInHTTP10:
    """Test rejection of chunked encoding in HTTP/1.0."""

    def test_chunked_http10_rejected(self):
        """Chunked Transfer-Encoding in HTTP/1.0 must be rejected."""
        parser = PythonProtocol()

        with pytest.raises(InvalidHeader, match="HTTP/1.0"):
            parser.feed(
                b"POST /test HTTP/1.0\r\n"
                b"Host: localhost\r\n"
                b"Transfer-Encoding: chunked\r\n"
                b"\r\n"
            )


class TestTransferEncodingValidation:
    """Test proper validation of Transfer-Encoding header values."""

    @pytest.mark.parametrize("ws", [b"\x0b", b"\x0c", b"\x85", b"\xa0"])
    def test_non_http_whitespace_rejected(self, ws):
        """Only SP/HTAB are whitespace around Transfer-Encoding tokens."""
        parser = PythonProtocol()

        with pytest.raises(ParseError):
            parser.feed(
                b"POST /test HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"Transfer-Encoding: chunked" + ws + b"\r\n"
                b"\r\n"
                b"0\r\n\r\n"
            )

    def test_stacked_chunked_rejected(self):
        """Stacked chunked encoding must be rejected."""
        parser = PythonProtocol()

        with pytest.raises(InvalidHeader, match="Stacked chunked"):
            parser.feed(
                b"POST /test HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"Transfer-Encoding: chunked, chunked\r\n"
                b"\r\n"
            )

    def test_chunked_then_identity_rejected(self):
        """Identity after chunked must be rejected."""
        parser = PythonProtocol()

        with pytest.raises(InvalidHeader, match="Invalid Transfer-Encoding after chunked"):
            parser.feed(
                b"POST /test HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"Transfer-Encoding: chunked, identity\r\n"
                b"\r\n"
            )

    def test_chunked_then_gzip_rejected(self):
        """Compression after chunked must be rejected."""
        parser = PythonProtocol()

        with pytest.raises(InvalidHeader, match="Invalid Transfer-Encoding after chunked"):
            parser.feed(
                b"POST /test HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"Transfer-Encoding: chunked, gzip\r\n"
                b"\r\n"
            )

    def test_unknown_transfer_coding_rejected(self):
        """Unknown transfer codings must be rejected."""
        parser = PythonProtocol()

        with pytest.raises(UnsupportedTransferCoding):
            parser.feed(
                b"POST /test HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"Transfer-Encoding: bogus\r\n"
                b"\r\n"
            )

    def test_te_with_parameters_rejected(self):
        """Transfer-Encoding with parameters (like identity;chunked=not) must be rejected."""
        parser = PythonProtocol()

        # "identity;chunked=not" is not a valid transfer coding
        with pytest.raises(UnsupportedTransferCoding):
            parser.feed(
                b"POST /test HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"Transfer-Encoding: identity;chunked=not\r\n"
                b"\r\n"
            )

    def test_te_with_tab_prefix_valid_chunked(self):
        """Tab before 'chunked' is stripped, value should be valid."""
        parser = PythonProtocol()

        # Tab is stripped during header parsing, so this is actually valid
        # But if combined with CL, it should still be rejected
        with pytest.raises(InvalidHeader, match="Content-Length with Transfer-Encoding"):
            parser.feed(
                b"POST /test HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"Content-Length: 12\r\n"
                b"Transfer-Encoding: \tchunked\r\n"
                b"\r\n"
            )

    def test_valid_chunked_accepted(self):
        """Valid chunked request should be accepted."""
        parser = PythonProtocol()

        parser.feed(
            b"POST /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"5\r\n"
            b"hello\r\n"
            b"0\r\n"
            b"\r\n"
        )

        assert parser.is_chunked
        assert parser.is_complete

    def test_valid_identity_then_chunked(self):
        """identity, chunked is valid per RFC."""
        parser = PythonProtocol()

        parser.feed(
            b"POST /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Transfer-Encoding: identity, chunked\r\n"
            b"\r\n"
            b"5\r\n"
            b"hello\r\n"
            b"0\r\n"
            b"\r\n"
        )

        assert parser.is_chunked
        assert parser.is_complete


class TestChunkSizeValidation:
    """Test strict validation of chunk sizes."""

    def test_chunk_size_with_leading_space_rejected(self):
        """Leading space in chunk size must be rejected."""
        parser = PythonProtocol()

        parser.feed(
            b"POST /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
        )

        with pytest.raises(InvalidChunkSize, match="Whitespace"):
            parser.feed(b" 5\r\nhello\r\n0\r\n\r\n")

    def test_chunk_size_with_trailing_space_rejected(self):
        """Trailing space in chunk size must be rejected."""
        parser = PythonProtocol()

        parser.feed(
            b"POST /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
        )

        with pytest.raises(InvalidChunkSize, match="Whitespace"):
            parser.feed(b"5 \r\nhello\r\n0\r\n\r\n")

    def test_chunk_size_with_tab_rejected(self):
        """Tab in chunk size must be rejected."""
        parser = PythonProtocol()

        parser.feed(
            b"POST /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
        )

        with pytest.raises(InvalidChunkSize):
            parser.feed(b"\t5\r\nhello\r\n0\r\n\r\n")

    def test_chunk_size_with_underscore_rejected(self):
        """Underscore in chunk size must be rejected."""
        parser = PythonProtocol()

        parser.feed(
            b"POST /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
        )

        with pytest.raises(InvalidChunkSize, match="Invalid character"):
            parser.feed(b"6_0\r\n" + b"x" * 96 + b"\r\n0\r\n\r\n")

    def test_empty_chunk_size_rejected(self):
        """Empty chunk size must be rejected."""
        parser = PythonProtocol()

        parser.feed(
            b"POST /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
        )

        with pytest.raises(InvalidChunkSize, match="Empty"):
            parser.feed(b"\r\nhello\r\n0\r\n\r\n")

    def test_valid_chunk_sizes(self):
        """Valid hex chunk sizes should work."""
        parser = PythonProtocol()
        body_chunks = []

        parser = PythonProtocol(
            on_body=lambda chunk: body_chunks.append(chunk),
        )

        parser.feed(
            b"POST /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"a\r\n"  # 10 in hex
            b"0123456789\r\n"
            b"0\r\n"
            b"\r\n"
        )

        assert parser.is_complete
        assert b"".join(body_chunks) == b"0123456789"

    def test_chunk_extension_accepted(self):
        """Chunk extensions after semicolon should be accepted."""
        parser = PythonProtocol()
        body_chunks = []

        parser = PythonProtocol(
            on_body=lambda chunk: body_chunks.append(chunk),
        )

        parser.feed(
            b"POST /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"5;ext=value\r\n"
            b"hello\r\n"
            b"0\r\n"
            b"\r\n"
        )

        assert parser.is_complete
        assert b"".join(body_chunks) == b"hello"


class TestChunkTerminator:
    """Test strict validation of the CRLF that terminates chunk data."""

    def test_bad_chunk_terminator_rejected(self):
        """Non-CRLF bytes after chunk data must be rejected, not skipped."""
        body_chunks = []
        parser = PythonProtocol(
            on_body=lambda chunk: body_chunks.append(chunk),
        )

        parser.feed(
            b"POST /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
        )

        # "hello" is 5 bytes, followed by "XX" instead of CRLF. A lax parser
        # would treat "XX" as the terminator and keep reading "3\r\nABC..."
        # as a second chunk, framing the body differently from a strict peer.
        with pytest.raises(ChunkMissingTerminator):
            parser.feed(b"5\r\nhelloXX3\r\nABC\r\n0\r\n\r\n")

    def test_valid_chunk_terminator_accepted(self):
        """A proper CRLF terminator between chunks still works."""
        body_chunks = []
        parser = PythonProtocol(
            on_body=lambda chunk: body_chunks.append(chunk),
        )

        parser.feed(
            b"POST /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"5\r\nhello\r\n"
            b"3\r\nABC\r\n"
            b"0\r\n\r\n"
        )

        assert parser.is_complete
        assert b"".join(body_chunks) == b"helloABC"


class TestMultipleTransferEncodingHeaders:
    """Test handling of multiple Transfer-Encoding headers."""

    def test_multiple_te_headers_with_chunked(self):
        """Multiple T-E headers that result in chunked should work."""
        parser = PythonProtocol()

        # This tests the iteration over headers - each T-E header is processed
        parser.feed(
            b"POST /test HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Transfer-Encoding: identity\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"5\r\n"
            b"hello\r\n"
            b"0\r\n"
            b"\r\n"
        )

        assert parser.is_chunked
        assert parser.is_complete

    def test_multiple_te_headers_double_chunked_rejected(self):
        """Multiple T-E headers both with chunked should be rejected."""
        parser = PythonProtocol()

        with pytest.raises(InvalidHeader, match="Stacked chunked"):
            parser.feed(
                b"POST /test HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"Transfer-Encoding: chunked\r\n"
                b"Transfer-Encoding: chunked\r\n"
                b"\r\n"
            )


class TestHeaderNameWhitespace:
    """Whitespace between field name and colon must be rejected (RFC 9112 5.1)."""

    def test_space_before_colon_rejected(self):
        """A space before the colon must not be stripped into a valid name."""
        parser = PythonProtocol()

        with pytest.raises(InvalidHeaderName):
            parser.feed(
                b"POST /test HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"Transfer-Encoding : chunked\r\n"
                b"\r\n"
            )

    def test_tab_before_colon_rejected(self):
        """A tab before the colon must not be stripped into a valid name."""
        parser = PythonProtocol()

        with pytest.raises(InvalidHeaderName):
            parser.feed(
                b"POST /test HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"Content-Length\t: 10\r\n"
                b"\r\n"
            )

    def test_leading_whitespace_name_rejected(self):
        """A leading-space line must not be accepted as a framing header."""
        parser = PythonProtocol()

        with pytest.raises(InvalidHeaderName):
            parser.feed(
                b"POST /test HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b" Content-Length: 10\r\n"
                b"\r\n"
            )

class TestRequestTargetControls:
    """RFC 9112: request-target must not contain control characters."""

    def test_raw_nul_rejected(self):
        parser = PythonProtocol()
        with pytest.raises(InvalidRequestLine):
            parser.feed(b"GET /\x00 HTTP/1.1\r\nHost: localhost\r\n\r\n")

    def test_embedded_nul_rejected(self):
        parser = PythonProtocol()
        with pytest.raises(InvalidRequestLine):
            parser.feed(b"GET /foo\x00bar HTTP/1.1\r\nHost: localhost\r\n\r\n")

    def test_bel_rejected(self):
        parser = PythonProtocol()
        with pytest.raises(InvalidRequestLine):
            parser.feed(b"GET /\x07 HTTP/1.1\r\nHost: localhost\r\n\r\n")

    def test_percent_encoded_nul_accepted(self):
        parser = PythonProtocol()
        parser.feed(b"GET /%00 HTTP/1.1\r\nHost: localhost\r\n\r\n")
        assert parser.is_complete
        assert parser.path == b"/%00"


class TestUnterminatedLineBounds:
    """A line that never gets its CRLF must not grow the buffer past the limit
    that applies to it."""

    @staticmethod
    def _feed_forever(parser, prefix, n=64):
        parser.feed(prefix)
        for _ in range(n):
            parser.feed(b"a" * 1024)

    def test_request_line(self):
        parser = PythonProtocol(limit_request_line=4094)
        with pytest.raises(LimitRequestLine):
            self._feed_forever(parser, b"GET /")
        assert len(parser._buffer) <= 4094 + 1024 + 1

    def test_request_line_unlimited_is_bounded(self):
        parser = PythonProtocol(limit_request_line=0)
        with pytest.raises(LimitRequestLine):
            self._feed_forever(parser, b"GET /", n=2048)

    def test_header_line(self):
        parser = PythonProtocol(limit_request_field_size=8190)
        with pytest.raises(LimitRequestHeaders):
            self._feed_forever(parser, b"GET / HTTP/1.1\r\nX: ")

    def test_chunk_size_line(self):
        parser = PythonProtocol(limit_request_field_size=8190)
        with pytest.raises(InvalidChunkSize):
            self._feed_forever(
                parser,
                b"POST / HTTP/1.1\r\nHost: a\r\n"
                b"Transfer-Encoding: chunked\r\n\r\n1;")

    def test_trailer_line(self):
        parser = PythonProtocol(limit_request_field_size=8190)
        with pytest.raises(LimitRequestHeaders):
            self._feed_forever(
                parser,
                b"POST / HTTP/1.1\r\nHost: a\r\n"
                b"Transfer-Encoding: chunked\r\n\r\n0\r\nX: ")

    def test_trailer_count(self):
        parser = PythonProtocol(limit_request_fields=10)
        parser.feed(b"POST / HTTP/1.1\r\nHost: a\r\n"
                    b"Transfer-Encoding: chunked\r\n\r\n0\r\n")
        with pytest.raises(LimitRequestHeaders):
            for _ in range(20):
                parser.feed(b"X: 1\r\n")

    def test_line_split_across_feeds(self):
        """A terminator split between two reads is still found."""
        done = []
        parser = PythonProtocol(on_message_complete=lambda: done.append(1))
        for byte in b"GET / HTTP/1.1\r\nHost: a\r\n\r\n":
            parser.feed(bytes([byte]))
        assert done == [1]


class TestLeadingEmptyLine:
    """RFC 9112 section 2.2: one empty line before the request line."""

    def test_one_crlf_split_across_feeds(self):
        done = []
        parser = PythonProtocol(on_message_complete=lambda: done.append(1))
        parser.feed(b"\r")
        parser.feed(b"\nGET / HTTP/1.1\r\nHost: a\r\n\r\n")
        assert done == [1]

    def test_two_crlf_rejected(self):
        parser = PythonProtocol()
        with pytest.raises(InvalidRequestLine):
            parser.feed(b"\r\n\r\nGET / HTTP/1.1\r\nHost: a\r\n\r\n")

    def test_one_crlf_per_message(self):
        """The skip resets for each request on a kept-alive connection."""
        done = []
        parser = PythonProtocol(on_message_complete=lambda: done.append(1))
        parser.feed(b"GET / HTTP/1.1\r\nHost: a\r\n\r\n")
        parser.reset()
        parser.feed(b"\r\nGET / HTTP/1.1\r\nHost: a\r\n\r\n")
        assert done == [1, 1]
