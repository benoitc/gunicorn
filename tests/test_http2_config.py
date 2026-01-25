# -*- coding: utf-8 -
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for HTTP/2 configuration settings."""

import pytest

from gunicorn import config
from gunicorn.config import Config


class TestHttpProtocolsConfig:
    """Test http_protocols configuration setting."""

    def test_default_is_h1(self):
        c = Config()
        assert c.http_protocols == ["h1"]

    def test_set_h1_only(self):
        c = Config()
        c.set("http_protocols", "h1")
        assert c.http_protocols == ["h1"]

    def test_set_h2_only(self):
        c = Config()
        c.set("http_protocols", "h2")
        assert c.http_protocols == ["h2"]

    def test_set_h1_and_h2(self):
        c = Config()
        c.set("http_protocols", "h2,h1")
        assert c.http_protocols == ["h2", "h1"]

    def test_set_h1_h2_order_preserved(self):
        c = Config()
        c.set("http_protocols", "h1,h2")
        assert c.http_protocols == ["h1", "h2"]

    def test_whitespace_handling(self):
        c = Config()
        c.set("http_protocols", " h1 , h2 ")
        assert c.http_protocols == ["h1", "h2"]

    def test_case_insensitive(self):
        c = Config()
        c.set("http_protocols", "H1,H2")
        assert c.http_protocols == ["h1", "h2"]

    def test_empty_string_defaults_to_h1(self):
        c = Config()
        c.set("http_protocols", "")
        assert c.http_protocols == ["h1"]

    def test_none_defaults_to_h1(self):
        c = Config()
        c.set("http_protocols", None)
        assert c.http_protocols == ["h1"]

    def test_invalid_protocol(self):
        c = Config()
        with pytest.raises(ValueError) as exc_info:
            c.set("http_protocols", "h4")
        assert "Invalid protocol" in str(exc_info.value)
        assert "h4" in str(exc_info.value)

    def test_invalid_type(self):
        c = Config()
        with pytest.raises(TypeError) as exc_info:
            c.set("http_protocols", 123)
        assert "must be a string" in str(exc_info.value)

    def test_invalid_type_list(self):
        c = Config()
        with pytest.raises(TypeError):
            c.set("http_protocols", ["h1", "h2"])

    def test_mixed_valid_invalid(self):
        c = Config()
        with pytest.raises(ValueError):
            c.set("http_protocols", "h1,invalid,h2")


class TestHttp2MaxConcurrentStreams:
    """Test http2_max_concurrent_streams configuration setting."""

    def test_default_value(self):
        c = Config()
        assert c.http2_max_concurrent_streams == 100

    def test_set_custom_value(self):
        c = Config()
        c.set("http2_max_concurrent_streams", 50)
        assert c.http2_max_concurrent_streams == 50

    def test_set_from_string(self):
        c = Config()
        c.set("http2_max_concurrent_streams", "200")
        assert c.http2_max_concurrent_streams == 200

    def test_set_high_value(self):
        c = Config()
        c.set("http2_max_concurrent_streams", 1000)
        assert c.http2_max_concurrent_streams == 1000

    def test_negative_value_raises(self):
        c = Config()
        with pytest.raises(ValueError):
            c.set("http2_max_concurrent_streams", -1)

    def test_zero_value(self):
        # Zero is technically valid for positive int validator
        # It may have special meaning (use h2 default)
        c = Config()
        c.set("http2_max_concurrent_streams", 0)
        assert c.http2_max_concurrent_streams == 0


class TestHttp2InitialWindowSize:
    """Test http2_initial_window_size configuration setting."""

    def test_default_value(self):
        c = Config()
        # Default per RFC 7540 is 65535
        assert c.http2_initial_window_size == 65535

    def test_set_custom_value(self):
        c = Config()
        c.set("http2_initial_window_size", 131072)
        assert c.http2_initial_window_size == 131072

    def test_set_from_string(self):
        c = Config()
        c.set("http2_initial_window_size", "32768")
        assert c.http2_initial_window_size == 32768

    def test_negative_value_raises(self):
        c = Config()
        with pytest.raises(ValueError):
            c.set("http2_initial_window_size", -1)


class TestHttp2MaxFrameSize:
    """Test http2_max_frame_size configuration setting."""

    def test_default_value(self):
        c = Config()
        # Default per RFC 7540 is 16384
        assert c.http2_max_frame_size == 16384

    def test_set_custom_value(self):
        c = Config()
        c.set("http2_max_frame_size", 32768)
        assert c.http2_max_frame_size == 32768

    def test_set_from_string(self):
        c = Config()
        c.set("http2_max_frame_size", "65536")
        assert c.http2_max_frame_size == 65536

    def test_negative_value_raises(self):
        c = Config()
        with pytest.raises(ValueError):
            c.set("http2_max_frame_size", -1)


class TestHttp2MaxHeaderListSize:
    """Test http2_max_header_list_size configuration setting."""

    def test_default_value(self):
        c = Config()
        assert c.http2_max_header_list_size == 65536

    def test_set_custom_value(self):
        c = Config()
        c.set("http2_max_header_list_size", 131072)
        assert c.http2_max_header_list_size == 131072

    def test_set_from_string(self):
        c = Config()
        c.set("http2_max_header_list_size", "262144")
        assert c.http2_max_header_list_size == 262144

    def test_negative_value_raises(self):
        c = Config()
        with pytest.raises(ValueError):
            c.set("http2_max_header_list_size", -1)


class TestHttp2ConfigPropertyAccess:
    """Test property access for HTTP/2 settings."""

    def test_all_http2_settings_accessible(self):
        c = Config()
        # These should not raise
        _ = c.http_protocols
        _ = c.http2_max_concurrent_streams
        _ = c.http2_initial_window_size
        _ = c.http2_max_frame_size
        _ = c.http2_max_header_list_size


class TestHttp2ConfigDefaults:
    """Test that defaults match HTTP/2 specification values."""

    def test_window_size_matches_rfc(self):
        """RFC 7540 default is 2^16-1 (65535)."""
        c = Config()
        assert c.http2_initial_window_size == 65535

    def test_max_frame_size_matches_rfc_minimum(self):
        """RFC 7540 minimum is 2^14 (16384)."""
        c = Config()
        assert c.http2_max_frame_size == 16384

    def test_concurrent_streams_reasonable_default(self):
        """Default should be reasonable for production use."""
        c = Config()
        assert 1 <= c.http2_max_concurrent_streams <= 1000


class TestValidateHttpProtocols:
    """Test the validate_http_protocols function directly."""

    def test_validate_none(self):
        result = config.validate_http_protocols(None)
        assert result == ["h1"]

    def test_validate_empty_string(self):
        result = config.validate_http_protocols("")
        assert result == ["h1"]

    def test_validate_whitespace_only(self):
        result = config.validate_http_protocols("   ")
        assert result == ["h1"]

    def test_validate_single_protocol(self):
        result = config.validate_http_protocols("h2")
        assert result == ["h2"]

    def test_validate_multiple_protocols(self):
        result = config.validate_http_protocols("h2,h1")
        assert result == ["h2", "h1"]

    def test_validate_with_spaces(self):
        result = config.validate_http_protocols("h2 , h1")
        assert result == ["h2", "h1"]

    def test_validate_uppercase(self):
        result = config.validate_http_protocols("H2,H1")
        assert result == ["h1", "h2"] or result == ["h2", "h1"]

    def test_validate_invalid_raises(self):
        with pytest.raises(ValueError):
            config.validate_http_protocols("http2")

    def test_validate_type_error(self):
        with pytest.raises(TypeError):
            config.validate_http_protocols(42)
