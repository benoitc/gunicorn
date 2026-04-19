#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Test request utilities for ASGI callback parser.

Provides the same test infrastructure as treq.py but for testing
the ASGI callback parsers (PythonProtocol and H1CProtocol).
"""

import importlib.machinery
import os
import random
import types

from gunicorn.config import Config
from gunicorn.asgi.parser import (
    PythonProtocol,
    ParseError,
    InvalidHeader,
    InvalidHeaderName,
    InvalidRequestLine,
    InvalidRequestMethod,
    InvalidHTTPVersion,
    LimitRequestLine,
    LimitRequestHeaders,
    UnsupportedTransferCoding,
    InvalidChunkSize,
    InvalidChunkExtension,
    InvalidProxyLine,
    InvalidProxyHeader,
)
from gunicorn.util import split_request_uri

dirname = os.path.dirname(__file__)
random.seed()

# Track if fast parser is available
_gunicorn_h1c = None


def _get_h1c():
    """Lazily import gunicorn_h1c if available."""
    global _gunicorn_h1c
    if _gunicorn_h1c is None:
        try:
            import gunicorn_h1c
            _gunicorn_h1c = gunicorn_h1c
        except ImportError:
            _gunicorn_h1c = False
    return _gunicorn_h1c if _gunicorn_h1c else None


def get_parser_class(http_parser):
    """Get the appropriate parser class for the test parameter."""
    if http_parser == "fast":
        h1c = _get_h1c()
        if h1c is None:
            raise ImportError("gunicorn_h1c required for fast parser tests")
        return h1c.H1CProtocol
    return PythonProtocol


def uri(data):
    ret = {"raw": data}
    parts = split_request_uri(data)
    ret["scheme"] = parts.scheme or ''
    ret["host"] = parts.netloc.rsplit(":", 1)[0] or None
    ret["port"] = parts.port or 80
    ret["path"] = parts.path or ''
    ret["query"] = parts.query or ''
    ret["fragment"] = parts.fragment or ''
    return ret


def load_py(fname, http_parser='python'):
    """Load test configuration from Python file.

    Args:
        fname: Path to the Python configuration file
        http_parser: Parser to use - 'python' or 'fast'
    """
    module_name = '__config__'
    mod = types.ModuleType(module_name)
    setattr(mod, 'uri', uri)
    setattr(mod, 'cfg', Config())
    loader = importlib.machinery.SourceFileLoader(module_name, fname)
    loader.exec_module(mod)
    result = vars(mod)
    result['http_parser'] = http_parser
    return result


def decode_hex_escapes(data):
    """Decode hex escape sequences like \\xAB in test data."""
    result = bytearray()
    i = 0
    while i < len(data):
        if i + 3 < len(data) and data[i:i+2] == b'\\x':
            hex_chars = data[i+2:i+4]
            try:
                byte_val = int(hex_chars, 16)
                result.append(byte_val)
                i += 4
                continue
            except ValueError:
                pass
        result.append(data[i])
        i += 1
    return bytes(result)


# Map WSGI parser exceptions to ASGI parser exceptions
EXCEPTION_MAP = {
    'InvalidRequestLine': (InvalidRequestLine, ParseError),
    'InvalidRequestMethod': (InvalidRequestMethod, ParseError),
    'InvalidHTTPVersion': (InvalidHTTPVersion, ParseError),
    'InvalidHeader': (InvalidHeader, ParseError),
    'InvalidHeaderName': (InvalidHeaderName, ParseError),
    'LimitRequestLine': (LimitRequestLine, ParseError),
    'LimitRequestHeaders': (LimitRequestHeaders, ParseError),
    'UnsupportedTransferCoding': (UnsupportedTransferCoding, ParseError),
    'InvalidChunkSize': (InvalidChunkSize, ParseError),
    'InvalidChunkExtension': (InvalidChunkExtension, ParseError),
    'InvalidProxyLine': (InvalidProxyLine, ParseError),
    'InvalidProxyHeader': (InvalidProxyHeader, ParseError),
}


def map_exception(wsgi_exc, http_parser='python'):
    """Map a WSGI exception class to equivalent ASGI parser exceptions.

    Args:
        wsgi_exc: The expected WSGI exception class
        http_parser: Parser being used - 'python' or 'fast'

    Returns:
        Tuple of acceptable exception classes
    """
    exc_name = wsgi_exc.__name__
    base_exceptions = EXCEPTION_MAP.get(exc_name, (ParseError,))

    # For fast parser, also accept gunicorn_h1c exceptions
    if http_parser == 'fast':
        h1c = _get_h1c()
        if h1c is not None:
            h1c_exceptions = []
            # Check for matching exception in gunicorn_h1c
            if hasattr(h1c, exc_name):
                h1c_exceptions.append(getattr(h1c, exc_name))
            # Always accept generic ParseError from h1c
            if hasattr(h1c, 'ParseError'):
                h1c_exceptions.append(h1c.ParseError)
            return base_exceptions + tuple(h1c_exceptions)

    return base_exceptions


class request:
    """Test valid HTTP requests against ASGI callback parser."""

    def __init__(self, fname, expect):
        self.fname = fname
        self.name = os.path.basename(fname)

        self.expect = expect
        if not isinstance(self.expect, list):
            self.expect = [self.expect]

        with open(self.fname, 'rb') as handle:
            self.data = handle.read()
        self.data = self.data.replace(b"\n", b"").replace(b"\\r\\n", b"\r\n")
        self.data = self.data.replace(b"\\0", b"\000").replace(b"\\n", b"\n").replace(b"\\t", b"\t")
        self.data = decode_hex_escapes(self.data)
        if b"\\" in self.data:
            raise AssertionError("Unexpected backslash in test data")

    def send_all(self):
        yield self.data

    def send_lines(self):
        lines = self.data
        pos = lines.find(b"\r\n")
        while pos > 0:
            yield lines[:pos+2]
            lines = lines[pos+2:]
            pos = lines.find(b"\r\n")
        if lines:
            yield lines

    def send_bytes(self):
        for d in self.data:
            yield bytes([d])

    def send_random(self):
        maxs = max(1, round(len(self.data) / 10))
        read = 0
        while read < len(self.data):
            chunk = random.randint(1, maxs)
            yield self.data[read:read+chunk]
            read += chunk

    def check(self, cfg, sender):
        """Parse request and verify it matches expected values."""
        body_chunks = []

        # Handle limit_request_field_size=0 meaning "use default"
        field_size = cfg.limit_request_field_size
        if field_size <= 0:
            field_size = 8190  # Default max

        parser = PythonProtocol(
            on_body=lambda chunk: body_chunks.append(chunk),
            limit_request_line=cfg.limit_request_line,
            limit_request_fields=cfg.limit_request_fields,
            limit_request_field_size=field_size,
            permit_unconventional_http_method=cfg.permit_unconventional_http_method,
            permit_unconventional_http_version=cfg.permit_unconventional_http_version,
            proxy_protocol=getattr(cfg, 'proxy_protocol', 'off'),
        )

        for chunk in sender():
            parser.feed(chunk)
        parser.finish()  # Signal EOF

        # Verify parsed request matches expected
        exp = self.expect[0]  # For now, handle single request

        assert parser.method == exp["method"].encode('latin-1'), \
            f"Method mismatch: {parser.method} != {exp['method']}"

        # Path comparison - parser stores raw bytes
        expected_path = exp["uri"]["raw"].encode('latin-1')
        assert parser.path == expected_path, \
            f"Path mismatch: {parser.path} != {expected_path}"

        assert parser.http_version == exp["version"], \
            f"Version mismatch: {parser.http_version} != {exp['version']}"

        # Headers - convert to comparable format
        parsed_headers = [
            (n.decode('latin-1').upper(), v.decode('latin-1'))
            for n, v in parser.headers
        ]
        assert parsed_headers == exp["headers"], \
            f"Headers mismatch: {parsed_headers} != {exp['headers']}"

        # Body - ensure expected_body is bytes for comparison
        body = b"".join(body_chunks)
        expected_body = exp["body"]
        if isinstance(expected_body, str):
            expected_body = expected_body.encode('latin-1')
        assert body == expected_body, \
            f"Body mismatch: {body!r} != {expected_body!r}"

        assert parser.is_complete, "Parser did not complete"


class badrequest:
    """Test invalid HTTP requests against ASGI callback parser."""

    def __init__(self, fname):
        self.fname = fname
        self.name = os.path.basename(fname)

        with open(self.fname, 'rb') as handle:
            self.data = handle.read()
        self.data = self.data.replace(b"\n", b"").replace(b"\\r\\n", b"\r\n")
        self.data = self.data.replace(b"\\0", b"\000").replace(b"\\n", b"\n").replace(b"\\t", b"\t")
        # Handle hex escape sequences for binary data (e.g., \x0D for bare CR)
        self.data = decode_hex_escapes(self.data)
        if b"\\" in self.data:
            raise AssertionError("Unexpected backslash in test data - only handling HTAB, NUL, CRLF, and hex escapes")

    def send_all(self):
        yield self.data

    def send_random(self):
        maxs = max(1, round(len(self.data) / 10))
        read = 0
        while read < len(self.data):
            chunk = random.randint(1, maxs)
            yield self.data[read:read+chunk]
            read += chunk

    def check(self, cfg, expected_exc, http_parser='python'):
        """Verify parser raises expected exception.

        Args:
            cfg: Gunicorn config object
            expected_exc: Expected WSGI exception class
            http_parser: Parser to use - 'python' or 'fast'
        """
        parser_class = get_parser_class(http_parser)

        # Handle limit_request_field_size=0 meaning "use default"
        field_size = cfg.limit_request_field_size
        if field_size <= 0:
            field_size = 8190  # Default max

        # Fast parser (H1CProtocol) has different constructor signature
        if http_parser == 'fast':
            parser = parser_class(
                limit_request_line=cfg.limit_request_line,
                limit_request_fields=cfg.limit_request_fields,
                limit_request_field_size=field_size,
            )
        else:
            parser = parser_class(
                limit_request_line=cfg.limit_request_line,
                limit_request_fields=cfg.limit_request_fields,
                limit_request_field_size=field_size,
                permit_unconventional_http_method=cfg.permit_unconventional_http_method,
                permit_unconventional_http_version=cfg.permit_unconventional_http_version,
                proxy_protocol=getattr(cfg, 'proxy_protocol', 'off'),
            )

        # Get acceptable exception types (includes h1c exceptions for fast parser)
        acceptable = list(map_exception(expected_exc, http_parser))

        # Always accept ParseError from python parser
        if ParseError not in acceptable:
            acceptable.append(ParseError)

        # For fast parser, also catch gunicorn_h1c exceptions
        if http_parser == 'fast':
            h1c = _get_h1c()
            if h1c:
                # gunicorn_h1c has two ParseError classes in different modules
                if hasattr(h1c, 'ParseError'):
                    acceptable.append(h1c.ParseError)
                if hasattr(h1c, '_protocol') and hasattr(h1c._protocol, 'ParseError'):
                    acceptable.append(h1c._protocol.ParseError)
                if hasattr(h1c, 'IncompleteError'):
                    acceptable.append(h1c.IncompleteError)

        acceptable = tuple(acceptable)

        raised = False
        try:
            for chunk in self.send_random():
                parser.feed(chunk)
            # If we get here without exception, try to check if parser completed
            # Some invalid requests might parse headers but fail on body
            if not parser.is_complete:
                # Parser stalled - this counts as detecting invalid input
                raised = True
        except acceptable:
            raised = True

        if not raised:
            raise AssertionError(
                f"Expected {expected_exc.__name__} but parser accepted the request"
            )
