#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""Tests for dirty stash (shared state) functionality."""

import pytest

from gunicorn.dirty.stash import (
    StashClient,
    StashTable,
    StashError,
    StashTableNotFoundError,
    StashKeyNotFoundError,
)
from gunicorn.dirty.protocol import (
    BinaryProtocol,
    DirtyProtocol,
    MSG_TYPE_STASH,
    STASH_OP_PUT,
    STASH_OP_GET,
    STASH_OP_DELETE,
    STASH_OP_KEYS,
    STASH_OP_CLEAR,
    STASH_OP_INFO,
    STASH_OP_ENSURE,
    STASH_OP_DELETE_TABLE,
    STASH_OP_TABLES,
    STASH_OP_EXISTS,
    make_stash_message,
)


class TestStashProtocol:
    """Test stash protocol encoding."""

    def test_make_stash_message_basic(self):
        """Test basic stash message creation."""
        msg = make_stash_message(123, STASH_OP_PUT, "test_table")
        assert msg["type"] == "stash"
        assert msg["id"] == 123
        assert msg["op"] == STASH_OP_PUT
        assert msg["table"] == "test_table"

    def test_make_stash_message_with_key_value(self):
        """Test stash message with key and value."""
        msg = make_stash_message(
            456, STASH_OP_PUT, "sessions",
            key="user:1", value={"name": "Alice"}
        )
        assert msg["key"] == "user:1"
        assert msg["value"] == {"name": "Alice"}

    def test_make_stash_message_with_pattern(self):
        """Test stash message with pattern."""
        msg = make_stash_message(
            789, STASH_OP_KEYS, "sessions",
            pattern="user:*"
        )
        assert msg["pattern"] == "user:*"

    def test_encode_stash_message(self):
        """Test binary encoding of stash message."""
        msg = make_stash_message(
            123, STASH_OP_PUT, "test",
            key="k", value="v"
        )
        encoded = BinaryProtocol._encode_from_dict(msg)
        assert isinstance(encoded, bytes)
        assert len(encoded) > 16  # Header + payload

    def test_stash_message_roundtrip(self):
        """Test encode/decode roundtrip for stash message."""
        original = make_stash_message(
            12345, STASH_OP_GET, "cache",
            key="my_key"
        )
        encoded = BinaryProtocol._encode_from_dict(original)
        msg_type, request_id, payload = BinaryProtocol.decode_message(encoded)

        assert msg_type == "stash"
        assert payload["op"] == STASH_OP_GET
        assert payload["table"] == "cache"
        assert payload["key"] == "my_key"

    def test_stash_operations_have_unique_codes(self):
        """Test that all stash operations have unique codes."""
        ops = [
            STASH_OP_PUT,
            STASH_OP_GET,
            STASH_OP_DELETE,
            STASH_OP_KEYS,
            STASH_OP_CLEAR,
            STASH_OP_INFO,
            STASH_OP_ENSURE,
            STASH_OP_DELETE_TABLE,
            STASH_OP_TABLES,
            STASH_OP_EXISTS,
        ]
        assert len(ops) == len(set(ops))


class TestStashTable:
    """Test StashTable dict-like interface."""

    def test_stash_table_name(self):
        """Test StashTable name property."""
        # Create a mock client
        class MockClient:
            pass

        table = StashTable(MockClient(), "test_table")
        assert table.name == "test_table"


class TestStashErrors:
    """Test stash error classes."""

    def test_stash_error_base(self):
        """Test base StashError."""
        error = StashError("test error")
        assert str(error) == "test error"
        assert isinstance(error, Exception)

    def test_stash_table_not_found_error(self):
        """Test StashTableNotFoundError."""
        error = StashTableNotFoundError("my_table")
        assert error.table_name == "my_table"
        assert "my_table" in str(error)

    def test_stash_key_not_found_error(self):
        """Test StashKeyNotFoundError."""
        error = StashKeyNotFoundError("my_table", "my_key")
        assert error.table_name == "my_table"
        assert error.key == "my_key"
        assert "my_key" in str(error)


class TestStashProtocolConstants:
    """Test protocol constants for stash."""

    def test_msg_type_stash_exists(self):
        """Test MSG_TYPE_STASH constant exists."""
        assert MSG_TYPE_STASH == 0x10

    def test_dirty_protocol_exports_stash_type(self):
        """Test DirtyProtocol exports stash type."""
        assert DirtyProtocol.MSG_TYPE_STASH == "stash"

    def test_stash_op_codes(self):
        """Test stash operation codes are integers."""
        assert isinstance(STASH_OP_PUT, int)
        assert isinstance(STASH_OP_GET, int)
        assert isinstance(STASH_OP_DELETE, int)
        assert isinstance(STASH_OP_KEYS, int)
        assert isinstance(STASH_OP_CLEAR, int)
        assert isinstance(STASH_OP_INFO, int)
        assert isinstance(STASH_OP_ENSURE, int)
        assert isinstance(STASH_OP_DELETE_TABLE, int)
        assert isinstance(STASH_OP_TABLES, int)
        assert isinstance(STASH_OP_EXISTS, int)


class TestStashEncodingEdgeCases:
    """Test edge cases in stash encoding."""

    def test_encode_empty_table_name(self):
        """Test encoding with empty table name."""
        msg = make_stash_message(1, STASH_OP_TABLES, "")
        encoded = BinaryProtocol._encode_from_dict(msg)
        assert isinstance(encoded, bytes)

    def test_encode_unicode_table_name(self):
        """Test encoding with unicode table name."""
        msg = make_stash_message(1, STASH_OP_PUT, "テスト", key="k", value="v")
        encoded = BinaryProtocol._encode_from_dict(msg)
        _, _, payload = BinaryProtocol.decode_message(encoded)
        assert payload["table"] == "テスト"

    def test_encode_complex_value(self):
        """Test encoding with complex nested value."""
        value = {
            "name": "test",
            "count": 42,
            "nested": {"a": [1, 2, 3]},
            "data": b"binary data",
        }
        msg = make_stash_message(1, STASH_OP_PUT, "test", key="k", value=value)
        encoded = BinaryProtocol._encode_from_dict(msg)
        _, _, payload = BinaryProtocol.decode_message(encoded)
        assert payload["value"] == value

    def test_encode_none_key(self):
        """Test encoding with None key (for table-level ops)."""
        msg = make_stash_message(1, STASH_OP_TABLES, "")
        assert "key" not in msg

    def test_encode_special_characters_in_pattern(self):
        """Test encoding with special characters in pattern."""
        msg = make_stash_message(
            1, STASH_OP_KEYS, "test",
            pattern="user:*:session:?"
        )
        encoded = BinaryProtocol._encode_from_dict(msg)
        _, _, payload = BinaryProtocol.decode_message(encoded)
        assert payload["pattern"] == "user:*:session:?"
