#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import re

from gunicorn.http.message import TOKEN_RE
from gunicorn.http.errors import InvalidHeader, InvalidHeaderName
from gunicorn import SERVER, util
from gunicorn.fastcgi.constants import (
    FCGI_VERSION_1,
    FCGI_STDOUT,
    FCGI_END_REQUEST,
    FCGI_REQUEST_COMPLETE,
    FCGI_MAX_CONTENT_LEN,
)


# RFC9110 5.5: field-vchar = VCHAR / obs-text
# RFC4234 B.1: VCHAR = 0x21-x07E = printable ASCII
HEADER_VALUE_RE = re.compile(r'[ \t\x21-\x7e\x80-\xff]*')


class FastCGIResponse:
    """FastCGI protocol response handler.

    Wraps WSGI response output in FastCGI STDOUT records and sends
    END_REQUEST when complete.

    Key differences from HTTP Response:
    - Headers sent as "Status: 200 OK\\r\\n..." (not "HTTP/1.1 200 OK")
    - All output wrapped in STDOUT records (max 64KB each)
    - Must send empty STDOUT record to signal end of output
    - Must send END_REQUEST record with status on close
    """

    def __init__(self, req, sock, cfg):
        self.req = req
        self.sock = sock
        self.version = SERVER
        self.status = None
        self.chunked = False  # FastCGI doesn't use HTTP chunked encoding
        self.must_close = False
        self.headers = []
        self.headers_sent = False
        self.response_length = None
        self.sent = 0
        self.upgrade = False
        self.cfg = cfg
        self.request_id = req.request_id

    def force_close(self):
        self.must_close = True

    def should_close(self):
        if self.must_close or self.req.should_close():
            return True
        # FastCGI connections can be reused based on keep_conn flag
        return False

    def start_response(self, status, headers, exc_info=None):
        if exc_info:
            try:
                if self.status and self.headers_sent:
                    util.reraise(exc_info[0], exc_info[1], exc_info[2])
            finally:
                exc_info = None
        elif self.status is not None:
            raise AssertionError("Response headers already set!")

        self.status = status

        # Get the status code from the response
        try:
            self.status_code = int(self.status.split()[0])
        except ValueError:
            self.status_code = None

        self.process_headers(headers)
        return self.write

    def process_headers(self, headers):
        for name, value in headers:
            if not isinstance(name, str):
                raise TypeError('%r is not a string' % name)

            if not TOKEN_RE.fullmatch(name):
                raise InvalidHeaderName('%r' % name)

            if not isinstance(value, str):
                raise TypeError('%r is not a string' % value)

            if not HEADER_VALUE_RE.fullmatch(value):
                raise InvalidHeader('%r' % value)

            # RFC9110 5.5
            value = value.strip(" \t")
            lname = name.lower()
            if lname == "content-length":
                self.response_length = int(value)
            elif util.is_hoppish(name):
                if lname == "connection":
                    if value.lower() == "upgrade":
                        self.upgrade = True
                elif lname == "upgrade":
                    if value.lower() == "websocket":
                        self.headers.append((name, value))
                # ignore hopbyhop headers
                continue
            self.headers.append((name, value))

    def default_headers(self):
        """Build CGI-style headers for FastCGI response.

        FastCGI uses CGI-style headers with "Status:" instead of HTTP status line.
        """
        headers = [
            "Status: %s\r\n" % self.status,
            "Server: %s\r\n" % self.version,
            "Date: %s\r\n" % util.http_date(),
        ]
        return headers

    def send_headers(self):
        if self.headers_sent:
            return

        tosend = self.default_headers()
        tosend.extend(["%s: %s\r\n" % (k, v) for k, v in self.headers])

        header_str = "%s\r\n" % "".join(tosend)
        header_bytes = util.to_bytestring(header_str, "latin-1")

        # Send headers wrapped in STDOUT record(s)
        self._write_stdout(header_bytes)
        self.headers_sent = True

    def write(self, arg):
        self.send_headers()
        if not isinstance(arg, bytes):
            raise TypeError('%r is not a byte' % arg)

        arglen = len(arg)
        tosend = arglen

        if self.response_length is not None:
            if self.sent >= self.response_length:
                return
            tosend = min(self.response_length - self.sent, tosend)
            if tosend < arglen:
                arg = arg[:tosend]

        if tosend == 0:
            return

        self.sent += tosend
        self._write_stdout(arg)

    def _write_stdout(self, data):
        """Write data wrapped in STDOUT record(s).

        Splits data into chunks of max 65535 bytes per record.
        """
        offset = 0
        while offset < len(data):
            chunk_size = min(len(data) - offset, FCGI_MAX_CONTENT_LEN)
            chunk = data[offset:offset + chunk_size]
            self._write_record(FCGI_STDOUT, chunk)
            offset += chunk_size

    def _write_record(self, record_type, content):
        """Build and send a FastCGI record.

        Record format:
        - version (1 byte): FCGI_VERSION_1
        - type (1 byte): record type
        - requestId (2 bytes BE): request ID
        - contentLength (2 bytes BE): content length
        - paddingLength (1 byte): padding length
        - reserved (1 byte): 0
        - content (contentLength bytes)
        - padding (paddingLength bytes)
        """
        content_length = len(content)
        # Pad to 8-byte boundary for efficiency (optional but recommended)
        padding_length = (8 - (content_length % 8)) % 8

        header = bytes([
            FCGI_VERSION_1,
            record_type,
            (self.request_id >> 8) & 0xFF,
            self.request_id & 0xFF,
            (content_length >> 8) & 0xFF,
            content_length & 0xFF,
            padding_length,
            0,  # reserved
        ])

        # Send header + content + padding
        self.sock.sendall(header + content + b'\x00' * padding_length)

    def _write_end_request(self, app_status=0, protocol_status=FCGI_REQUEST_COMPLETE):
        """Send END_REQUEST record.

        END_REQUEST body (8 bytes):
        - appStatus (4 bytes BE): application exit status
        - protocolStatus (1 byte): FCGI_REQUEST_COMPLETE, etc.
        - reserved (3 bytes): 0
        """
        content = bytes([
            (app_status >> 24) & 0xFF,
            (app_status >> 16) & 0xFF,
            (app_status >> 8) & 0xFF,
            app_status & 0xFF,
            protocol_status,
            0, 0, 0,  # reserved
        ])
        self._write_record(FCGI_END_REQUEST, content)

    def can_sendfile(self):
        # FastCGI wraps all data in records, so sendfile optimization
        # would require special handling. Disable for simplicity.
        return False

    def sendfile(self, respiter):
        # Not supported for FastCGI - fall back to regular write
        return False

    def write_file(self, respiter):
        for item in respiter:
            self.write(item)

    def close(self):
        """Close the response.

        Sends empty STDOUT record (end of output) and END_REQUEST record.
        """
        if not self.headers_sent:
            self.send_headers()

        # Send empty STDOUT to signal end of output
        self._write_record(FCGI_STDOUT, b'')

        # Send END_REQUEST
        self._write_end_request()
