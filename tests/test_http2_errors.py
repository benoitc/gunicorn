# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for HTTP/2 error classes."""

import pytest

from gunicorn.http2.errors import (
    HTTP2Error,
    HTTP2ProtocolError,
    HTTP2InternalError,
    HTTP2FlowControlError,
    HTTP2SettingsTimeout,
    HTTP2StreamClosed,
    HTTP2FrameSizeError,
    HTTP2RefusedStream,
    HTTP2Cancel,
    HTTP2CompressionError,
    HTTP2ConnectError,
    HTTP2EnhanceYourCalm,
    HTTP2InadequateSecurity,
    HTTP2RequiresHTTP11,
    HTTP2StreamError,
    HTTP2ConnectionError,
    HTTP2ConfigurationError,
    HTTP2NotAvailable,
)


class TestHTTP2ErrorCodes:
    """Test RFC 7540 error codes."""

    def test_no_error(self):
        err = HTTP2Error()
        assert err.error_code == 0x0

    def test_protocol_error(self):
        err = HTTP2ProtocolError()
        assert err.error_code == 0x1

    def test_internal_error(self):
        err = HTTP2InternalError()
        assert err.error_code == 0x2

    def test_flow_control_error(self):
        err = HTTP2FlowControlError()
        assert err.error_code == 0x3

    def test_settings_timeout(self):
        err = HTTP2SettingsTimeout()
        assert err.error_code == 0x4

    def test_stream_closed(self):
        err = HTTP2StreamClosed()
        assert err.error_code == 0x5

    def test_frame_size_error(self):
        err = HTTP2FrameSizeError()
        assert err.error_code == 0x6

    def test_refused_stream(self):
        err = HTTP2RefusedStream()
        assert err.error_code == 0x7

    def test_cancel(self):
        err = HTTP2Cancel()
        assert err.error_code == 0x8

    def test_compression_error(self):
        err = HTTP2CompressionError()
        assert err.error_code == 0x9

    def test_connect_error(self):
        err = HTTP2ConnectError()
        assert err.error_code == 0xa

    def test_enhance_your_calm(self):
        err = HTTP2EnhanceYourCalm()
        assert err.error_code == 0xb

    def test_inadequate_security(self):
        err = HTTP2InadequateSecurity()
        assert err.error_code == 0xc

    def test_http11_required(self):
        err = HTTP2RequiresHTTP11()
        assert err.error_code == 0xd


class TestHTTP2ErrorInheritance:
    """Test error class inheritance."""

    def test_all_inherit_from_http2error(self):
        error_classes = [
            HTTP2ProtocolError,
            HTTP2InternalError,
            HTTP2FlowControlError,
            HTTP2SettingsTimeout,
            HTTP2StreamClosed,
            HTTP2FrameSizeError,
            HTTP2RefusedStream,
            HTTP2Cancel,
            HTTP2CompressionError,
            HTTP2ConnectError,
            HTTP2EnhanceYourCalm,
            HTTP2InadequateSecurity,
            HTTP2RequiresHTTP11,
            HTTP2StreamError,
            HTTP2ConnectionError,
            HTTP2ConfigurationError,
            HTTP2NotAvailable,
        ]
        for cls in error_classes:
            assert issubclass(cls, HTTP2Error)
            assert issubclass(cls, Exception)

    def test_http2error_is_exception(self):
        assert issubclass(HTTP2Error, Exception)


class TestHTTP2ErrorMessages:
    """Test error message handling."""

    def test_default_message_from_docstring(self):
        err = HTTP2ProtocolError()
        assert err.message == "Protocol error detected."
        assert str(err) == "Protocol error detected."

    def test_custom_message(self):
        err = HTTP2ProtocolError("Custom error message")
        assert err.message == "Custom error message"
        assert str(err) == "Custom error message"

    def test_custom_error_code(self):
        err = HTTP2Error("Test", error_code=0xFF)
        assert err.error_code == 0xFF

    def test_message_and_error_code(self):
        err = HTTP2ProtocolError("Custom", error_code=0x99)
        assert err.message == "Custom"
        assert err.error_code == 0x99


class TestHTTP2StreamError:
    """Test stream-specific error handling."""

    def test_stream_id_in_error(self):
        err = HTTP2StreamError(stream_id=5)
        assert err.stream_id == 5

    def test_stream_error_str(self):
        err = HTTP2StreamError(stream_id=7, message="Stream reset")
        assert "Stream 7" in str(err)
        assert "Stream reset" in str(err)

    def test_stream_error_default_message(self):
        err = HTTP2StreamError(stream_id=3)
        assert err.stream_id == 3
        assert "Stream 3" in str(err)

    def test_stream_error_with_error_code(self):
        err = HTTP2StreamError(stream_id=1, error_code=0x8)
        assert err.stream_id == 1
        assert err.error_code == 0x8


class TestHTTP2ConnectionError:
    """Test connection-level error handling."""

    def test_connection_error_basic(self):
        err = HTTP2ConnectionError("Connection failed")
        assert str(err) == "Connection failed"
        assert isinstance(err, HTTP2Error)


class TestHTTP2ConfigurationError:
    """Test configuration error handling."""

    def test_configuration_error_basic(self):
        err = HTTP2ConfigurationError("Invalid setting")
        assert str(err) == "Invalid setting"
        assert isinstance(err, HTTP2Error)


class TestHTTP2NotAvailable:
    """Test HTTP/2 unavailable error."""

    def test_default_message(self):
        err = HTTP2NotAvailable()
        assert "h2 library" in err.message
        assert "pip install" in err.message

    def test_custom_message(self):
        err = HTTP2NotAvailable("Custom unavailable message")
        assert err.message == "Custom unavailable message"

    def test_inherits_from_http2error(self):
        err = HTTP2NotAvailable()
        assert isinstance(err, HTTP2Error)


class TestErrorRaising:
    """Test that errors can be properly raised and caught."""

    def test_raise_and_catch_http2error(self):
        with pytest.raises(HTTP2Error):
            raise HTTP2ProtocolError("Test")

    def test_raise_and_catch_specific(self):
        with pytest.raises(HTTP2ProtocolError):
            raise HTTP2ProtocolError("Test")

    def test_raise_stream_error(self):
        with pytest.raises(HTTP2StreamError) as exc_info:
            raise HTTP2StreamError(stream_id=5, message="Test stream error")
        assert exc_info.value.stream_id == 5

    def test_error_chaining(self):
        try:
            try:
                raise ValueError("Original")
            except ValueError as e:
                raise HTTP2InternalError("Wrapped") from e
        except HTTP2InternalError as err:
            assert err.__cause__ is not None
            assert isinstance(err.__cause__, ValueError)
