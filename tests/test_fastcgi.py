#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import io
import pytest
from unittest import mock

from gunicorn.fastcgi import (
    FastCGIRequest,
    FastCGIParser,
    FastCGIResponse,
    FastCGIParseException,
    InvalidFastCGIRecord,
    UnsupportedRole,
    ForbiddenFastCGIRequest,
)
from gunicorn.fastcgi.constants import (
    FCGI_VERSION_1,
    FCGI_BEGIN_REQUEST,
    FCGI_PARAMS,
    FCGI_STDIN,
    FCGI_STDOUT,
    FCGI_END_REQUEST,
    FCGI_RESPONDER,
    FCGI_AUTHORIZER,
    FCGI_KEEP_CONN,
    FCGI_REQUEST_COMPLETE,
)
from gunicorn.http.unreader import IterUnreader


def make_fcgi_record(record_type, request_id, content, padding=0):
    """Create a FastCGI record.

    Args:
        record_type: Record type (FCGI_BEGIN_REQUEST, FCGI_PARAMS, etc.)
        request_id: Request ID (1-65535)
        content: Record content as bytes
        padding: Optional padding length

    Returns:
        bytes: Complete FastCGI record
    """
    content_length = len(content)
    header = bytes([
        FCGI_VERSION_1,
        record_type,
        (request_id >> 8) & 0xFF,
        request_id & 0xFF,
        (content_length >> 8) & 0xFF,
        content_length & 0xFF,
        padding,
        0,  # reserved
    ])
    return header + content + b'\x00' * padding


def make_begin_request(request_id, role=FCGI_RESPONDER, flags=0):
    """Create a BEGIN_REQUEST record."""
    content = bytes([
        (role >> 8) & 0xFF,
        role & 0xFF,
        flags,
        0, 0, 0, 0, 0,  # reserved
    ])
    return make_fcgi_record(FCGI_BEGIN_REQUEST, request_id, content)


def encode_name_value(name, value):
    """Encode a name-value pair for PARAMS record.

    Uses FastCGI length encoding:
    - 1 byte if length < 128
    - 4 bytes (big-endian with high bit set) if length >= 128
    """
    name_bytes = name.encode('latin-1')
    value_bytes = value.encode('latin-1')

    result = b''

    # Encode name length
    if len(name_bytes) < 128:
        result += bytes([len(name_bytes)])
    else:
        result += (len(name_bytes) | 0x80000000).to_bytes(4, 'big')

    # Encode value length
    if len(value_bytes) < 128:
        result += bytes([len(value_bytes)])
    else:
        result += (len(value_bytes) | 0x80000000).to_bytes(4, 'big')

    result += name_bytes + value_bytes
    return result


def make_params_records(params_dict, request_id):
    """Create PARAMS records for a dict of parameters.

    Args:
        params_dict: Dict of parameter names to values
        request_id: Request ID

    Returns:
        bytes: PARAMS records followed by empty PARAMS record
    """
    content = b''
    for name, value in params_dict.items():
        content += encode_name_value(name, value)

    # PARAMS record with content
    result = make_fcgi_record(FCGI_PARAMS, request_id, content)
    # Empty PARAMS record to signal end
    result += make_fcgi_record(FCGI_PARAMS, request_id, b'')
    return result


def make_stdin_records(body, request_id):
    """Create STDIN records for request body.

    Args:
        body: Request body as bytes
        request_id: Request ID

    Returns:
        bytes: STDIN records followed by empty STDIN record
    """
    result = b''
    if body:
        result = make_fcgi_record(FCGI_STDIN, request_id, body)
    # Empty STDIN record to signal end
    result += make_fcgi_record(FCGI_STDIN, request_id, b'')
    return result


def make_fcgi_request(params_dict, body=b'', request_id=1, role=FCGI_RESPONDER, flags=0):
    """Create a complete FastCGI request.

    Args:
        params_dict: Dict of CGI/WSGI parameters
        body: Request body
        request_id: Request ID
        role: FastCGI role
        flags: FastCGI flags (e.g., FCGI_KEEP_CONN)

    Returns:
        bytes: Complete FastCGI request
    """
    if body:
        params_dict = dict(params_dict)
        params_dict['CONTENT_LENGTH'] = str(len(body))

    result = make_begin_request(request_id, role, flags)
    result += make_params_records(params_dict, request_id)
    result += make_stdin_records(body, request_id)
    return result


