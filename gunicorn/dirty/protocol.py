#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Dirty Worker Binary Protocol

Binary message framing over Unix sockets, inspired by OpenBSD msgctl/msgsnd.
Replaces JSON protocol for efficient binary data transfer.

Header Format (16 bytes):
+--------+--------+--------+--------+--------+--------+--------+--------+
|  Magic (2B)     | Ver(1) | MType  |        Payload Length (4B)        |
+--------+--------+--------+--------+--------+--------+--------+--------+
|                       Request ID (8 bytes)                            |
+--------+--------+--------+--------+--------+--------+--------+--------+

- Magic: 0x47 0x44 ("GD" for Gunicorn Dirty)
- Version: 0x01
- MType: Message type (REQUEST, RESPONSE, ERROR, CHUNK, END)
- Length: Payload size (big-endian uint32, max 64MB)
- Request ID: uint64 (replaces UUID string)

Payload is TLV-encoded (see tlv.py).
"""

import asyncio
import socket
import struct

from .errors import DirtyProtocolError
from .tlv import TLVEncoder


# Protocol constants
MAGIC = b"GD"  # 0x47 0x44
VERSION = 0x01

# Message types (1 byte)
MSG_TYPE_REQUEST = 0x01
MSG_TYPE_RESPONSE = 0x02
MSG_TYPE_ERROR = 0x03
MSG_TYPE_CHUNK = 0x04
MSG_TYPE_END = 0x05
MSG_TYPE_STASH = 0x10  # Stash operations (shared state between workers)
MSG_TYPE_STATUS = 0x11  # Status query for arbiter/workers
MSG_TYPE_MANAGE = 0x12  # Worker management (add/remove workers)

# Message type names (for backwards compatibility with old API)
MSG_TYPE_REQUEST_STR = "request"
MSG_TYPE_RESPONSE_STR = "response"
MSG_TYPE_ERROR_STR = "error"
MSG_TYPE_CHUNK_STR = "chunk"
MSG_TYPE_END_STR = "end"
MSG_TYPE_STASH_STR = "stash"
MSG_TYPE_STATUS_STR = "status"
MSG_TYPE_MANAGE_STR = "manage"

# Map int types to string names
MSG_TYPE_TO_STR = {
    MSG_TYPE_REQUEST: MSG_TYPE_REQUEST_STR,
    MSG_TYPE_RESPONSE: MSG_TYPE_RESPONSE_STR,
    MSG_TYPE_ERROR: MSG_TYPE_ERROR_STR,
    MSG_TYPE_CHUNK: MSG_TYPE_CHUNK_STR,
    MSG_TYPE_END: MSG_TYPE_END_STR,
    MSG_TYPE_STASH: MSG_TYPE_STASH_STR,
    MSG_TYPE_STATUS: MSG_TYPE_STATUS_STR,
    MSG_TYPE_MANAGE: MSG_TYPE_MANAGE_STR,
}

# Map string names to int types
MSG_TYPE_FROM_STR = {v: k for k, v in MSG_TYPE_TO_STR.items()}

# Stash operation codes
STASH_OP_PUT = 1
STASH_OP_GET = 2
STASH_OP_DELETE = 3
STASH_OP_KEYS = 4
STASH_OP_CLEAR = 5
STASH_OP_INFO = 6
STASH_OP_ENSURE = 7
STASH_OP_DELETE_TABLE = 8
STASH_OP_TABLES = 9
STASH_OP_EXISTS = 10

# Manage operation codes
MANAGE_OP_ADD = 1      # Add/spawn workers
MANAGE_OP_REMOVE = 2   # Remove/kill workers

# Header format: Magic (2) + Version (1) + Type (1) + Length (4) + RequestID (8) = 16
HEADER_FORMAT = ">2sBBIQ"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

# Maximum message size (64 MB)
MAX_MESSAGE_SIZE = 64 * 1024 * 1024


class BinaryProtocol:
    """Binary message protocol for dirty worker IPC."""

    # Export constants for external use
    HEADER_SIZE = HEADER_SIZE
    MAX_MESSAGE_SIZE = MAX_MESSAGE_SIZE

    MSG_TYPE_REQUEST = MSG_TYPE_REQUEST_STR
    MSG_TYPE_RESPONSE = MSG_TYPE_RESPONSE_STR
    MSG_TYPE_ERROR = MSG_TYPE_ERROR_STR
    MSG_TYPE_CHUNK = MSG_TYPE_CHUNK_STR
    MSG_TYPE_END = MSG_TYPE_END_STR
    MSG_TYPE_STASH = MSG_TYPE_STASH_STR
    MSG_TYPE_STATUS = MSG_TYPE_STATUS_STR
    MSG_TYPE_MANAGE = MSG_TYPE_MANAGE_STR

    @staticmethod
    def encode_header(msg_type: int, request_id: int, payload_length: int) -> bytes:
        """
        Encode the 16-byte message header.

        Args:
            msg_type: Message type (MSG_TYPE_REQUEST, etc.)
            request_id: Unique request identifier (uint64)
            payload_length: Length of the TLV-encoded payload

        Returns:
            bytes: 16-byte header
        """
        return struct.pack(HEADER_FORMAT, MAGIC, VERSION, msg_type,
                           payload_length, request_id)

    @staticmethod
    def decode_header(data: bytes) -> tuple:
        """
        Decode the 16-byte message header.

        Args:
            data: 16 bytes of header data

        Returns:
            tuple: (msg_type, request_id, payload_length)

        Raises:
            DirtyProtocolError: If header is invalid
        """
        if len(data) < HEADER_SIZE:
            raise DirtyProtocolError(
                f"Header too short: {len(data)} bytes, expected {HEADER_SIZE}",
                raw_data=data
            )

        magic, version, msg_type, length, request_id = struct.unpack(
            HEADER_FORMAT, data[:HEADER_SIZE]
        )

        if magic != MAGIC:
            raise DirtyProtocolError(
                f"Invalid magic: {magic!r}, expected {MAGIC!r}",
                raw_data=data[:20]
            )

        if version != VERSION:
            raise DirtyProtocolError(
                f"Unsupported protocol version: {version}, expected {VERSION}",
                raw_data=data[:20]
            )

        if msg_type not in MSG_TYPE_TO_STR:
            raise DirtyProtocolError(
                f"Unknown message type: 0x{msg_type:02x}",
                raw_data=data[:20]
            )

        if length > MAX_MESSAGE_SIZE:
            raise DirtyProtocolError(
                f"Message too large: {length} bytes (max: {MAX_MESSAGE_SIZE})"
            )

        return msg_type, request_id, length

    @staticmethod
    def encode_request(request_id: int, app_path: str, action: str,
                       args: tuple = None, kwargs: dict = None) -> bytes:
        """
        Encode a request message.

        Args:
            request_id: Unique request identifier (uint64)
            app_path: Import path of the dirty app
            action: Action to call on the app
            args: Positional arguments
            kwargs: Keyword arguments

        Returns:
            bytes: Complete message (header + payload)
        """
        payload_dict = {
            "app_path": app_path,
            "action": action,
            "args": list(args) if args else [],
            "kwargs": kwargs or {},
        }
        payload = TLVEncoder.encode(payload_dict)
        header = BinaryProtocol.encode_header(MSG_TYPE_REQUEST, request_id,
                                              len(payload))
        return header + payload

    @staticmethod
    def encode_response(request_id: int, result) -> bytes:
        """
        Encode a success response message.

        Args:
            request_id: Request identifier this responds to
            result: Result value (must be TLV-serializable)

        Returns:
            bytes: Complete message (header + payload)
        """
        payload_dict = {"result": result}
        payload = TLVEncoder.encode(payload_dict)
        header = BinaryProtocol.encode_header(MSG_TYPE_RESPONSE, request_id,
                                              len(payload))
        return header + payload

    @staticmethod
    def encode_error(request_id: int, error) -> bytes:
        """
        Encode an error response message.

        Args:
            request_id: Request identifier this responds to
            error: DirtyError instance, dict, or Exception

        Returns:
            bytes: Complete message (header + payload)
        """
        from .errors import DirtyError

        if isinstance(error, DirtyError):
            error_dict = error.to_dict()
        elif isinstance(error, dict):
            error_dict = error
        else:
            error_dict = {
                "error_type": type(error).__name__,
                "message": str(error),
                "details": {},
            }

        payload_dict = {"error": error_dict}
        payload = TLVEncoder.encode(payload_dict)
        header = BinaryProtocol.encode_header(MSG_TYPE_ERROR, request_id,
                                              len(payload))
        return header + payload

    @staticmethod
    def encode_chunk(request_id: int, data) -> bytes:
        """
        Encode a chunk message for streaming responses.

        Args:
            request_id: Request identifier this chunk belongs to
            data: Chunk data (must be TLV-serializable)

        Returns:
            bytes: Complete message (header + payload)
        """
        payload_dict = {"data": data}
        payload = TLVEncoder.encode(payload_dict)
        header = BinaryProtocol.encode_header(MSG_TYPE_CHUNK, request_id,
                                              len(payload))
        return header + payload

    @staticmethod
    def encode_end(request_id: int) -> bytes:
        """
        Encode an end-of-stream message.

        Args:
            request_id: Request identifier this ends

        Returns:
            bytes: Complete message (header + empty payload)
        """
        # End message has empty payload
        header = BinaryProtocol.encode_header(MSG_TYPE_END, request_id, 0)
        return header

    @staticmethod
    def encode_status(request_id: int) -> bytes:
        """
        Encode a status query message.

        Args:
            request_id: Request identifier

        Returns:
            bytes: Complete message (header + empty payload)
        """
        # Status query has empty payload
        header = BinaryProtocol.encode_header(MSG_TYPE_STATUS, request_id, 0)
        return header

    @staticmethod
    def encode_manage(request_id: int, op: int, count: int = 1) -> bytes:
        """
        Encode a worker management message.

        Args:
            request_id: Request identifier
            op: Management operation (MANAGE_OP_ADD or MANAGE_OP_REMOVE)
            count: Number of workers to add/remove

        Returns:
            bytes: Complete message (header + payload)
        """
        payload_dict = {
            "op": op,
            "count": count,
        }
        payload = TLVEncoder.encode(payload_dict)
        header = BinaryProtocol.encode_header(MSG_TYPE_MANAGE, request_id,
                                              len(payload))
        return header + payload

    @staticmethod
    def encode_stash(request_id: int, op: int, table: str,
                     key=None, value=None, pattern=None) -> bytes:
        """
        Encode a stash operation message.

        Args:
            request_id: Unique request identifier (uint64)
            op: Stash operation code (STASH_OP_*)
            table: Table name
            key: Optional key for put/get/delete operations
            value: Optional value for put operation
            pattern: Optional pattern for keys operation

        Returns:
            bytes: Complete message (header + payload)
        """
        payload_dict = {
            "op": op,
            "table": table,
        }
        if key is not None:
            payload_dict["key"] = key
        if value is not None:
            payload_dict["value"] = value
        if pattern is not None:
            payload_dict["pattern"] = pattern

        payload = TLVEncoder.encode(payload_dict)
        header = BinaryProtocol.encode_header(MSG_TYPE_STASH, request_id,
                                              len(payload))
        return header + payload

    @staticmethod
    def decode_message(data: bytes) -> tuple:
        """
        Decode a complete message (header + payload).

        Args:
            data: Complete message bytes

        Returns:
            tuple: (msg_type_str, request_id, payload_dict)
                   msg_type_str is the string name (e.g., "request")
                   payload_dict is the decoded TLV payload as a dict

        Raises:
            DirtyProtocolError: If message is malformed
        """
        msg_type, request_id, length = BinaryProtocol.decode_header(data)

        if len(data) < HEADER_SIZE + length:
            raise DirtyProtocolError(
                f"Incomplete message: expected {HEADER_SIZE + length} bytes, "
                f"got {len(data)}",
                raw_data=data[:50]
            )

        if length == 0:
            # End message has empty payload
            payload_dict = {}
        else:
            payload_data = data[HEADER_SIZE:HEADER_SIZE + length]
            try:
                payload_dict = TLVEncoder.decode_full(payload_data)
            except DirtyProtocolError:
                raise
            except Exception as e:
                raise DirtyProtocolError(
                    f"Failed to decode TLV payload: {e}",
                    raw_data=payload_data[:50]
                )

        # Convert to dict format similar to old JSON protocol
        msg_type_str = MSG_TYPE_TO_STR[msg_type]

        return msg_type_str, request_id, payload_dict

    # -------------------------------------------------------------------------
    # Async API (primary - for DirtyArbiter and DirtyWorker)
    # -------------------------------------------------------------------------

    @staticmethod
    async def read_message_async(reader: asyncio.StreamReader) -> dict:
        """
        Read a complete binary message from async stream.

        Args:
            reader: asyncio StreamReader

        Returns:
            dict: Message dict with 'type', 'id', and payload fields

        Raises:
            DirtyProtocolError: If read fails or message is malformed
            asyncio.IncompleteReadError: If connection closed mid-read
        """
        # Read header
        try:
            header = await reader.readexactly(HEADER_SIZE)
        except asyncio.IncompleteReadError as e:
            if len(e.partial) == 0:
                # Clean close - no data was read
                raise
            raise DirtyProtocolError(
                f"Incomplete header: got {len(e.partial)} bytes, "
                f"expected {HEADER_SIZE}",
                raw_data=e.partial
            )

        msg_type, request_id, length = BinaryProtocol.decode_header(header)

        # Read payload
        if length > 0:
            try:
                payload_data = await reader.readexactly(length)
            except asyncio.IncompleteReadError as e:
                raise DirtyProtocolError(
                    f"Incomplete payload: got {len(e.partial)} bytes, "
                    f"expected {length}",
                    raw_data=e.partial
                )

            try:
                payload_dict = TLVEncoder.decode_full(payload_data)
            except DirtyProtocolError:
                raise
            except Exception as e:
                raise DirtyProtocolError(
                    f"Failed to decode TLV payload: {e}",
                    raw_data=payload_data[:50]
                )
        else:
            payload_dict = {}

        # Build response dict
        msg_type_str = MSG_TYPE_TO_STR[msg_type]
        result = {"type": msg_type_str, "id": request_id}
        result.update(payload_dict)

        return result

    @staticmethod
    async def write_message_async(writer: asyncio.StreamWriter,
                                  message: dict) -> None:
        """
        Write a message to async stream.

        Accepts dict format for backwards compatibility.

        Args:
            writer: asyncio StreamWriter
            message: Message dict with 'type', 'id', and payload fields

        Raises:
            DirtyProtocolError: If encoding fails
            ConnectionError: If write fails
        """
        data = BinaryProtocol._encode_from_dict(message)
        writer.write(data)
        await writer.drain()

    # -------------------------------------------------------------------------
    # Sync API (for HTTP workers that may not be async)
    # -------------------------------------------------------------------------

    @staticmethod
    def _recv_exactly(sock: socket.socket, n: int) -> bytes:
        """
        Receive exactly n bytes from a socket.

        Args:
            sock: Socket to read from
            n: Number of bytes to read

        Returns:
            bytes: Received data

        Raises:
            DirtyProtocolError: If read fails or connection closed
        """
        data = b""
        while len(data) < n:
            chunk = sock.recv(n - len(data))
            if not chunk:
                if len(data) == 0:
                    raise DirtyProtocolError("Connection closed")
                raise DirtyProtocolError(
                    f"Connection closed after {len(data)} bytes, expected {n}",
                    raw_data=data
                )
            data += chunk
        return data

    @staticmethod
    def read_message(sock: socket.socket) -> dict:
        """
        Read a complete message from socket (sync).

        Args:
            sock: Socket to read from

        Returns:
            dict: Message dict with 'type', 'id', and payload fields

        Raises:
            DirtyProtocolError: If read fails or message is malformed
        """
        # Read header
        header = BinaryProtocol._recv_exactly(sock, HEADER_SIZE)
        msg_type, request_id, length = BinaryProtocol.decode_header(header)

        # Read payload
        if length > 0:
            payload_data = BinaryProtocol._recv_exactly(sock, length)
            try:
                payload_dict = TLVEncoder.decode_full(payload_data)
            except DirtyProtocolError:
                raise
            except Exception as e:
                raise DirtyProtocolError(
                    f"Failed to decode TLV payload: {e}",
                    raw_data=payload_data[:50]
                )
        else:
            payload_dict = {}

        # Build response dict
        msg_type_str = MSG_TYPE_TO_STR[msg_type]
        result = {"type": msg_type_str, "id": request_id}
        result.update(payload_dict)

        return result

    @staticmethod
    def write_message(sock: socket.socket, message: dict) -> None:
        """
        Write a message to socket (sync).

        Args:
            sock: Socket to write to
            message: Message dict with 'type', 'id', and payload fields

        Raises:
            DirtyProtocolError: If encoding fails
            OSError: If write fails
        """
        data = BinaryProtocol._encode_from_dict(message)
        sock.sendall(data)

    @staticmethod
    def _encode_from_dict(message: dict) -> bytes:  # pylint: disable=too-many-return-statements
        """
        Encode a message dict to binary format.

        Supports the old dict-based API for backwards compatibility.

        Args:
            message: Message dict with 'type', 'id', and payload fields

        Returns:
            bytes: Complete encoded message
        """
        msg_type_str = message.get("type")
        request_id = message.get("id", 0)

        # Handle string or int request IDs
        if isinstance(request_id, str):
            # For backwards compat with UUID strings, hash to int
            request_id = hash(request_id) & 0xFFFFFFFFFFFFFFFF

        msg_type = MSG_TYPE_FROM_STR.get(msg_type_str)
        if msg_type is None:
            raise DirtyProtocolError(f"Unknown message type: {msg_type_str}")

        if msg_type == MSG_TYPE_REQUEST:
            return BinaryProtocol.encode_request(
                request_id,
                message.get("app_path", ""),
                message.get("action", ""),
                message.get("args"),
                message.get("kwargs")
            )
        elif msg_type == MSG_TYPE_RESPONSE:
            return BinaryProtocol.encode_response(
                request_id,
                message.get("result")
            )
        elif msg_type == MSG_TYPE_ERROR:
            return BinaryProtocol.encode_error(
                request_id,
                message.get("error", {})
            )
        elif msg_type == MSG_TYPE_CHUNK:
            return BinaryProtocol.encode_chunk(
                request_id,
                message.get("data")
            )
        elif msg_type == MSG_TYPE_END:
            return BinaryProtocol.encode_end(request_id)
        elif msg_type == MSG_TYPE_STASH:
            return BinaryProtocol.encode_stash(
                request_id,
                message.get("op"),
                message.get("table", ""),
                message.get("key"),
                message.get("value"),
                message.get("pattern")
            )
        elif msg_type == MSG_TYPE_STATUS:
            return BinaryProtocol.encode_status(request_id)
        elif msg_type == MSG_TYPE_MANAGE:
            return BinaryProtocol.encode_manage(
                request_id,
                message.get("op"),
                message.get("count", 1)
            )
        else:
            raise DirtyProtocolError(f"Unhandled message type: {msg_type}")


# =============================================================================
# Backwards Compatibility Aliases
# =============================================================================

# Alias BinaryProtocol as DirtyProtocol for drop-in replacement
DirtyProtocol = BinaryProtocol


# Message builder helpers (backwards compatible with old API)
def make_request(request_id, app_path: str, action: str,
                 args: tuple = None, kwargs: dict = None) -> dict:
    """
    Build a request message dict.

    Args:
        request_id: Unique request identifier (int or str)
        app_path: Import path of the dirty app (e.g., 'myapp.ml:MLApp')
        action: Action to call on the app
        args: Positional arguments
        kwargs: Keyword arguments

    Returns:
        dict: Request message dict
    """
    return {
        "type": DirtyProtocol.MSG_TYPE_REQUEST,
        "id": request_id,
        "app_path": app_path,
        "action": action,
        "args": list(args) if args else [],
        "kwargs": kwargs or {},
    }


def make_response(request_id, result) -> dict:
    """
    Build a success response message dict.

    Args:
        request_id: Request identifier this responds to
        result: Result value

    Returns:
        dict: Response message dict
    """
    return {
        "type": DirtyProtocol.MSG_TYPE_RESPONSE,
        "id": request_id,
        "result": result,
    }


def make_error_response(request_id, error) -> dict:
    """
    Build an error response message dict.

    Args:
        request_id: Request identifier this responds to
        error: DirtyError instance or dict with error info

    Returns:
        dict: Error response message dict
    """
    from .errors import DirtyError
    if isinstance(error, DirtyError):
        error_dict = error.to_dict()
    elif isinstance(error, dict):
        error_dict = error
    else:
        error_dict = {
            "error_type": type(error).__name__,
            "message": str(error),
            "details": {},
        }

    return {
        "type": DirtyProtocol.MSG_TYPE_ERROR,
        "id": request_id,
        "error": error_dict,
    }


def make_chunk_message(request_id, data) -> dict:
    """
    Build a chunk message dict for streaming responses.

    Args:
        request_id: Request identifier this chunk belongs to
        data: Chunk data

    Returns:
        dict: Chunk message dict
    """
    return {
        "type": DirtyProtocol.MSG_TYPE_CHUNK,
        "id": request_id,
        "data": data,
    }


def make_end_message(request_id) -> dict:
    """
    Build an end-of-stream message dict.

    Args:
        request_id: Request identifier this ends

    Returns:
        dict: End message dict
    """
    return {
        "type": DirtyProtocol.MSG_TYPE_END,
        "id": request_id,
    }


def make_stash_message(request_id, op: int, table: str,
                       key=None, value=None, pattern=None) -> dict:
    """
    Build a stash operation message dict.

    Args:
        request_id: Unique request identifier (int or str)
        op: Stash operation code (STASH_OP_*)
        table: Table name
        key: Optional key for put/get/delete operations
        value: Optional value for put operation
        pattern: Optional pattern for keys operation

    Returns:
        dict: Stash message dict
    """
    msg = {
        "type": DirtyProtocol.MSG_TYPE_STASH,
        "id": request_id,
        "op": op,
        "table": table,
    }
    if key is not None:
        msg["key"] = key
    if value is not None:
        msg["value"] = value
    if pattern is not None:
        msg["pattern"] = pattern
    return msg


def make_manage_message(request_id, op: int, count: int = 1) -> dict:
    """
    Build a worker management message dict.

    Args:
        request_id: Unique request identifier (int or str)
        op: Management operation (MANAGE_OP_ADD or MANAGE_OP_REMOVE)
        count: Number of workers to add/remove

    Returns:
        dict: Manage message dict
    """
    return {
        "type": DirtyProtocol.MSG_TYPE_MANAGE,
        "id": request_id,
        "op": op,
        "count": count,
    }
