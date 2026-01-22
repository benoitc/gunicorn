#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import io
import pytest
from unittest import mock

from gunicorn.uwsgi import (
    UWSGIRequest,
    UWSGIParser,
    UWSGIParseException,
    InvalidUWSGIHeader,
    UnsupportedModifier,
    ForbiddenUWSGIRequest,
)
from gunicorn.http.unreader import IterUnreader


def make_uwsgi_packet(vars_dict, modifier1=0, modifier2=0):
    """Create uWSGI packet for testing.

    Args:
        vars_dict: Dict of WSGI environ variables
        modifier1: Packet type (0 = WSGI request)
        modifier2: Additional flags

    Returns:
        bytes: Complete uWSGI packet
    """
    vars_data = b''
    for key, value in vars_dict.items():
        k = key.encode('latin-1')
        v = value.encode('latin-1')
        vars_data += len(k).to_bytes(2, 'little') + k
        vars_data += len(v).to_bytes(2, 'little') + v

    header = bytes([modifier1]) + len(vars_data).to_bytes(2, 'little') + bytes([modifier2])
    return header + vars_data


def make_uwsgi_packet_with_body(vars_dict, body=b'', modifier1=0, modifier2=0):
    """Create uWSGI packet with body for testing."""
    if body:
        vars_dict = dict(vars_dict)
        vars_dict['CONTENT_LENGTH'] = str(len(body))
    return make_uwsgi_packet(vars_dict, modifier1, modifier2) + body


class MockConfig:
    """Mock config object for testing."""

    def __init__(self, is_ssl=False, uwsgi_allow_ips=None):
        self.is_ssl = is_ssl
        self.uwsgi_allow_ips = uwsgi_allow_ips or ['127.0.0.1', '::1']


class TestUWSGIPacketConstruction:
    """Test the packet construction helper."""

    def test_empty_vars(self):
        packet = make_uwsgi_packet({})
        assert packet == b'\x00\x00\x00\x00'  # modifier1=0, size=0, modifier2=0

    def test_single_var(self):
        packet = make_uwsgi_packet({'KEY': 'val'})
        # Header: modifier1(0) + size(10 in LE) + modifier2(0)
        # Var: key_size(3 in LE) + 'KEY' + val_size(3 in LE) + 'val'
        # Size = 2 + 3 + 2 + 3 = 10 bytes
        expected_header = b'\x00\x0a\x00\x00'
        expected_var = b'\x03\x00KEY\x03\x00val'
        assert packet == expected_header + expected_var

    def test_multiple_vars(self):
        packet = make_uwsgi_packet({'A': '1', 'B': '2'})
        assert len(packet) == 4 + (2 + 1 + 2 + 1) * 2  # header + 2 vars