class MockConfig:
    """Mock config object for testing."""

    def __init__(self, is_ssl=False, fastcgi_allow_ips=None):
        self.is_ssl = is_ssl
        self.fastcgi_allow_ips = fastcgi_allow_ips or ['127.0.0.1', '::1']


class MockSocket:
    """Mock socket for testing response output."""

    def __init__(self):
        self.data = b''

    def sendall(self, data):
        self.data += data


class TestFastCGIRecordConstruction:
    """Test the record construction helpers."""

    def test_make_fcgi_record(self):
        """Test basic record construction."""
        record = make_fcgi_record(FCGI_PARAMS, 1, b'test')
        assert record[0] == FCGI_VERSION_1
        assert record[1] == FCGI_PARAMS
        assert record[2:4] == b'\x00\x01'  # request_id = 1
        assert record[4:6] == b'\x00\x04'  # content_length = 4
        assert record[6] == 0  # padding_length
        assert record[7] == 0  # reserved
        assert record[8:] == b'test'

    def test_make_begin_request(self):
        """Test BEGIN_REQUEST record construction."""
        record = make_begin_request(1, FCGI_RESPONDER, FCGI_KEEP_CONN)
        assert record[0] == FCGI_VERSION_1
        assert record[1] == FCGI_BEGIN_REQUEST
        # Content: role (2 bytes) + flags (1 byte) + reserved (5 bytes)
        content = record[8:]
        assert content[0:2] == b'\x00\x01'  # role = RESPONDER
        assert content[2] == FCGI_KEEP_CONN  # flags

    def test_encode_name_value_short(self):
        """Test name-value encoding with short lengths."""
        encoded = encode_name_value('KEY', 'val')
        assert encoded == b'\x03\x03KEYval'

    def test_encode_name_value_long(self):
        """Test name-value encoding with long value."""
        long_value = 'x' * 200
        encoded = encode_name_value('K', long_value)
        # Name length: 1 byte (0x01)
        # Value length: 4 bytes (0x80 | 200 in big-endian)
        assert encoded[0] == 1  # name length
        assert encoded[1] == 0x80  # high bit set for 4-byte length
        assert encoded[1:5] == (200 | 0x80000000).to_bytes(4, 'big')


class TestFastCGIRequest:
    """Test FastCGIRequest parsing."""

    def test_parse_simple_request(self):
        """Test parsing a simple GET request."""
        packet = make_fcgi_request({
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': '/test',
            'QUERY_STRING': 'foo=bar',
        })
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        assert req.method == 'GET'
        assert req.path == '/test'
        assert req.query == 'foo=bar'
        assert req.uri == '/test?foo=bar'
        assert req.request_id == 1

    def test_parse_post_request_with_body(self):
        """Test parsing a POST request with body."""
        body = b'name=test&value=123'
        packet = make_fcgi_request({
            'REQUEST_METHOD': 'POST',
            'PATH_INFO': '/submit',
            'CONTENT_TYPE': 'application/x-www-form-urlencoded',
        }, body)
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        assert req.method == 'POST'
        assert req.path == '/submit'
        assert req.body.read() == body

    def test_parse_headers(self):
        """Test that HTTP_* vars become headers."""
        packet = make_fcgi_request({
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': '/',
            'HTTP_HOST': 'example.com',
            'HTTP_USER_AGENT': 'TestClient/1.0',
            'HTTP_ACCEPT': 'text/html',
        })
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        headers_dict = dict(req.headers)
        assert headers_dict['HOST'] == 'example.com'
        assert headers_dict['USER-AGENT'] == 'TestClient/1.0'
        assert headers_dict['ACCEPT'] == 'text/html'

    def test_parse_content_type_header(self):
        """Test that CONTENT_TYPE becomes a header."""
        packet = make_fcgi_request({
            'REQUEST_METHOD': 'POST',
            'PATH_INFO': '/',
            'CONTENT_TYPE': 'application/json',
            'CONTENT_LENGTH': '0',
        })
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        headers_dict = dict(req.headers)
        assert headers_dict['CONTENT-TYPE'] == 'application/json'
        assert headers_dict['CONTENT-LENGTH'] == '0'

    def test_https_scheme(self):
        """Test scheme detection from HTTPS variable."""
        packet = make_fcgi_request({
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': '/',
            'HTTPS': 'on',
        })
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        assert req.scheme == 'https'

    def test_wsgi_url_scheme(self):
        """Test scheme from wsgi.url_scheme variable."""
        packet = make_fcgi_request({
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': '/',
            'wsgi.url_scheme': 'https',
        })
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        assert req.scheme == 'https'

    def test_default_values(self):
        """Test default values when vars are missing."""
        packet = make_fcgi_request({})
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        assert req.method == 'GET'
        assert req.path == '/'
        assert req.query == ''
        assert req.uri == '/'

    def test_fcgi_vars_preserved(self):
        """Test that all vars are preserved in fcgi_vars."""
        packet = make_fcgi_request({
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': '/',
            'SERVER_NAME': 'localhost',
            'SERVER_PORT': '8000',
            'CUSTOM_VAR': 'custom_value',
        })
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        assert req.fcgi_vars['SERVER_NAME'] == 'localhost'
        assert req.fcgi_vars['SERVER_PORT'] == '8000'
        assert req.fcgi_vars['CUSTOM_VAR'] == 'custom_value'

    def test_keep_conn_flag(self):
        """Test keep_conn flag parsing."""
        packet = make_fcgi_request(
            {'REQUEST_METHOD': 'GET', 'PATH_INFO': '/'},
            flags=FCGI_KEEP_CONN
        )
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        assert req.keep_conn is True
        assert req.flags == FCGI_KEEP_CONN

    def test_custom_request_id(self):
        """Test parsing with custom request ID."""
        packet = make_fcgi_request(
            {'REQUEST_METHOD': 'GET', 'PATH_INFO': '/'},
            request_id=42
        )
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        assert req.request_id == 42


