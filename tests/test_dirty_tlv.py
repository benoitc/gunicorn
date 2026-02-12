#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for dirty TLV binary encoder/decoder."""

import math
import struct
import pytest

from gunicorn.dirty.tlv import (
    TLVEncoder,
    TYPE_NONE,
    TYPE_BOOL,
    TYPE_INT64,
    TYPE_FLOAT64,
    TYPE_BYTES,
    TYPE_STRING,
    TYPE_LIST,
    TYPE_DICT,
    MAX_STRING_SIZE,
    MAX_BYTES_SIZE,
    MAX_LIST_SIZE,
    MAX_DICT_SIZE,
)
from gunicorn.dirty.errors import DirtyProtocolError


class TestTLVEncoderBasicTypes:
    """Tests for basic type encoding/decoding."""

    def test_encode_decode_none(self):
        """Test None encoding/decoding."""
        encoded = TLVEncoder.encode(None)
        assert encoded == bytes([TYPE_NONE])

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value is None
        assert offset == 1

    def test_encode_decode_true(self):
        """Test True encoding/decoding."""
        encoded = TLVEncoder.encode(True)
        assert encoded == bytes([TYPE_BOOL, 0x01])

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value is True
        assert offset == 2

    def test_encode_decode_false(self):
        """Test False encoding/decoding."""
        encoded = TLVEncoder.encode(False)
        assert encoded == bytes([TYPE_BOOL, 0x00])

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value is False
        assert offset == 2

    def test_encode_decode_positive_int(self):
        """Test positive integer encoding/decoding."""
        encoded = TLVEncoder.encode(42)
        assert encoded[0] == TYPE_INT64
        assert len(encoded) == 9  # 1 type + 8 value

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == 42
        assert offset == 9

    def test_encode_decode_negative_int(self):
        """Test negative integer encoding/decoding."""
        encoded = TLVEncoder.encode(-12345)

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == -12345

    def test_encode_decode_large_int(self):
        """Test large integer encoding/decoding."""
        large_val = 2**62
        encoded = TLVEncoder.encode(large_val)

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == large_val

    def test_encode_decode_zero(self):
        """Test zero encoding/decoding."""
        encoded = TLVEncoder.encode(0)

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == 0

    def test_encode_decode_float(self):
        """Test float encoding/decoding."""
        encoded = TLVEncoder.encode(3.14159)
        assert encoded[0] == TYPE_FLOAT64
        assert len(encoded) == 9  # 1 type + 8 value

        value, offset = TLVEncoder.decode(encoded, 0)
        assert abs(value - 3.14159) < 1e-10

    def test_encode_decode_negative_float(self):
        """Test negative float encoding/decoding."""
        encoded = TLVEncoder.encode(-273.15)

        value, offset = TLVEncoder.decode(encoded, 0)
        assert abs(value - (-273.15)) < 1e-10

    def test_encode_decode_float_infinity(self):
        """Test infinity encoding/decoding."""
        encoded = TLVEncoder.encode(float('inf'))

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == float('inf')

    def test_encode_decode_float_nan(self):
        """Test NaN encoding/decoding."""
        encoded = TLVEncoder.encode(float('nan'))

        value, offset = TLVEncoder.decode(encoded, 0)
        assert math.isnan(value)


class TestTLVEncoderBytes:
    """Tests for bytes encoding/decoding."""

    def test_encode_decode_empty_bytes(self):
        """Test empty bytes encoding/decoding."""
        encoded = TLVEncoder.encode(b"")
        assert encoded[0] == TYPE_BYTES

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == b""

    def test_encode_decode_bytes(self):
        """Test bytes encoding/decoding."""
        data = b"\x00\x01\x02\xff\xfe\xfd"
        encoded = TLVEncoder.encode(data)

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == data

    def test_encode_decode_large_bytes(self):
        """Test large bytes encoding/decoding."""
        data = b"x" * 10000
        encoded = TLVEncoder.encode(data)

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == data

    def test_bytes_too_large(self):
        """Test that bytes exceeding max size raises error."""
        # We won't actually allocate MAX_BYTES_SIZE, just check the encoding
        with pytest.raises(DirtyProtocolError) as exc_info:
            TLVEncoder.encode(b"x" * (MAX_BYTES_SIZE + 1))
        assert "too large" in str(exc_info.value).lower()


