#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import glob
import os

import pytest

from gunicorn.http.errors import (
    InvalidRequestLine,
    InvalidRequestMethod,
    InvalidSchemeHeaders,
    ObsoleteFolding,
)
import treq

dirname = os.path.dirname(__file__)
reqdir = os.path.join(dirname, "requests", "invalid")
httpfiles = glob.glob(os.path.join(reqdir, "*.http"))

# Flags incompatible with fast parser (require Python parser features)
_FAST_INCOMPATIBLE_FLAGS = ('permit_obsolete_folding', 'strip_header_spaces')

# Exceptions that only the Python parser raises (C parser has different validation)
_PYTHON_ONLY_EXCEPTIONS = (ObsoleteFolding, InvalidSchemeHeaders)

# C parser may raise different but valid exceptions for these cases
_FAST_PARSER_ALTERNATES = {
    InvalidRequestMethod: (InvalidRequestLine,),  # e.g. "GET:" raises InvalidRequestLine
}


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

        # Skip tests expecting Python-only exceptions
        if expect in _PYTHON_ONLY_EXCEPTIONS or (
            isinstance(expect, type) and issubclass(expect, _PYTHON_ONLY_EXCEPTIONS)
        ):
            pytest.skip(f"fast parser does not raise {expect.__name__}")

    # Determine acceptable exceptions (fast parser may raise alternates)
    if http_parser == 'fast' and expect in _FAST_PARSER_ALTERNATES:
        acceptable = (expect,) + _FAST_PARSER_ALTERNATES[expect]
    else:
        acceptable = expect

    req = treq.badrequest(fname)

    with pytest.raises(acceptable):
        req.check(cfg)
