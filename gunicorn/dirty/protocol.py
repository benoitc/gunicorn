#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Dirty Arbiters Protocol

Length-prefixed JSON message framing over Unix sockets.
Provides both async (primary) and sync (for HTTP workers) APIs.

Message Format:
+----------------+------------------+
| 4-byte length  | JSON payload     |
+----------------+------------------+

The length field is a 4-byte unsigned integer in network byte order (big-endian).
"""

import asyncio
import json
import struct
import socket

from .errors import DirtyProtocolError


class DirtyProtocol:
    """Length-prefixed JSON messages over Unix sockets."""

    # 4-byte unsigned int, network byte order (big-endian)
    HEADER_FORMAT = "!I"
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

    # Maximum message size (64 MB)
    MAX_MESSAGE_SIZE = 64 * 1024 * 1024

    # Message types for future streaming support
    MSG_TYPE_REQUEST = "request"
    MSG_TYPE_RESPONSE = "response"
    MSG_TYPE_ERROR = "error"
    MSG_TYPE_CHUNK = "chunk"
    MSG_TYPE_END = "end"

    @staticmethod
    def encode(message: dict) -> bytes:
        """
        Encode a message dict to length-prefixed bytes.

        Args:
            message: Dictionary to encode as JSON

        Returns:
            bytes: Length-prefixed encoded message

        Raises:
            DirtyProtocolError: If encoding fails
        """
        try:
            payload = json.dumps(message).encode("utf-8")
            if len(payload) > DirtyProtocol.MAX_MESSAGE_SIZE:
                raise DirtyProtocolError(
                    f"Message too large: {len(payload)} bytes "
                    f"(max: {DirtyProtocol.MAX_MESSAGE_SIZE})"
                )
            length = struct.pack(DirtyProtocol.HEADER_FORMAT, len(payload))
            return length + payload
        except (TypeError, ValueError) as e:
            raise DirtyProtocolError(f"Failed to encode message: {e}")

    @staticmethod
    def decode(data: bytes) -> dict:
        """
        Decode bytes (without length prefix) to message dict.

        Args:
            data: JSON bytes to decode

        Returns:
            dict: Decoded message

        Raises:
            DirtyProtocolError: If decoding fails
        """
        try:
            return json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise DirtyProtocolError(f"Failed to decode message: {e}",
                                     raw_data=data)

    # -------------------------------------------------------------------------
    # Async API (primary - for DirtyArbiter and DirtyWorker)
    # -------------------------------------------------------------------------

    @staticmethod
    async def read_message_async(reader: asyncio.StreamReader) -> dict:
        """
        Read a complete message from async stream.

        Args:
            reader: asyncio StreamReader

        Returns:
            dict: Decoded message

        Raises:
            DirtyProtocolError: If read fails or message is malformed
            asyncio.IncompleteReadError: If connection closed mid-read
        """
        # Read length header
        try:
            header = await reader.readexactly(DirtyProtocol.HEADER_SIZE)
        except asyncio.IncompleteReadError as e:
            if len(e.partial) == 0:
                # Clean close - no data was read
                raise
            raise DirtyProtocolError(
                f"Incomplete header: got {len(e.partial)} bytes, "
                f"expected {DirtyProtocol.HEADER_SIZE}",
                raw_data=e.partial
            )

        length = struct.unpack(DirtyProtocol.HEADER_FORMAT, header)[0]

        if length > DirtyProtocol.MAX_MESSAGE_SIZE:
            raise DirtyProtocolError(
                f"Message too large: {length} bytes "
                f"(max: {DirtyProtocol.MAX_MESSAGE_SIZE})"
            )

        if length == 0:
            raise DirtyProtocolError("Empty message received")

        # Read payload
        try:
            payload = await reader.readexactly(length)
        except asyncio.IncompleteReadError as e:
            raise DirtyProtocolError(
                f"Incomplete message: got {len(e.partial)} bytes, "
                f"expected {length}",
                raw_data=e.partial
            )

        return DirtyProtocol.decode(payload)

    @staticmethod
    async def write_message_async(writer: asyncio.StreamWriter,
                                  message: dict) -> None:
        """
        Write a message to async stream.

        Args:
            writer: asyncio StreamWriter
            message: Dictionary to send

        Raises:
            DirtyProtocolError: If encoding fails
            ConnectionError: If write fails
        """
        data = DirtyProtocol.encode(message)
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
            dict: Decoded message

        Raises:
            DirtyProtocolError: If read fails or message is malformed
        """
        # Read length header
        header = DirtyProtocol._recv_exactly(sock, DirtyProtocol.HEADER_SIZE)
        length = struct.unpack(DirtyProtocol.HEADER_FORMAT, header)[0]

        if length > DirtyProtocol.MAX_MESSAGE_SIZE:
            raise DirtyProtocolError(
                f"Message too large: {length} bytes "
                f"(max: {DirtyProtocol.MAX_MESSAGE_SIZE})"
            )

        if length == 0:
            raise DirtyProtocolError("Empty message received")

        # Read payload
        payload = DirtyProtocol._recv_exactly(sock, length)
        return DirtyProtocol.decode(payload)

    @staticmethod
    def write_message(sock: socket.socket, message: dict) -> None:
        """
        Write a message to socket (sync).

        Args:
            sock: Socket to write to
            message: Dictionary to send

        Raises:
            DirtyProtocolError: If encoding fails
            OSError: If write fails
        """
        data = DirtyProtocol.encode(message)
        sock.sendall(data)


# Message builder helpers
def make_request(request_id: str, app_path: str, action: str,
                 args: tuple = None, kwargs: dict = None) -> dict:
    """
    Build a request message.

    Args:
        request_id: Unique request identifier
        app_path: Import path of the dirty app (e.g., 'myapp.ml:MLApp')
        action: Action to call on the app
        args: Positional arguments
        kwargs: Keyword arguments

    Returns:
        dict: Request message
    """
    return {
        "type": DirtyProtocol.MSG_TYPE_REQUEST,
        "id": request_id,
        "app_path": app_path,
        "action": action,
        "args": list(args) if args else [],
        "kwargs": kwargs or {},
    }


def make_response(request_id: str, result) -> dict:
    """
    Build a success response message.

    Args:
        request_id: Request identifier this responds to
        result: Result value (must be JSON-serializable)

    Returns:
        dict: Response message
    """
    return {
        "type": DirtyProtocol.MSG_TYPE_RESPONSE,
        "id": request_id,
        "result": result,
    }


def make_error_response(request_id: str, error) -> dict:
    """
    Build an error response message.

    Args:
        request_id: Request identifier this responds to
        error: DirtyError instance or dict with error info

    Returns:
        dict: Error response message
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


def make_chunk_message(request_id: str, data) -> dict:
    """
    Build a chunk message for streaming responses.

    Args:
        request_id: Request identifier this chunk belongs to
        data: Chunk data (must be JSON-serializable)

    Returns:
        dict: Chunk message
    """
    return {
        "type": DirtyProtocol.MSG_TYPE_CHUNK,
        "id": request_id,
        "data": data,
    }


def make_end_message(request_id: str) -> dict:
    """
    Build an end-of-stream message.

    Args:
        request_id: Request identifier this ends

    Returns:
        dict: End message
    """
    return {
        "type": DirtyProtocol.MSG_TYPE_END,
        "id": request_id,
    }