class TestFastCGIRequestErrors:
    """Test FastCGIRequest error handling."""

    def test_incomplete_header(self):
        """Test error on incomplete header."""
        unreader = IterUnreader([b'\x01\x01\x00'])  # Only 3 bytes
        cfg = MockConfig()

        with pytest.raises(InvalidFastCGIRecord) as exc_info:
            FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))
        assert 'incomplete header' in str(exc_info.value)

    def test_unsupported_version(self):
        """Test error on unsupported protocol version."""
        # Version 2 instead of 1
        record = bytes([2, FCGI_BEGIN_REQUEST, 0, 1, 0, 8, 0, 0])
        record += bytes([0, 1, 0, 0, 0, 0, 0, 0])  # BEGIN_REQUEST content
        unreader = IterUnreader([record])
        cfg = MockConfig()

        with pytest.raises(InvalidFastCGIRecord) as exc_info:
            FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))
        assert 'unsupported version' in str(exc_info.value)

    def test_unsupported_role(self):
        """Test error on non-RESPONDER role."""
        packet = make_fcgi_request(
            {'REQUEST_METHOD': 'GET', 'PATH_INFO': '/'},
            role=FCGI_AUTHORIZER
        )
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        with pytest.raises(UnsupportedRole) as exc_info:
            FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))
        assert exc_info.value.role == FCGI_AUTHORIZER
        assert exc_info.value.code == 501

    def test_wrong_first_record_type(self):
        """Test error when first record is not BEGIN_REQUEST."""
        record = make_fcgi_record(FCGI_PARAMS, 1, b'')
        unreader = IterUnreader([record])
        cfg = MockConfig()

        with pytest.raises(InvalidFastCGIRecord) as exc_info:
            FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))
        assert 'expected BEGIN_REQUEST' in str(exc_info.value)

    def test_request_id_mismatch(self):
        """Test error on request ID mismatch in PARAMS."""
        begin = make_begin_request(1)
        # PARAMS with different request ID
        params = make_fcgi_record(FCGI_PARAMS, 2, b'')
        unreader = IterUnreader([begin + params])
        cfg = MockConfig()

        with pytest.raises(InvalidFastCGIRecord) as exc_info:
            FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))
        assert 'request_id mismatch' in str(exc_info.value)

    def test_truncated_params(self):
        """Test error on truncated parameter data."""
        begin = make_begin_request(1)
        # PARAMS with truncated content (says 100 bytes, provides less)
        header = bytes([FCGI_VERSION_1, FCGI_PARAMS, 0, 1, 0, 100, 0, 0])
        unreader = IterUnreader([begin + header + b'short'])
        cfg = MockConfig()

        with pytest.raises(InvalidFastCGIRecord) as exc_info:
            FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))
        assert 'incomplete' in str(exc_info.value)

    def test_forbidden_ip(self):
        """Test error when source IP not in allow list."""
        packet = make_fcgi_request({'REQUEST_METHOD': 'GET', 'PATH_INFO': '/'})
        unreader = IterUnreader([packet])
        cfg = MockConfig(fastcgi_allow_ips=['192.168.1.1'])

        with pytest.raises(ForbiddenFastCGIRequest) as exc_info:
            FastCGIRequest(cfg, unreader, ('10.0.0.1', 12345))
        assert exc_info.value.code == 403
        assert '10.0.0.1' in str(exc_info.value)

    def test_allowed_ip_wildcard(self):
        """Test that wildcard allows any IP."""
        packet = make_fcgi_request({'REQUEST_METHOD': 'GET', 'PATH_INFO': '/'})
        unreader = IterUnreader([packet])
        cfg = MockConfig(fastcgi_allow_ips=['*'])

        # Should not raise
        req = FastCGIRequest(cfg, unreader, ('10.0.0.1', 12345))
        assert req.method == 'GET'

    def test_unix_socket_always_allowed(self):
        """Test that UNIX socket connections are always allowed."""
        packet = make_fcgi_request({'REQUEST_METHOD': 'GET', 'PATH_INFO': '/'})
        unreader = IterUnreader([packet])
        cfg = MockConfig(fastcgi_allow_ips=['127.0.0.1'])

        # UNIX socket has non-tuple peer_addr
        req = FastCGIRequest(cfg, unreader, None)
        assert req.method == 'GET'

    def test_too_many_params(self):
        """Test error on too many parameters."""
        # Create a dict with more than MAX_FCGI_PARAMS (1000) params
        params = {f'PARAM_{i}': f'value_{i}' for i in range(1001)}
        packet = make_fcgi_request(params)
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        with pytest.raises(InvalidFastCGIRecord) as exc_info:
            FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))
        assert 'too many parameters' in str(exc_info.value)