class TestUWSGIRequest:
    """Test UWSGIRequest parsing."""

    def test_parse_simple_request(self):
        """Test parsing a simple GET request."""
        packet = make_uwsgi_packet({
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': '/test',
            'QUERY_STRING': 'foo=bar',
        })
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = UWSGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        assert req.method == 'GET'
        assert req.path == '/test'
        assert req.query == 'foo=bar'
        assert req.uri == '/test?foo=bar'

    def test_parse_post_request_with_body(self):
        """Test parsing a POST request with body."""
        body = b'name=test&value=123'
        packet = make_uwsgi_packet_with_body({
            'REQUEST_METHOD': 'POST',
            'PATH_INFO': '/submit',
            'CONTENT_TYPE': 'application/x-www-form-urlencoded',
        }, body)
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = UWSGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        assert req.method == 'POST'
        assert req.path == '/submit'
        assert req.body.read() == body

    def test_parse_headers(self):
        """Test that HTTP_* vars become headers."""
        packet = make_uwsgi_packet({
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': '/',
            'HTTP_HOST': 'example.com',
            'HTTP_USER_AGENT': 'TestClient/1.0',
            'HTTP_ACCEPT': 'text/html',
        })
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = UWSGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        headers_dict = dict(req.headers)
        assert headers_dict['HOST'] == 'example.com'
        assert headers_dict['USER-AGENT'] == 'TestClient/1.0'
        assert headers_dict['ACCEPT'] == 'text/html'

    def test_parse_content_type_header(self):
        """Test that CONTENT_TYPE becomes a header."""
        packet = make_uwsgi_packet({
            'REQUEST_METHOD': 'POST',
            'PATH_INFO': '/',
            'CONTENT_TYPE': 'application/json',
            'CONTENT_LENGTH': '0',
        })
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = UWSGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        headers_dict = dict(req.headers)
        assert headers_dict['CONTENT-TYPE'] == 'application/json'
        assert headers_dict['CONTENT-LENGTH'] == '0'

    def test_https_scheme(self):
        """Test scheme detection from HTTPS variable."""
        packet = make_uwsgi_packet({
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': '/',
            'HTTPS': 'on',
        })
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = UWSGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        assert req.scheme == 'https'

    def test_wsgi_url_scheme(self):
        """Test scheme from wsgi.url_scheme variable."""
        packet = make_uwsgi_packet({
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': '/',
            'wsgi.url_scheme': 'https',
        })
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = UWSGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        assert req.scheme == 'https'

    def test_default_values(self):
        """Test default values when vars are missing."""
        packet = make_uwsgi_packet({})
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = UWSGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        assert req.method == 'GET'
        assert req.path == '/'
        assert req.query == ''
        assert req.uri == '/'

    def test_uwsgi_vars_preserved(self):
        """Test that all vars are preserved in uwsgi_vars."""
        packet = make_uwsgi_packet({
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': '/',
            'SERVER_NAME': 'localhost',
            'SERVER_PORT': '8000',
            'CUSTOM_VAR': 'custom_value',
        })
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = UWSGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        assert req.uwsgi_vars['SERVER_NAME'] == 'localhost'
        assert req.uwsgi_vars['SERVER_PORT'] == '8000'
        assert req.uwsgi_vars['CUSTOM_VAR'] == 'custom_value'


class TestUWSGIRequestErrors:
    """Test UWSGIRequest error handling."""

    def test_incomplete_header(self):
        """Test error on incomplete header."""
        unreader = IterUnreader([b'\x00\x00'])  # Only 2 bytes
        cfg = MockConfig()

        with pytest.raises(InvalidUWSGIHeader) as exc_info:
            UWSGIRequest(cfg, unreader, ('127.0.0.1', 12345))
        assert 'incomplete header' in str(exc_info.value)

    def test_incomplete_vars_block(self):
        """Test error on truncated vars block."""
        # Header says 100 bytes of vars, but we only provide 10
        header = b'\x00\x64\x00\x00'  # modifier1=0, size=100, modifier2=0
        unreader = IterUnreader([header + b'1234567890'])
        cfg = MockConfig()

        with pytest.raises(InvalidUWSGIHeader) as exc_info:
            UWSGIRequest(cfg, unreader, ('127.0.0.1', 12345))
        assert 'incomplete vars block' in str(exc_info.value)

    def test_unsupported_modifier(self):
        """Test error on non-zero modifier1."""
        packet = bytes([1]) + b'\x00\x00\x00'  # modifier1=1
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        with pytest.raises(UnsupportedModifier) as exc_info:
            UWSGIRequest(cfg, unreader, ('127.0.0.1', 12345))
        assert exc_info.value.modifier == 1
        assert exc_info.value.code == 501

    def test_truncated_key_size(self):
        """Test error on truncated key size."""
        header = b'\x00\x01\x00\x00'  # size=1, but need at least 2 bytes for key_size
        unreader = IterUnreader([header + b'X'])
        cfg = MockConfig()

        with pytest.raises(InvalidUWSGIHeader) as exc_info:
            UWSGIRequest(cfg, unreader, ('127.0.0.1', 12345))
        assert 'truncated' in str(exc_info.value)

    def test_forbidden_ip(self):
        """Test error when source IP not in allow list."""
        packet = make_uwsgi_packet({'REQUEST_METHOD': 'GET', 'PATH_INFO': '/'})
        unreader = IterUnreader([packet])
        cfg = MockConfig(uwsgi_allow_ips=['192.168.1.1'])

        with pytest.raises(ForbiddenUWSGIRequest) as exc_info:
            UWSGIRequest(cfg, unreader, ('10.0.0.1', 12345))
        assert exc_info.value.code == 403
        assert '10.0.0.1' in str(exc_info.value)

    def test_allowed_ip_wildcard(self):
        """Test that wildcard allows any IP."""
        packet = make_uwsgi_packet({'REQUEST_METHOD': 'GET', 'PATH_INFO': '/'})
        unreader = IterUnreader([packet])
        cfg = MockConfig(uwsgi_allow_ips=['*'])

        # Should not raise
        req = UWSGIRequest(cfg, unreader, ('10.0.0.1', 12345))
        assert req.method == 'GET'

    def test_unix_socket_always_allowed(self):
        """Test that UNIX socket connections are always allowed."""
        packet = make_uwsgi_packet({'REQUEST_METHOD': 'GET', 'PATH_INFO': '/'})
        unreader = IterUnreader([packet])
        cfg = MockConfig(uwsgi_allow_ips=['127.0.0.1'])

        # UNIX socket has non-tuple peer_addr
        req = UWSGIRequest(cfg, unreader, None)
        assert req.method == 'GET'


