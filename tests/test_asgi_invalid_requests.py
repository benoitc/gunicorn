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

    req = treq_asgi.badrequest(fname)
    req.check(cfg, expect, http_parser=http_parser)
