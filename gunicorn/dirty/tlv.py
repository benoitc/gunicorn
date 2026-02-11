#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
TLV (Type-Length-Value) Binary Encoder/Decoder

Provides efficient binary serialization for dirty worker protocol messages.
Inspired by OpenBSD msgctl/msgsnd message format.

Type Codes:
    0x00: None (no value bytes)
    0x01: bool (1 byte: 0x00 or 0x01)
    0x05: int64 (8 bytes big-endian signed)
    0x06: float64 (8 bytes IEEE 754)
    0x10: bytes (4-byte length + raw bytes)
    0x11: string (4-byte length + UTF-8 encoded)
    0x20: list (4-byte count + encoded elements)
    0x21: dict (4-byte count + encoded key-value pairs)
"""

import struct

from .errors import DirtyProtocolError


# Type codes
TYPE_NONE = 0x00
TYPE_BOOL = 0x01
TYPE_INT64 = 0x05
TYPE_FLOAT64 = 0x06
TYPE_BYTES = 0x10
TYPE_STRING = 0x11
TYPE_LIST = 0x20
TYPE_DICT = 0x21

# Maximum sizes for safety
MAX_STRING_SIZE = 64 * 1024 * 1024  # 64 MB
MAX_BYTES_SIZE = 64 * 1024 * 1024   # 64 MB
MAX_LIST_SIZE = 1024 * 1024         # 1 million items
MAX_DICT_SIZE = 1024 * 1024         # 1 million items


class TLVEncoder:
    """
    TLV binary encoder/decoder.

    Encodes Python values to binary TLV format and decodes back.
    Supports: None, bool, int, float, bytes, str, list, dict.
    """

    @staticmethod
    def encode(value) -> bytes:  # pylint: disable=too-many-return-statements
        """
        Encode a Python value to TLV binary format.

        Args:
            value: Python value to encode (None, bool, int, float,
                   bytes, str, list, or dict)

        Returns:
            bytes: TLV-encoded binary data

        Raises:
            DirtyProtocolError: If value type is not supported
        """
        if value is None:
            return bytes([TYPE_NONE])

        if isinstance(value, bool):
            # bool must come before int since bool is a subclass of int
            return bytes([TYPE_BOOL, 0x01 if value else 0x00])

        if isinstance(value, int):
            return bytes([TYPE_INT64]) + struct.pack(">q", value)

        if isinstance(value, float):
            return bytes([TYPE_FLOAT64]) + struct.pack(">d", value)

        if isinstance(value, bytes):
            if len(value) > MAX_BYTES_SIZE:
                raise DirtyProtocolError(
                    f"Bytes too large: {len(value)} bytes "
                    f"(max: {MAX_BYTES_SIZE})"
                )
            return bytes([TYPE_BYTES]) + struct.pack(">I", len(value)) + value

        if isinstance(value, str):
            encoded = value.encode("utf-8")
            if len(encoded) > MAX_STRING_SIZE:
                raise DirtyProtocolError(
                    f"String too large: {len(encoded)} bytes "
                    f"(max: {MAX_STRING_SIZE})"
                )
            return bytes([TYPE_STRING]) + struct.pack(">I", len(encoded)) + encoded

        if isinstance(value, (list, tuple)):
            if len(value) > MAX_LIST_SIZE:
                raise DirtyProtocolError(
                    f"List too large: {len(value)} items "
                    f"(max: {MAX_LIST_SIZE})"
                )
            parts = [bytes([TYPE_LIST]), struct.pack(">I", len(value))]
            for item in value:
                parts.append(TLVEncoder.encode(item))
            return b"".join(parts)

        if isinstance(value, dict):
            if len(value) > MAX_DICT_SIZE:
                raise DirtyProtocolError(
                    f"Dict too large: {len(value)} items "
                    f"(max: {MAX_DICT_SIZE})"
                )
            parts = [bytes([TYPE_DICT]), struct.pack(">I", len(value))]
            for k, v in value.items():
                # Convert keys to strings (like JSON)
                if not isinstance(k, str):
                    k = str(k)
                parts.append(TLVEncoder.encode(k))
                parts.append(TLVEncoder.encode(v))
            return b"".join(parts)

        raise DirtyProtocolError(
            f"Unsupported type for TLV encoding: {type(value).__name__}"
        )

    @staticmethod
    def decode(data: bytes, offset: int = 0) -> tuple:  # pylint: disable=too-many-return-statements
        """
        Decode a TLV-encoded value from binary data.

        Args:
            data: Binary data to decode
            offset: Starting offset in the data

        Returns:
            tuple: (decoded_value, new_offset)

        Raises:
            DirtyProtocolError: If data is malformed or truncated
        """
        if offset >= len(data):
            raise DirtyProtocolError(
                "Truncated TLV data: no type byte",
                raw_data=data[offset:offset + 20]
            )

        type_code = data[offset]
        offset += 1

        if type_code == TYPE_NONE:
            return None, offset

        if type_code == TYPE_BOOL:
            if offset >= len(data):
                raise DirtyProtocolError(
                    "Truncated TLV data: missing bool value",
                    raw_data=data[offset - 1:offset + 20]
                )
            value = data[offset] != 0x00
            return value, offset + 1

        if type_code == TYPE_INT64:
            if offset + 8 > len(data):
                raise DirtyProtocolError(
                    "Truncated TLV data: incomplete int64",
                    raw_data=data[offset - 1:offset + 20]
                )
            value = struct.unpack(">q", data[offset:offset + 8])[0]
            return value, offset + 8

        if type_code == TYPE_FLOAT64:
            if offset + 8 > len(data):
                raise DirtyProtocolError(
                    "Truncated TLV data: incomplete float64",
                    raw_data=data[offset - 1:offset + 20]
                )
            value = struct.unpack(">d", data[offset:offset + 8])[0]
            return value, offset + 8

        if type_code == TYPE_BYTES:
            if offset + 4 > len(data):
                raise DirtyProtocolError(
                    "Truncated TLV data: incomplete bytes length",
                    raw_data=data[offset - 1:offset + 20]
                )
            length = struct.unpack(">I", data[offset:offset + 4])[0]
            offset += 4

            if length > MAX_BYTES_SIZE:
                raise DirtyProtocolError(
                    f"Bytes too large: {length} bytes (max: {MAX_BYTES_SIZE})"
                )

            if offset + length > len(data):
                raise DirtyProtocolError(
                    f"Truncated TLV data: expected {length} bytes, "
                    f"got {len(data) - offset}",
                    raw_data=data[offset - 5:offset + 20]
                )
            value = data[offset:offset + length]
            return value, offset + length

        if type_code == TYPE_STRING:
            if offset + 4 > len(data):
                raise DirtyProtocolError(
                    "Truncated TLV data: incomplete string length",
                    raw_data=data[offset - 1:offset + 20]
                )
            length = struct.unpack(">I", data[offset:offset + 4])[0]
            offset += 4

            if length > MAX_STRING_SIZE:
                raise DirtyProtocolError(
                    f"String too large: {length} bytes (max: {MAX_STRING_SIZE})"
                )

            if offset + length > len(data):
                raise DirtyProtocolError(
                    f"Truncated TLV data: expected {length} bytes for string, "
                    f"got {len(data) - offset}",
                    raw_data=data[offset - 5:offset + 20]
                )
            try:
                value = data[offset:offset + length].decode("utf-8")
            except UnicodeDecodeError as e:
                raise DirtyProtocolError(
                    f"Invalid UTF-8 in string: {e}",
                    raw_data=data[offset:offset + min(length, 20)]
                )
            return value, offset + length

        if type_code == TYPE_LIST:
            if offset + 4 > len(data):
                raise DirtyProtocolError(
                    "Truncated TLV data: incomplete list count",
                    raw_data=data[offset - 1:offset + 20]
                )
            count = struct.unpack(">I", data[offset:offset + 4])[0]
            offset += 4

            if count > MAX_LIST_SIZE:
                raise DirtyProtocolError(
                    f"List too large: {count} items (max: {MAX_LIST_SIZE})"
                )

            items = []
            for _ in range(count):
                item, offset = TLVEncoder.decode(data, offset)
                items.append(item)
            return items, offset

        if type_code == TYPE_DICT:
            if offset + 4 > len(data):
                raise DirtyProtocolError(
                    "Truncated TLV data: incomplete dict count",
                    raw_data=data[offset - 1:offset + 20]
                )
            count = struct.unpack(">I", data[offset:offset + 4])[0]
            offset += 4

            if count > MAX_DICT_SIZE:
                raise DirtyProtocolError(
                    f"Dict too large: {count} items (max: {MAX_DICT_SIZE})"
                )

            result = {}
            for _ in range(count):
                key, offset = TLVEncoder.decode(data, offset)
                if not isinstance(key, str):
                    raise DirtyProtocolError(
                        f"Dict key must be string, got {type(key).__name__}"
                    )
                value, offset = TLVEncoder.decode(data, offset)
                result[key] = value
            return result, offset

        raise DirtyProtocolError(
            f"Unknown TLV type code: 0x{type_code:02x}",
            raw_data=data[offset - 1:offset + 20]
        )

    @staticmethod
    def decode_full(data: bytes):
        """
        Decode a complete TLV-encoded value, ensuring all data is consumed.

        Args:
            data: Binary data to decode

        Returns:
            Decoded Python value

        Raises:
            DirtyProtocolError: If data is malformed or has trailing bytes
        """
        value, offset = TLVEncoder.decode(data, 0)
        if offset != len(data):
            raise DirtyProtocolError(
                f"Trailing data after TLV: {len(data) - offset} bytes",
                raw_data=data[offset:offset + 20]
            )
        return value
