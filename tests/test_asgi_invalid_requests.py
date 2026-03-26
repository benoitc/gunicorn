#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Test invalid HTTP requests against ASGI callback parser.

Runs the same .http test files as test_invalid_requests.py but using
the ASGI PythonProtocol callback parser.
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


@pytest.mark.parametrize("fname", httpfiles)
def test_asgi_parser(fname):
    """Test invalid HTTP requests with ASGI callback parser."""
    basename = os.path.basename(fname)
    if basename in SKIP_TESTS:
        pytest.skip(f"Test {basename} not supported by callback parser")

    env = treq_asgi.load_py(os.path.splitext(fname)[0] + ".py")
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
    req.check(cfg, expect)