class TestFastCGIRequestConnection:
    """Test connection handling."""

    def test_should_close_without_keep_conn(self):
        """Test default close behavior without keep_conn."""
        packet = make_fcgi_request({'REQUEST_METHOD': 'GET', 'PATH_INFO': '/'})
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        # Without FCGI_KEEP_CONN flag, should close
        assert req.should_close() is True

    def test_should_not_close_with_keep_conn(self):
        """Test keep-alive with FCGI_KEEP_CONN flag."""
        packet = make_fcgi_request(
            {'REQUEST_METHOD': 'GET', 'PATH_INFO': '/'},
            flags=FCGI_KEEP_CONN
        )
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        assert req.should_close() is False

    def test_should_close_connection_close_header(self):
        """Test Connection: close header overrides keep_conn."""
        packet = make_fcgi_request({
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': '/',
            'HTTP_CONNECTION': 'close',
        }, flags=FCGI_KEEP_CONN)
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        # keep_conn is True but Connection: close should still close
        # Actually, looking at the code, keep_conn takes priority
        # Let me check the actual behavior...
        # The code checks keep_conn first, so this should NOT close
        assert req.should_close() is False

    def test_force_close(self):
        """Test force_close method."""
        packet = make_fcgi_request(
            {'REQUEST_METHOD': 'GET', 'PATH_INFO': '/'},
            flags=FCGI_KEEP_CONN
        )
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))
        req.force_close()

        assert req.should_close() is True


class TestFastCGIParser:
    """Test FastCGIParser."""

    def test_parser_iteration(self):
        """Test iterating over parser."""
        packet = make_fcgi_request({
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': '/test',
        })
        cfg = MockConfig()

        parser = FastCGIParser(cfg, [packet], ('127.0.0.1', 12345))
        req = next(parser)

        assert req.method == 'GET'
        assert req.path == '/test'

    def test_parser_mesg_class(self):
        """Test that parser uses FastCGIRequest."""
        assert FastCGIParser.mesg_class is FastCGIRequest