class TestTLVEncoderString:
    """Tests for string encoding/decoding."""

    def test_encode_decode_empty_string(self):
        """Test empty string encoding/decoding."""
        encoded = TLVEncoder.encode("")
        assert encoded[0] == TYPE_STRING

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == ""

    def test_encode_decode_ascii_string(self):
        """Test ASCII string encoding/decoding."""
        encoded = TLVEncoder.encode("hello world")

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == "hello world"

    def test_encode_decode_unicode_string(self):
        """Test Unicode string encoding/decoding."""
        text = "Hello, world! \u00a9 \u2603 \U0001F600"
        encoded = TLVEncoder.encode(text)

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == text

    def test_encode_decode_chinese(self):
        """Test Chinese characters encoding/decoding."""
        text = "Hello, world!"
        encoded = TLVEncoder.encode(text)

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == text

    def test_encode_decode_emoji(self):
        """Test emoji encoding/decoding."""
        text = "Test emoji"
        encoded = TLVEncoder.encode(text)

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == text

    def test_encode_decode_large_string(self):
        """Test large string encoding/decoding."""
        text = "x" * 10000
        encoded = TLVEncoder.encode(text)

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == text


class TestTLVEncoderList:
    """Tests for list encoding/decoding."""

    def test_encode_decode_empty_list(self):
        """Test empty list encoding/decoding."""
        encoded = TLVEncoder.encode([])
        assert encoded[0] == TYPE_LIST

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == []

    def test_encode_decode_simple_list(self):
        """Test simple list encoding/decoding."""
        data = [1, 2, 3]
        encoded = TLVEncoder.encode(data)

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == data

    def test_encode_decode_mixed_list(self):
        """Test mixed type list encoding/decoding."""
        data = [1, "hello", 3.14, True, None, b"bytes"]
        encoded = TLVEncoder.encode(data)

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == data

    def test_encode_decode_nested_list(self):
        """Test nested list encoding/decoding."""
        data = [[1, 2], [3, [4, 5]], ["a", "b"]]
        encoded = TLVEncoder.encode(data)

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == data

    def test_encode_decode_tuple_as_list(self):
        """Test that tuples are encoded as lists."""
        data = (1, 2, 3)
        encoded = TLVEncoder.encode(data)

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == [1, 2, 3]  # Decoded as list

    def test_encode_decode_large_list(self):
        """Test large list encoding/decoding."""
        data = list(range(1000))
        encoded = TLVEncoder.encode(data)

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == data


class TestTLVEncoderDict:
    """Tests for dict encoding/decoding."""

    def test_encode_decode_empty_dict(self):
        """Test empty dict encoding/decoding."""
        encoded = TLVEncoder.encode({})
        assert encoded[0] == TYPE_DICT

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == {}

    def test_encode_decode_simple_dict(self):
        """Test simple dict encoding/decoding."""
        data = {"a": 1, "b": 2, "c": 3}
        encoded = TLVEncoder.encode(data)

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == data

    def test_encode_decode_mixed_values_dict(self):
        """Test dict with mixed value types."""
        data = {
            "int": 42,
            "float": 3.14,
            "string": "hello",
            "bool": True,
            "none": None,
            "bytes": b"data",
            "list": [1, 2, 3],
        }
        encoded = TLVEncoder.encode(data)

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == data

    def test_encode_decode_nested_dict(self):
        """Test nested dict encoding/decoding."""
        data = {
            "outer": {
                "inner": {
                    "value": 42
                },
                "list": [{"a": 1}, {"b": 2}]
            }
        }
        encoded = TLVEncoder.encode(data)

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == data

    def test_encode_dict_non_string_key_converted(self):
        """Test that non-string keys are converted to strings (like JSON)."""
        data = {1: "value", 2: "other"}
        encoded = TLVEncoder.encode(data)
        decoded, _ = TLVEncoder.decode(encoded, 0)
        # Keys should be converted to strings
        assert decoded == {"1": "value", "2": "other"}


