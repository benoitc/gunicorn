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
    InvalidChunkSize,
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

        with pytest.raises(InvalidHeader, match="Negative Content-Length"):
            parser.feed(
                b"POST /test HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"Content-Length: -999\r\n"
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