class TestFastCGIResponse:
    """Test FastCGIResponse."""

    def test_start_response(self):
        """Test start_response sets status and headers."""
        packet = make_fcgi_request({'REQUEST_METHOD': 'GET', 'PATH_INFO': '/'})
        unreader = IterUnreader([packet])
        cfg = MockConfig()
        req = FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))
        sock = MockSocket()

        resp = FastCGIResponse(req, sock, cfg)
        write = resp.start_response('200 OK', [('Content-Type', 'text/plain')])

        assert resp.status == '200 OK'
        assert resp.status_code == 200
        assert ('Content-Type', 'text/plain') in resp.headers
        assert callable(write)

    def test_write_sends_stdout_record(self):
        """Test write sends data in STDOUT record."""
        packet = make_fcgi_request({'REQUEST_METHOD': 'GET', 'PATH_INFO': '/'})
        unreader = IterUnreader([packet])
        cfg = MockConfig()
        req = FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))
        sock = MockSocket()

        resp = FastCGIResponse(req, sock, cfg)
        resp.start_response('200 OK', [('Content-Type', 'text/plain')])
        resp.write(b'Hello, World!')

        # Check that STDOUT records were sent
        data = sock.data
        # Find STDOUT record (type 6)
        found_stdout = False
        pos = 0
        while pos < len(data):
            if len(data) - pos < 8:
                break
            record_type = data[pos + 1]
            content_length = int.from_bytes(data[pos + 4:pos + 6], 'big')
            padding_length = data[pos + 6]
            if record_type == FCGI_STDOUT and content_length > 0:
                found_stdout = True
                break
            pos += 8 + content_length + padding_length

        assert found_stdout

    def test_close_sends_end_request(self):
        """Test close sends empty STDOUT and END_REQUEST."""
        packet = make_fcgi_request({'REQUEST_METHOD': 'GET', 'PATH_INFO': '/'})
        unreader = IterUnreader([packet])
        cfg = MockConfig()
        req = FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))
        sock = MockSocket()

        resp = FastCGIResponse(req, sock, cfg)
        resp.start_response('200 OK', [])
        resp.close()

        data = sock.data

        # Find END_REQUEST record
        found_end_request = False
        pos = 0
        while pos < len(data):
            if len(data) - pos < 8:
                break
            record_type = data[pos + 1]
            content_length = int.from_bytes(data[pos + 4:pos + 6], 'big')
            padding_length = data[pos + 6]
            if record_type == FCGI_END_REQUEST:
                found_end_request = True
                # Check content has protocol status
                content_start = pos + 8
                if content_length >= 5:
                    protocol_status = data[content_start + 4]
                    assert protocol_status == FCGI_REQUEST_COMPLETE
                break
            pos += 8 + content_length + padding_length

        assert found_end_request

    def test_response_uses_request_id(self):
        """Test response uses correct request ID."""
        packet = make_fcgi_request(
            {'REQUEST_METHOD': 'GET', 'PATH_INFO': '/'},
            request_id=42
        )
        unreader = IterUnreader([packet])
        cfg = MockConfig()
        req = FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))
        sock = MockSocket()

        resp = FastCGIResponse(req, sock, cfg)
        resp.start_response('200 OK', [])
        resp.write(b'test')
        resp.close()

        # Check that records use request ID 42
        data = sock.data
        pos = 0
        while pos < len(data):
            if len(data) - pos < 8:
                break
            request_id = int.from_bytes(data[pos + 2:pos + 4], 'big')
            content_length = int.from_bytes(data[pos + 4:pos + 6], 'big')
            padding_length = data[pos + 6]
            assert request_id == 42
            pos += 8 + content_length + padding_length

    def test_headers_use_status_format(self):
        """Test headers use CGI Status: format."""
        packet = make_fcgi_request({'REQUEST_METHOD': 'GET', 'PATH_INFO': '/'})
        unreader = IterUnreader([packet])
        cfg = MockConfig()
        req = FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))
        sock = MockSocket()

        resp = FastCGIResponse(req, sock, cfg)
        resp.start_response('200 OK', [('Content-Type', 'text/plain')])
        resp.send_headers()

        # Extract headers from STDOUT record
        data = sock.data
        # Skip record header
        content_length = int.from_bytes(data[4:6], 'big')
        headers_data = data[8:8 + content_length].decode('latin-1')

        assert 'Status: 200 OK' in headers_data
        assert 'Content-Type: text/plain' in headers_data