class TestTLVEncoderComplexStructures:
    """Tests for complex nested structures."""

    def test_encode_decode_request_like(self):
        """Test encoding/decoding a request-like structure."""
        data = {
            "id": 12345,
            "app_path": "myapp.ml:MLApp",
            "action": "predict",
            "args": [b"input_data", 0.7],
            "kwargs": {"temperature": 0.7, "max_tokens": 1000},
        }
        encoded = TLVEncoder.encode(data)

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == data

    def test_encode_decode_response_like(self):
        """Test encoding/decoding a response-like structure."""
        data = {
            "id": 12345,
            "result": {
                "predictions": [0.1, 0.2, 0.7],
                "metadata": {"model": "v1.0", "latency_ms": 42},
            }
        }
        encoded = TLVEncoder.encode(data)

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == data

    def test_encode_decode_deeply_nested(self):
        """Test deeply nested structures."""
        data = {"a": {"b": {"c": {"d": {"e": {"f": "deep"}}}}}}
        encoded = TLVEncoder.encode(data)

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == data


class TestTLVEncoderRoundtrip:
    """Tests for complete roundtrip using decode_full."""

    def test_decode_full_simple(self):
        """Test decode_full with simple value."""
        data = {"key": "value"}
        encoded = TLVEncoder.encode(data)

        value = TLVEncoder.decode_full(encoded)
        assert value == data

    def test_decode_full_trailing_data(self):
        """Test decode_full raises on trailing data."""
        encoded = TLVEncoder.encode(42) + b"extra"

        with pytest.raises(DirtyProtocolError) as exc_info:
            TLVEncoder.decode_full(encoded)
        assert "trailing" in str(exc_info.value).lower()


class TestTLVEncoderErrors:
    """Tests for error handling."""

    def test_decode_empty_data(self):
        """Test decoding empty data raises error."""
        with pytest.raises(DirtyProtocolError) as exc_info:
            TLVEncoder.decode(b"", 0)
        assert "truncated" in str(exc_info.value).lower()

    def test_decode_truncated_int(self):
        """Test decoding truncated int raises error."""
        # TYPE_INT64 followed by only 4 bytes instead of 8
        data = bytes([TYPE_INT64, 0, 0, 0, 0])
        with pytest.raises(DirtyProtocolError) as exc_info:
            TLVEncoder.decode(data, 0)
        assert "truncated" in str(exc_info.value).lower()

    def test_decode_truncated_float(self):
        """Test decoding truncated float raises error."""
        data = bytes([TYPE_FLOAT64, 0, 0, 0, 0])
        with pytest.raises(DirtyProtocolError) as exc_info:
            TLVEncoder.decode(data, 0)
        assert "truncated" in str(exc_info.value).lower()

    def test_decode_truncated_bytes_length(self):
        """Test decoding truncated bytes length raises error."""
        data = bytes([TYPE_BYTES, 0, 0])  # Only 2 bytes of length
        with pytest.raises(DirtyProtocolError) as exc_info:
            TLVEncoder.decode(data, 0)
        assert "truncated" in str(exc_info.value).lower()

    def test_decode_truncated_bytes_data(self):
        """Test decoding truncated bytes data raises error."""
        # Says 10 bytes but only provides 5
        data = bytes([TYPE_BYTES]) + struct.pack(">I", 10) + b"12345"
        with pytest.raises(DirtyProtocolError) as exc_info:
            TLVEncoder.decode(data, 0)
        assert "truncated" in str(exc_info.value).lower()

    def test_decode_truncated_string_length(self):
        """Test decoding truncated string length raises error."""
        data = bytes([TYPE_STRING, 0])
        with pytest.raises(DirtyProtocolError) as exc_info:
            TLVEncoder.decode(data, 0)
        assert "truncated" in str(exc_info.value).lower()

    def test_decode_truncated_string_data(self):
        """Test decoding truncated string data raises error."""
        data = bytes([TYPE_STRING]) + struct.pack(">I", 10) + b"hello"
        with pytest.raises(DirtyProtocolError) as exc_info:
            TLVEncoder.decode(data, 0)
        assert "truncated" in str(exc_info.value).lower()

    def test_decode_invalid_utf8(self):
        """Test decoding invalid UTF-8 raises error."""
        # Valid length, but invalid UTF-8 bytes
        data = bytes([TYPE_STRING]) + struct.pack(">I", 3) + b"\x80\x81\x82"
        with pytest.raises(DirtyProtocolError) as exc_info:
            TLVEncoder.decode(data, 0)
        assert "utf-8" in str(exc_info.value).lower()

    def test_decode_truncated_list_count(self):
        """Test decoding truncated list count raises error."""
        data = bytes([TYPE_LIST, 0])
        with pytest.raises(DirtyProtocolError) as exc_info:
            TLVEncoder.decode(data, 0)
        assert "truncated" in str(exc_info.value).lower()

    def test_decode_truncated_dict_count(self):
        """Test decoding truncated dict count raises error."""
        data = bytes([TYPE_DICT, 0])
        with pytest.raises(DirtyProtocolError) as exc_info:
            TLVEncoder.decode(data, 0)
        assert "truncated" in str(exc_info.value).lower()

    def test_decode_unknown_type(self):
        """Test decoding unknown type raises error."""
        data = bytes([0xFF])  # Unknown type
        with pytest.raises(DirtyProtocolError) as exc_info:
            TLVEncoder.decode(data, 0)
        assert "unknown" in str(exc_info.value).lower()

    def test_encode_unsupported_type(self):
        """Test encoding unsupported type raises error."""
        with pytest.raises(DirtyProtocolError) as exc_info:
            TLVEncoder.encode(object())
        assert "unsupported type" in str(exc_info.value).lower()

    def test_encode_function_raises_error(self):
        """Test encoding a function raises error."""
        with pytest.raises(DirtyProtocolError) as exc_info:
            TLVEncoder.encode(lambda x: x)
        assert "unsupported type" in str(exc_info.value).lower()

    def test_decode_dict_non_string_key_in_data(self):
        """Test decoding dict with non-string key raises error."""
        # Manually construct a dict with int key
        # TYPE_DICT, count=1, TYPE_INT64 key, TYPE_INT64 value
        data = (
            bytes([TYPE_DICT])
            + struct.pack(">I", 1)
            + bytes([TYPE_INT64])
            + struct.pack(">q", 1)  # Key (int, not string)
            + bytes([TYPE_INT64])
            + struct.pack(">q", 2)  # Value
        )
        with pytest.raises(DirtyProtocolError) as exc_info:
            TLVEncoder.decode(data, 0)
        assert "string" in str(exc_info.value).lower()


