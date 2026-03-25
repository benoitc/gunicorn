#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Test valid HTTP requests against ASGI callback parser.

Runs the same .http test files as test_valid_requests.py but using
the ASGI PythonProtocol callback parser.
"""

import glob
import os

import pytest

import treq_asgi

dirname = os.path.dirname(__file__)
reqdir = os.path.join(dirname, "requests", "valid")
httpfiles = glob.glob(os.path.join(reqdir, "*.http"))

# Tests that require features not supported by callback parser
SKIP_TESTS = set()

# Tests that use config options incompatible with callback parser
INCOMPATIBLE_BOOL_FLAGS = ('permit_obsolete_folding', 'strip_header_spaces')


@pytest.mark.parametrize("fname", httpfiles)
def test_asgi_parser(fname):
    """Test valid HTTP requests with ASGI callback parser."""
    basename = os.path.basename(fname)
    if basename in SKIP_TESTS:
        pytest.skip(f"Test {basename} not supported by callback parser")

    env = treq_asgi.load_py(os.path.splitext(fname)[0] + ".py")
    expect = env['request']
    cfg = env['cfg']

    # Skip tests that use incompatible config flags
    for flag in INCOMPATIBLE_BOOL_FLAGS:
        if getattr(cfg, flag, False):
            pytest.skip(f"Callback parser incompatible with {flag}")

    # Skip proxy protocol tests
    if getattr(cfg, 'proxy_protocol', 'off') != 'off':
        pytest.skip("Callback parser does not support proxy_protocol")

    req = treq_asgi.request(fname, expect)

    # Test with different sending strategies
    for sender in [req.send_all, req.send_lines, req.send_random]:
        req.check(cfg, sender)