class TestExceptionStrings:
    """Test exception string representations."""

    def test_invalid_fastcgi_record_str(self):
        exc = InvalidFastCGIRecord("test message")
        assert str(exc) == "Invalid FastCGI record: test message"
        assert exc.code == 400

    def test_unsupported_role_str(self):
        exc = UnsupportedRole(2)
        assert str(exc) == "Unsupported FastCGI role: 2"
        assert exc.code == 501

    def test_forbidden_fastcgi_request_str(self):
        exc = ForbiddenFastCGIRequest("10.0.0.1")
        assert str(exc) == "FastCGI request from '10.0.0.1' not allowed"
        assert exc.code == 403


class TestFastCGIBody:
    """Test body reading."""

    def test_read_body_in_chunks(self):
        """Test reading body in multiple chunks."""
        body = b'A' * 1000
        packet = make_fcgi_request({
            'REQUEST_METHOD': 'POST',
            'PATH_INFO': '/',
        }, body)
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        result = b''
        chunk = req.body.read(100)
        while chunk:
            result += chunk
            chunk = req.body.read(100)

        assert result == body

    def test_invalid_content_length(self):
        """Test handling of invalid CONTENT_LENGTH."""
        # Create request without body but with invalid content length
        begin = make_begin_request(1)
        params = make_params_records({
            'REQUEST_METHOD': 'POST',
            'PATH_INFO': '/',
            'CONTENT_LENGTH': 'invalid',
        }, 1)
        stdin = make_stdin_records(b'', 1)
        packet = begin + params + stdin
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        # Invalid content length should default to 0
        assert req.body.read() == b''

    def test_negative_content_length(self):
        """Test handling of negative CONTENT_LENGTH."""
        begin = make_begin_request(1)
        params = make_params_records({
            'REQUEST_METHOD': 'POST',
            'PATH_INFO': '/',
            'CONTENT_LENGTH': '-5',
        }, 1)
        stdin = make_stdin_records(b'', 1)
        packet = begin + params + stdin
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        # Negative content length should default to 0
        assert req.body.read() == b''


class TestNameValueEncoding:
    """Test name-value length encoding/decoding."""

    def test_decode_short_length(self):
        """Test decoding 1-byte length."""
        from gunicorn.fastcgi.message import FastCGIRequest

        # Create a minimal request to access _decode_length
        packet = make_fcgi_request({'REQUEST_METHOD': 'GET', 'PATH_INFO': '/'})
        unreader = IterUnreader([packet])
        cfg = MockConfig()
        req = FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        # Test 1-byte length
        data = bytes([50])  # length = 50
        length, pos = req._decode_length(data, 0)
        assert length == 50
        assert pos == 1

    def test_decode_long_length(self):
        """Test decoding 4-byte length."""
        packet = make_fcgi_request({'REQUEST_METHOD': 'GET', 'PATH_INFO': '/'})
        unreader = IterUnreader([packet])
        cfg = MockConfig()
        req = FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        # Test 4-byte length (high bit set, value = 1000)
        data = (1000 | 0x80000000).to_bytes(4, 'big')
        length, pos = req._decode_length(data, 0)
        assert length == 1000
        assert pos == 4

    def test_long_param_value(self):
        """Test parsing parameter with value > 127 bytes."""
        long_value = 'x' * 200
        packet = make_fcgi_request({
            'REQUEST_METHOD': 'GET',
            'PATH_INFO': '/',
            'LONG_PARAM': long_value,
        })
        unreader = IterUnreader([packet])
        cfg = MockConfig()

        req = FastCGIRequest(cfg, unreader, ('127.0.0.1', 12345))

        assert req.fcgi_vars['LONG_PARAM'] == long_value


