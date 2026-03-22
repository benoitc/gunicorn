#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import glob
import os

import pytest

import treq

dirname = os.path.dirname(__file__)
reqdir = os.path.join(dirname, "requests", "invalid")
httpfiles = glob.glob(os.path.join(reqdir, "*.http"))

# Flags incompatible with fast parser
_FAST_INCOMPATIBLE_FLAGS = ('permit_obsolete_folding', 'strip_header_spaces')


@pytest.mark.parametrize("fname", httpfiles)
def test_http_parser(fname, http_parser):
    """Test invalid HTTP requests with both parser implementations."""
    env = treq.load_py(os.path.splitext(fname)[0] + ".py", http_parser=http_parser)

    expect = env["request"]
    cfg = env["cfg"]

    # Skip fast parser tests that use incompatible compatibility flags
    if http_parser == 'fast':
        for flag in _FAST_INCOMPATIBLE_FLAGS:
            if getattr(cfg, flag, False):
                pytest.skip(f"fast parser incompatible with {flag}")

    req = treq.badrequest(fname)

    with pytest.raises(expect):
        req.check(cfg)