class TestUWSGIRequestConnection:
    """Test connection handling."""

    def test_should_close_default(self):
        """Test default keep-alive behavior."""
        packet = make_uwsgi_packet({'REQUEST_METHOD': 'GET', 'PATH_INFO': '/'})
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = UWSGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        assert req.should_close() is False

    def test_should_close_connection_close(self):
        """Test Connection: close header."""
        packet = make_uwsgi_packet({
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': '/',
            'HTTP_CONNECTION': 'close',
        })
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = UWSGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        assert req.should_close() is True

    def test_should_close_connection_keepalive(self):
        """Test Connection: keep-alive header."""
        packet = make_uwsgi_packet({
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': '/',
            'HTTP_CONNECTION': 'keep-alive',
        })
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = UWSGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        assert req.should_close() is False

    def test_force_close(self):
        """Test force_close method."""
        packet = make_uwsgi_packet({'REQUEST_METHOD': 'GET', 'PATH_INFO': '/'})
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = UWSGIRequest(cfg, unreader, ('127.0.0.1', 12345))
        req.force_close()

        assert req.should_close() is True


class TestUWSGIParser:
    """Test UWSGIParser."""

    def test_parser_iteration(self):
        """Test iterating over parser for multiple requests."""
        packet = make_uwsgi_packet({
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': '/test',
            'HTTP_CONNECTION': 'close',  # Single request
        })
        cfg = MockConfig()

        # Parser expects an iterable source, not an unreader
        parser = UWSGIParser(cfg, [packet], ('127.0.0.1', 12345))
        req = next(parser)

        assert req.method == 'GET'
        assert req.path == '/test'

    def test_parser_mesg_class(self):
        """Test that parser uses UWSGIRequest."""
        assert UWSGIParser.mesg_class is UWSGIRequest


class TestExceptionStrings:
    """Test exception string representations."""

    def test_invalid_uwsgi_header_str(self):
        exc = InvalidUWSGIHeader("test message")
        assert str(exc) == "Invalid uWSGI header: test message"
        assert exc.code == 400

    def test_unsupported_modifier_str(self):
        exc = UnsupportedModifier(5)
        assert str(exc) == "Unsupported uWSGI modifier1: 5"
        assert exc.code == 501

    def test_forbidden_uwsgi_request_str(self):
        exc = ForbiddenUWSGIRequest("10.0.0.1")
        assert str(exc) == "uWSGI request from '10.0.0.1' not allowed"
        assert exc.code == 403


class TestUWSGIBody:
    """Test body reading."""

    def test_read_body_in_chunks(self):
        """Test reading body in multiple chunks."""
        body = b'A' * 1000
        packet = make_uwsgi_packet_with_body({
            'REQUEST_METHOD': 'POST',
            'PATH_INFO': '/',
        }, body)
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = UWSGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        result = b''
        chunk = req.body.read(100)
        while chunk:
            result += chunk
            chunk = req.body.read(100)

        assert result == body

    def test_invalid_content_length(self):
        """Test handling of invalid CONTENT_LENGTH."""
        packet = make_uwsgi_packet({
            'REQUEST_METHOD': 'POST',
            'PATH_INFO': '/',
            'CONTENT_LENGTH': 'invalid',
        })
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = UWSGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        # Invalid content length should default to 0
        assert req.body.read() == b''

    def test_negative_content_length(self):
        """Test handling of negative CONTENT_LENGTH."""
        packet = make_uwsgi_packet({
            'REQUEST_METHOD': 'POST',
            'PATH_INFO': '/',
            'CONTENT_LENGTH': '-5',
        })
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = UWSGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        # Negative content length should default to 0
        assert req.body.read() == b''