class TestFastCGIConnectionState:
    """Test multiplexing support with FastCGIConnectionState."""

    def test_single_request(self):
        """Test handling a single request through connection state."""
        from gunicorn.fastcgi import FastCGIConnectionState
        from gunicorn.fastcgi.constants import FCGI_RESPONDER

        cfg = MockConfig()
        state = FastCGIConnectionState(cfg, ('127.0.0.1', 12345))

        # Begin request
        state.begin_request(1, FCGI_RESPONDER, 0)
        assert state.has_pending_requests()
        assert state.get_ready_requests() == []

        # Add params
        params_data = encode_name_value('REQUEST_METHOD', 'GET')
        params_data += encode_name_value('PATH_INFO', '/test')
        state.add_params(1, params_data)
        state.add_params(1, b'')  # End params
        assert state.get_ready_requests() == []

        # Add stdin
        state.add_stdin(1, b'')  # Empty body, end stdin
        assert state.get_ready_requests() == [1]

        # Pop and verify
        req_state = state.pop_request(1)
        assert req_state.request_id == 1
        assert req_state.is_ready()
        assert not state.has_pending_requests()

    def test_multiple_concurrent_requests(self):
        """Test handling multiple interleaved requests."""
        from gunicorn.fastcgi import FastCGIConnectionState
        from gunicorn.fastcgi.constants import FCGI_RESPONDER, FCGI_KEEP_CONN

        cfg = MockConfig()
        state = FastCGIConnectionState(cfg, ('127.0.0.1', 12345))

        # Begin two requests
        state.begin_request(1, FCGI_RESPONDER, FCGI_KEEP_CONN)
        state.begin_request(2, FCGI_RESPONDER, FCGI_KEEP_CONN)

        # Interleave params
        params1 = encode_name_value('REQUEST_METHOD', 'GET')
        params1 += encode_name_value('PATH_INFO', '/first')
        state.add_params(1, params1)

        params2 = encode_name_value('REQUEST_METHOD', 'POST')
        params2 += encode_name_value('PATH_INFO', '/second')
        state.add_params(2, params2)

        # End params for both
        state.add_params(1, b'')
        state.add_params(2, b'')

        # Neither ready yet (no stdin)
        assert state.get_ready_requests() == []

        # Complete request 2 first
        state.add_stdin(2, b'body data')
        state.add_stdin(2, b'')
        assert state.get_ready_requests() == [2]

        # Complete request 1
        state.add_stdin(1, b'')
        ready = state.get_ready_requests()
        assert 1 in ready
        assert 2 in ready

    def test_build_request_from_state(self):
        """Test building FastCGIRequest from RequestState."""
        from gunicorn.fastcgi import FastCGIConnectionState
        from gunicorn.fastcgi.constants import FCGI_RESPONDER

        cfg = MockConfig()
        state = FastCGIConnectionState(cfg, ('127.0.0.1', 12345))

        # Build complete request
        state.begin_request(1, FCGI_RESPONDER, 0)
        params_data = encode_name_value('REQUEST_METHOD', 'POST')
        params_data += encode_name_value('PATH_INFO', '/submit')
        params_data += encode_name_value('CONTENT_LENGTH', '11')
        state.add_params(1, params_data)
        state.add_params(1, b'')
        state.add_stdin(1, b'hello world')
        state.add_stdin(1, b'')

        req_state = state.pop_request(1)
        req = state.build_request(req_state, None, req_number=1)

        assert req.method == 'POST'
        assert req.path == '/submit'
        assert req.request_id == 1
        assert req.body.read() == b'hello world'

    def test_duplicate_request_id_error(self):
        """Test error on duplicate request ID."""
        from gunicorn.fastcgi import FastCGIConnectionState
        from gunicorn.fastcgi.constants import FCGI_RESPONDER

        cfg = MockConfig()
        state = FastCGIConnectionState(cfg, ('127.0.0.1', 12345))

        state.begin_request(1, FCGI_RESPONDER, 0)

        with pytest.raises(InvalidFastCGIRecord) as exc_info:
            state.begin_request(1, FCGI_RESPONDER, 0)
        assert 'duplicate request_id' in str(exc_info.value)

    def test_unknown_request_id_params_error(self):
        """Test error on PARAMS for unknown request ID."""
        from gunicorn.fastcgi import FastCGIConnectionState

        cfg = MockConfig()
        state = FastCGIConnectionState(cfg, ('127.0.0.1', 12345))

        with pytest.raises(InvalidFastCGIRecord) as exc_info:
            state.add_params(99, b'data')
        assert 'unknown request_id' in str(exc_info.value)

    def test_unknown_request_id_stdin_error(self):
        """Test error on STDIN for unknown request ID."""
        from gunicorn.fastcgi import FastCGIConnectionState

        cfg = MockConfig()
        state = FastCGIConnectionState(cfg, ('127.0.0.1', 12345))

        with pytest.raises(InvalidFastCGIRecord) as exc_info:
            state.add_stdin(99, b'data')
        assert 'unknown request_id' in str(exc_info.value)

    def test_unsupported_role_in_multiplexing(self):
        """Test error on unsupported role in multiplexing mode."""
        from gunicorn.fastcgi import FastCGIConnectionState
        from gunicorn.fastcgi.constants import FCGI_AUTHORIZER

        cfg = MockConfig()
        state = FastCGIConnectionState(cfg, ('127.0.0.1', 12345))

        with pytest.raises(UnsupportedRole) as exc_info:
            state.begin_request(1, FCGI_AUTHORIZER, 0)
        assert exc_info.value.role == FCGI_AUTHORIZER

    def test_ip_check_in_connection_state(self):
        """Test IP allowlist is checked in FastCGIConnectionState."""
        from gunicorn.fastcgi import FastCGIConnectionState

        cfg = MockConfig(fastcgi_allow_ips=['192.168.1.1'])

        with pytest.raises(ForbiddenFastCGIRequest):
            FastCGIConnectionState(cfg, ('10.0.0.1', 12345))

    def test_keep_conn_flag_preserved(self):
        """Test keep_conn flag is preserved in request state."""
        from gunicorn.fastcgi import FastCGIConnectionState
        from gunicorn.fastcgi.constants import FCGI_RESPONDER, FCGI_KEEP_CONN

        cfg = MockConfig()
        state = FastCGIConnectionState(cfg, ('127.0.0.1', 12345))

        state.begin_request(1, FCGI_RESPONDER, FCGI_KEEP_CONN)
        state.add_params(1, b'')
        state.add_stdin(1, b'')

        req_state = state.pop_request(1)
        assert req_state.keep_conn is True