class TestTLVEncoderOffset:
    """Tests for offset handling."""

    def test_decode_with_offset(self):
        """Test decoding from specific offset."""
        # Create data with prefix
        prefix = b"garbage"
        encoded = TLVEncoder.encode(42)
        data = prefix + encoded

        value, offset = TLVEncoder.decode(data, len(prefix))
        assert value == 42
        assert offset == len(prefix) + len(encoded)

    def test_decode_multiple_values(self):
        """Test decoding multiple consecutive values."""
        v1 = TLVEncoder.encode("hello")
        v2 = TLVEncoder.encode(42)
        v3 = TLVEncoder.encode([1, 2, 3])
        data = v1 + v2 + v3

        offset = 0
        val1, offset = TLVEncoder.decode(data, offset)
        assert val1 == "hello"

        val2, offset = TLVEncoder.decode(data, offset)
        assert val2 == 42

        val3, offset = TLVEncoder.decode(data, offset)
        assert val3 == [1, 2, 3]

        assert offset == len(data)


class TestTLVEncoderBinaryData:
    """Tests for binary data handling (the main motivation for this protocol)."""

    def test_binary_data_no_encoding(self):
        """Test that binary data is passed through without encoding."""
        # This is the key advantage over JSON - binary data doesn't need base64
        binary_data = bytes(range(256))  # All byte values
        encoded = TLVEncoder.encode(binary_data)

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == binary_data

    def test_binary_with_null_bytes(self):
        """Test binary data with embedded null bytes."""
        binary_data = b"\x00\x00\xff\x00\x00"
        encoded = TLVEncoder.encode(binary_data)

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == binary_data

    def test_binary_in_nested_structure(self):
        """Test binary data inside nested structures."""
        data = {
            "image": b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
            "metadata": {"width": 640, "height": 480},
            "chunks": [b"chunk1", b"chunk2", b"chunk3"],
        }
        encoded = TLVEncoder.encode(data)

        value, offset = TLVEncoder.decode(encoded, 0)
        assert value == data
