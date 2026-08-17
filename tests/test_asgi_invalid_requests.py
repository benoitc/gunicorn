#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Test invalid HTTP requests against ASGI callback parser.

Runs the same .http test files as test_invalid_requests.py but using
the ASGI callback parsers (PythonProtocol and H1CProtocol).
"""

import glob
import os

import pytest

from gunicorn.http.errors import (
    InvalidSchemeHeaders,
    ObsoleteFolding,
)
import treq_asgi
from gunicorn.asgi.parser import CallbackRequest

dirname = os.path.dirname(__file__)
reqdir = os.path.join(dirname, "requests", "invalid")
httpfiles = glob.glob(os.path.join(reqdir, "*.http"))

# Tests that require features not supported by callback parser
SKIP_TESTS = {
    # Tests requiring header_map config (underscore handling)
    'chunked_07.http', '040.http',
    # Tests for features not in callback parser
    '008.http',  # Invalid request target validation
    '012.http',  # Invalid request target validation
    '016.http',  # URI bracket validation
    '020.http',  # Space before colon in header name
    '022.http',  # Request target validation
}

# Config flags incompatible with callback parser
INCOMPATIBLE_FLAGS = ('permit_obsolete_folding', 'strip_header_spaces')

# Exceptions only raised by Python WSGI parser
WSGI_ONLY_EXCEPTIONS = (ObsoleteFolding, InvalidSchemeHeaders)

# Tests where fast parser has different validation than Python parser
FAST_PARSER_SKIP_TESTS = {
    '014.http',      # InvalidHeader - fast parser accepts
    '015.http',      # InvalidHeader - fast parser accepts
    '023.http',      # InvalidHeader - fast parser accepts
    '024.http',      # InvalidHeader - fast parser accepts
    'prefix_03.http',  # InvalidHeader - fast parser accepts
    'prefix_04.http',  # InvalidHeader - fast parser accepts
}


@pytest.mark.parametrize("fname", httpfiles)
def test_asgi_parser(fname, http_parser):
    """Test invalid HTTP requests with ASGI callback parsers."""
    basename = os.path.basename(fname)
    if basename in SKIP_TESTS:
        pytest.skip(f"Test {basename} not supported by callback parser")

    # Skip fast parser tests for files with known different validation
    if http_parser == 'fast' and basename in FAST_PARSER_SKIP_TESTS:
        pytest.skip(f"Fast parser has different validation for {basename}")

    env = treq_asgi.load_py(os.path.splitext(fname)[0] + ".py", http_parser=http_parser)
    expect = env["request"]
    cfg = env["cfg"]

    # Skip tests that use incompatible config flags
    for flag in INCOMPATIBLE_FLAGS:
        if getattr(cfg, flag, False):
            pytest.skip(f"Callback parser incompatible with {flag}")

    # Skip tests expecting WSGI-only exceptions
    if expect in WSGI_ONLY_EXCEPTIONS or (
        isinstance(expect, type) and issubclass(expect, WSGI_ONLY_EXCEPTIONS)
    ):
        pytest.skip(f"Callback parser does not raise {expect.__name__}")

    # Fixture-level opt-out for validations not (yet) implemented by the
    # fast (C) callback parser. The sidecar sets `python_only = True`.
    if http_parser == 'fast' and env.get('python_only'):
        pytest.skip("fixture marked python_only")

    req = treq_asgi.badrequest(fname)
    req.check(cfg, expect, http_parser=http_parser)


class TestSingletonHeadersFromParser:
    """Duplicate singleton fields are rejected where both parsers converge.

    The corpus cases above cover rejection during parsing. This covers the
    backstop in CallbackRequest.from_parser(), which production reaches via
    ASGIProtocol._on_headers_complete() and the corpus harness never does,
    since it drives the parser directly. Either outcome is accepted: the
    parser refusing the bytes outright, or from_parser() catching it.
    """

    DUPLICATES = [
        pytest.param(
            b"GET / HTTP/1.1\r\nHost: a\r\nHost: b\r\n\r\n", "host", id="host"
        ),
        pytest.param(
            b"GET / HTTP/1.1\r\nHost: a\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Type: text/html\r\n\r\n",
            "content-type", id="content-type",
        ),
    ]

    @pytest.mark.parametrize("raw,field", DUPLICATES)
    def test_duplicate_rejected(self, raw, field, http_parser):
        parser_class = treq_asgi.get_parser_class(http_parser)
        parser = parser_class()
        try:
            parser.feed(raw)
        except Exception as exc:  # parser rejected it outright, also fine
            assert field in str(exc).lower()
            return

        with pytest.raises(Exception) as exc_info:
            CallbackRequest.from_parser(parser)
        assert field in str(exc_info.value).lower()

    def test_single_occurrence_accepted(self, http_parser):
        parser_class = treq_asgi.get_parser_class(http_parser)
        parser = parser_class()
        parser.feed(b"GET / HTTP/1.1\r\nHost: a\r\nContent-Type: text/html\r\n\r\n")
        req = CallbackRequest.from_parser(parser)
        assert req.get_header("HOST") == "a"
