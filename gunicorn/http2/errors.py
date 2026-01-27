# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
HTTP/2 specific exceptions.

These exceptions map to HTTP/2 error codes defined in RFC 7540.
"""


class HTTP2ErrorCode:
    """HTTP/2 Error Codes (RFC 7540 Section 7)."""

    NO_ERROR = 0x0
    PROTOCOL_ERROR = 0x1
    INTERNAL_ERROR = 0x2
    FLOW_CONTROL_ERROR = 0x3
    SETTINGS_TIMEOUT = 0x4
    STREAM_CLOSED = 0x5
    FRAME_SIZE_ERROR = 0x6
    REFUSED_STREAM = 0x7
    CANCEL = 0x8
    COMPRESSION_ERROR = 0x9
    CONNECT_ERROR = 0xa
    ENHANCE_YOUR_CALM = 0xb
    INADEQUATE_SECURITY = 0xc
    HTTP_1_1_REQUIRED = 0xd


class HTTP2Error(Exception):
    """Base exception for HTTP/2 errors."""

    error_code = 0x0  # NO_ERROR

    def __init__(self, message=None, error_code=None):
        self.message = message or self.__class__.__doc__
        if error_code is not None:
            self.error_code = error_code
        super().__init__(self.message)


class HTTP2ProtocolError(HTTP2Error):
    """Protocol error detected."""

    error_code = 0x1  # PROTOCOL_ERROR


class HTTP2InternalError(HTTP2Error):
    """Internal error occurred."""

    error_code = 0x2  # INTERNAL_ERROR


class HTTP2FlowControlError(HTTP2Error):
    """Flow control limits exceeded."""

    error_code = 0x3  # FLOW_CONTROL_ERROR


class HTTP2SettingsTimeout(HTTP2Error):
    """Settings acknowledgment timeout."""

    error_code = 0x4  # SETTINGS_TIMEOUT


class HTTP2StreamClosed(HTTP2Error):
    """Stream was closed."""

    error_code = 0x5  # STREAM_CLOSED


class HTTP2FrameSizeError(HTTP2Error):
    """Frame size is incorrect."""

    error_code = 0x6  # FRAME_SIZE_ERROR


class HTTP2RefusedStream(HTTP2Error):
    """Stream was refused."""

    error_code = 0x7  # REFUSED_STREAM


class HTTP2Cancel(HTTP2Error):
    """Stream was cancelled."""

    error_code = 0x8  # CANCEL


class HTTP2CompressionError(HTTP2Error):
    """Compression state error."""

    error_code = 0x9  # COMPRESSION_ERROR


class HTTP2ConnectError(HTTP2Error):
    """Connection error during CONNECT."""

    error_code = 0xa  # CONNECT_ERROR


class HTTP2EnhanceYourCalm(HTTP2Error):
    """Peer is generating excessive load."""

    error_code = 0xb  # ENHANCE_YOUR_CALM


class HTTP2InadequateSecurity(HTTP2Error):
    """Transport security is inadequate."""

    error_code = 0xc  # INADEQUATE_SECURITY


class HTTP2RequiresHTTP11(HTTP2Error):
    """HTTP/1.1 is required for this request."""

    error_code = 0xd  # HTTP_1_1_REQUIRED


class HTTP2StreamError(HTTP2Error):
    """Error specific to a single stream."""

    def __init__(self, stream_id, message=None, error_code=None):
        self.stream_id = stream_id
        super().__init__(message, error_code)

    def __str__(self):
        return f"Stream {self.stream_id}: {self.message}"


class HTTP2ConnectionError(HTTP2Error):
    """Error affecting the entire connection."""


class HTTP2ConfigurationError(HTTP2Error):
    """Invalid HTTP/2 configuration."""


class HTTP2NotAvailable(HTTP2Error):
    """HTTP/2 support is not available (h2 library not installed)."""

    def __init__(self, message=None):
        message = message or "HTTP/2 requires the h2 library: pip install gunicorn[http2]"
        super().__init__(message)


__all__ = [
    'HTTP2ErrorCode',
    'HTTP2Error',
    'HTTP2ProtocolError',
    'HTTP2InternalError',
    'HTTP2FlowControlError',
    'HTTP2SettingsTimeout',
    'HTTP2StreamClosed',
    'HTTP2FrameSizeError',
    'HTTP2RefusedStream',
    'HTTP2Cancel',
    'HTTP2CompressionError',
    'HTTP2ConnectError',
    'HTTP2EnhanceYourCalm',
    'HTTP2InadequateSecurity',
    'HTTP2RequiresHTTP11',
    'HTTP2StreamError',
    'HTTP2ConnectionError',
    'HTTP2ConfigurationError',
    'HTTP2NotAvailable',
]