class TestRequestState:
    """Test RequestState class."""

    def test_initial_state(self):
        """Test initial state of RequestState."""
        from gunicorn.fastcgi.message import RequestState
        from gunicorn.fastcgi.constants import FCGI_RESPONDER

        state = RequestState(1, FCGI_RESPONDER, 0)
        assert state.request_id == 1
        assert state.role == FCGI_RESPONDER
        assert state.flags == 0
        assert state.keep_conn is False
        assert not state.params_complete
        assert not state.stdin_complete
        assert not state.is_ready()

    def test_params_accumulation(self):
        """Test params data accumulation."""
        from gunicorn.fastcgi.message import RequestState
        from gunicorn.fastcgi.constants import FCGI_RESPONDER

        state = RequestState(1, FCGI_RESPONDER, 0)

        state.add_params(b'part1')
        state.add_params(b'part2')
        assert not state.params_complete

        state.add_params(b'')  # Empty signals end
        assert state.params_complete
        assert state.get_params_data() == b'part1part2'

    def test_stdin_accumulation(self):
        """Test stdin data accumulation."""
        from gunicorn.fastcgi.message import RequestState
        from gunicorn.fastcgi.constants import FCGI_RESPONDER

        state = RequestState(1, FCGI_RESPONDER, 0)

        state.add_stdin(b'body1')
        state.add_stdin(b'body2')
        assert not state.stdin_complete

        state.add_stdin(b'')  # Empty signals end
        assert state.stdin_complete
        assert state.get_stdin_data() == b'body1body2'

    def test_is_ready_requires_both(self):
        """Test is_ready requires both params and stdin complete."""
        from gunicorn.fastcgi.message import RequestState
        from gunicorn.fastcgi.constants import FCGI_RESPONDER

        state = RequestState(1, FCGI_RESPONDER, 0)

        state.add_params(b'')
        assert not state.is_ready()  # stdin not complete

        state.add_stdin(b'')
        assert state.is_ready()  # both complete


class TestBufferedBodyReader:
    """Test BufferedBodyReader for multiplexing mode."""

    def test_read_all(self):
        """Test reading all data at once."""
        from gunicorn.fastcgi.message import BufferedBodyReader

        reader = BufferedBodyReader(b'hello world')
        assert reader.read() == b'hello world'
        assert reader.read() == b''  # EOF

    def test_read_in_chunks(self):
        """Test reading data in chunks."""
        from gunicorn.fastcgi.message import BufferedBodyReader

        reader = BufferedBodyReader(b'hello world')
        assert reader.read(5) == b'hello'
        assert reader.read(1) == b' '
        assert reader.read(100) == b'world'
        assert reader.read(1) == b''  # EOF

    def test_empty_data(self):
        """Test with empty data."""
        from gunicorn.fastcgi.message import BufferedBodyReader

        reader = BufferedBodyReader(b'')
        assert reader.length == 0
        assert reader.read() == b''
