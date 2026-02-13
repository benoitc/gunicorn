#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Control Socket Protocol

JSON-based protocol with length-prefixed framing for the control interface.

Message Format:
    +----------------+------------------+
    | Length (4B BE) |  JSON Payload    |
    +----------------+------------------+

Request Format:
    {"id": 1, "command": "show", "args": ["workers"]}

Response Format:
    {"id": 1, "status": "ok", "data": {...}}
    {"id": 1, "status": "error", "error": "message"}
"""

import json
import struct


class ProtocolError(Exception):
    """Protocol-level error."""


class ControlProtocol:
    """
    Protocol implementation for control socket communication.

    Uses 4-byte big-endian length prefix followed by JSON payload.
    """

    # Maximum message size (16 MB)
    MAX_MESSAGE_SIZE = 16 * 1024 * 1024

    @staticmethod
    def encode_message(data: dict) -> bytes:
        """
        Encode a message for transmission.

        Args:
            data: Dictionary to encode

        Returns:
            Length-prefixed JSON bytes
        """
        payload = json.dumps(data).encode('utf-8')
        length = struct.pack('>I', len(payload))
        return length + payload

    @staticmethod
    def decode_message(data: bytes) -> dict:
        """
        Decode a message from bytes.

        Args:
            data: Raw bytes (length prefix + JSON payload)

        Returns:
            Decoded dictionary
        """
        if len(data) < 4:
            raise ProtocolError("Message too short")

        length = struct.unpack('>I', data[:4])[0]
        if len(data) < 4 + length:
            raise ProtocolError("Incomplete message")

        payload = data[4:4 + length]
        return json.loads(payload.decode('utf-8'))

    @staticmethod
    def read_message(sock) -> dict:
        """
        Read one message from a socket.

        Args:
            sock: Socket to read from

        Returns:
            Decoded message dictionary

        Raises:
            ProtocolError: If message is malformed
            ConnectionError: If connection is closed
        """
        # Read length prefix
        length_data = b''
        while len(length_data) < 4:
            chunk = sock.recv(4 - len(length_data))
            if not chunk:
                if not length_data:
                    raise ConnectionError("Connection closed")
                raise ProtocolError("Incomplete length prefix")
            length_data += chunk

        length = struct.unpack('>I', length_data)[0]

        if length > ControlProtocol.MAX_MESSAGE_SIZE:
            raise ProtocolError(f"Message too large: {length}")

        # Read payload
        payload_data = b''
        while len(payload_data) < length:
            chunk = sock.recv(min(length - len(payload_data), 65536))
            if not chunk:
                raise ProtocolError("Incomplete payload")
            payload_data += chunk

        try:
            return json.loads(payload_data.decode('utf-8'))
        except json.JSONDecodeError as e:
            raise ProtocolError(f"Invalid JSON: {e}")

    @staticmethod
    def write_message(sock, data: dict):
        """
        Write one message to a socket.

        Args:
            sock: Socket to write to
            data: Message dictionary to send
        """
        message = ControlProtocol.encode_message(data)
        sock.sendall(message)

    @staticmethod
    async def read_message_async(reader) -> dict:
        """
        Read one message from an async reader.

        Args:
            reader: asyncio StreamReader

        Returns:
            Decoded message dictionary
        """
        # Read length prefix
        length_data = await reader.readexactly(4)
        length = struct.unpack('>I', length_data)[0]

        if length > ControlProtocol.MAX_MESSAGE_SIZE:
            raise ProtocolError(f"Message too large: {length}")

        # Read payload
        payload_data = await reader.readexactly(length)

        try:
            return json.loads(payload_data.decode('utf-8'))
        except json.JSONDecodeError as e:
            raise ProtocolError(f"Invalid JSON: {e}")

    @staticmethod
    async def write_message_async(writer, data: dict):
        """
        Write one message to an async writer.

        Args:
            writer: asyncio StreamWriter
            data: Message dictionary to send
        """
        message = ControlProtocol.encode_message(data)
        writer.write(message)
        await writer.drain()


def make_request(request_id: int, command: str, args: list = None) -> dict:
    """
    Create a request message.

    Args:
        request_id: Unique request identifier
        command: Command name (e.g., "show workers")
        args: Optional list of arguments

    Returns:
        Request dictionary
    """
    return {
        "id": request_id,
        "command": command,
        "args": args or [],
    }


def make_response(request_id: int, data: dict = None) -> dict:
    """
    Create a success response message.

    Args:
        request_id: Request identifier being responded to
        data: Response data

    Returns:
        Response dictionary
    """
    return {
        "id": request_id,
        "status": "ok",
        "data": data or {},
    }


def make_error_response(request_id: int, error: str) -> dict:
    """
    Create an error response message.

    Args:
        request_id: Request identifier being responded to
        error: Error message

    Returns:
        Error response dictionary
    """
    return {
        "id": request_id,
        "status": "error",
        "error": error,
    }
