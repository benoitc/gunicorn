#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

#!/usr/bin/env python
"""
Test script to demonstrate the Dirty Binary Protocol layer.

The binary protocol uses a 16-byte header + TLV-encoded payloads for efficient
binary data transfer without base64 encoding overhead.

Run with:
    python examples/dirty_example/test_protocol.py
"""

import sys
import os
import asyncio
import socket

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from gunicorn.dirty.protocol import (
    BinaryProtocol,
    DirtyProtocol,
    make_request,
    make_response,
    make_error_response,
    HEADER_SIZE,
    MAGIC,
    VERSION,
)
from gunicorn.dirty.errors import DirtyError, DirtyTimeoutError


def test_protocol_encode_decode():
    """Test protocol encoding and decoding."""
    print("=" * 60)
    print("Testing Binary Protocol Encode/Decode")
    print("=" * 60)

    # Test request with integer ID (recommended for binary protocol)
    print("\n1. Creating a request message...")
    request = make_request(
        request_id=12345,  # Integer IDs are efficient
        app_path="myapp.ml:MLApp",
        action="inference",
        args=("model1",),
        kwargs={"temperature": 0.7}
    )
    print(f"   Request: {request}")

    # Encode using binary protocol
    print("\n2. Encoding message with binary protocol...")
    encoded = BinaryProtocol._encode_from_dict(request)
    print(f"   Encoded length: {len(encoded)} bytes")
    print(f"   Header ({HEADER_SIZE} bytes): {encoded[:HEADER_SIZE].hex()}")
    print(f"   Magic: {MAGIC!r}")
    print(f"   Version: {VERSION}")

    # Decode header
    print("\n3. Decoding header...")
    msg_type, request_id, payload_len = BinaryProtocol.decode_header(encoded[:HEADER_SIZE])
    print(f"   Message type: {msg_type} (0x{msg_type:02x})")
    print(f"   Request ID: {request_id}")
    print(f"   Payload length: {payload_len} bytes")

    # Decode full message
    print("\n4. Decoding full message...")
    msg_type_str, req_id, payload = BinaryProtocol.decode_message(encoded)
    print(f"   Type: {msg_type_str}")
    print(f"   Request ID: {req_id}")
    print(f"   Payload: {payload}")


def test_binary_data_handling():
    """Test binary data handling - the main advantage of binary protocol."""
    print("\n" + "=" * 60)
    print("Testing Binary Data Handling")
    print("=" * 60)

    # Create binary data (e.g., image, audio, model weights)
    binary_data = bytes(range(256))  # All byte values
    print(f"\n1. Original binary data: {len(binary_data)} bytes")
    print(f"   First 16 bytes: {binary_data[:16].hex()}")

    # Create response with binary data (no base64 needed!)
    print("\n2. Encoding binary data in response...")
    response = make_response(67890, {"image_data": binary_data, "format": "raw"})
    encoded = BinaryProtocol._encode_from_dict(response)
    print(f"   Encoded total size: {len(encoded)} bytes")

    # Decode and verify
    print("\n3. Decoding binary data...")
    msg_type_str, req_id, payload = BinaryProtocol.decode_message(encoded)
    recovered_data = payload["result"]["image_data"]
    print(f"   Recovered data size: {len(recovered_data)} bytes")
    print(f"   Data matches: {recovered_data == binary_data}")
    print(f"   First 16 bytes: {recovered_data[:16].hex()}")


def test_protocol_response():
    """Test response message building."""
    print("\n" + "=" * 60)
    print("Testing Response Messages")
    print("=" * 60)

    # Success response
    print("\n1. Creating success response...")
    response = make_response(12345, {"result": "Hello, World!", "confidence": 0.95})
    print(f"   Response: {response}")

    # Error response
    print("\n2. Creating error response...")
    error = DirtyTimeoutError("Operation timed out", timeout=30)
    error_response = make_error_response(12345, error)
    print(f"   Error response: {error_response}")


def test_socket_communication():
    """Test sync protocol over actual sockets."""
    print("\n" + "=" * 60)
    print("Testing Socket Communication")
    print("=" * 60)

    # Create a socket pair
    server_sock, client_sock = socket.socketpair()

    try:
        # Send a request
        print("\n1. Sending request over socket...")
        request = make_request(
            request_id=100001,
            app_path="test:App",
            action="compute",
            args=(1, 2, 3),
            kwargs={}
        )
        DirtyProtocol.write_message(client_sock, request)
        print(f"   Sent: {request}")

        # Receive the request
        print("\n2. Receiving request...")
        received = DirtyProtocol.read_message(server_sock)
        print(f"   Received: {received}")
        print(f"   Request ID: {received['id']}")

        # Send a response with binary data
        print("\n3. Sending response with binary data...")
        binary_result = b"\x00\x01\x02\x03\xff\xfe\xfd\xfc"
        response = make_response(100001, {"data": binary_result, "sum": 6})
        DirtyProtocol.write_message(server_sock, response)
        print(f"   Sent binary data: {binary_result.hex()}")

        # Receive the response
        print("\n4. Receiving response...")
        received = DirtyProtocol.read_message(client_sock)
        print(f"   Received binary data: {received['result']['data'].hex()}")
        print(f"   Sum: {received['result']['sum']}")

    finally:
        server_sock.close()
        client_sock.close()


async def test_async_communication():
    """Test async protocol over streams."""
    print("\n" + "=" * 60)
    print("Testing Async Communication")
    print("=" * 60)

    # Use a pipe for async testing
    read_fd, write_fd = os.pipe()

    try:
        # Create message
        request = make_request(
            request_id=200001,
            app_path="async:App",
            action="process",
            args=("data",),
            kwargs={"async": True}
        )

        # Write to pipe
        print("\n1. Writing async message...")
        encoded = BinaryProtocol._encode_from_dict(request)
        os.write(write_fd, encoded)
        os.close(write_fd)
        write_fd = None
        print(f"   Wrote {len(encoded)} bytes")

        # Read from pipe using async reader
        print("\n2. Reading async message...")
        reader = asyncio.StreamReader()
        data = os.read(read_fd, len(encoded))
        reader.feed_data(data)
        reader.feed_eof()

        received = await DirtyProtocol.read_message_async(reader)
        print(f"   Received: {received}")
        print(f"   Request ID: {received['id']}")

    finally:
        if write_fd is not None:
            os.close(write_fd)
        os.close(read_fd)


def test_error_serialization():
    """Test error serialization and deserialization."""
    print("\n" + "=" * 60)
    print("Testing Error Serialization")
    print("=" * 60)

    # Create various errors
    errors = [
        DirtyError("Generic error", {"code": 500}),
        DirtyTimeoutError("Timeout!", timeout=60),
    ]

    for error in errors:
        print(f"\n1. Original error: {error}")
        print(f"   Type: {type(error).__name__}")

        # Serialize
        error_dict = error.to_dict()
        print(f"2. Serialized: {error_dict}")

        # Deserialize
        restored = DirtyError.from_dict(error_dict)
        print(f"3. Restored: {restored}")
        print(f"   Type: {type(restored).__name__}")
        print(f"   Match type: {type(restored) == type(error)}")


if __name__ == "__main__":
    print("\n" + "#" * 60)
    print("# Dirty Binary Protocol Demonstration")
    print("#" * 60)

    test_protocol_encode_decode()
    test_binary_data_handling()
    test_protocol_response()
    test_socket_communication()
    asyncio.run(test_async_communication())
    test_error_serialization()

    print("\n" + "#" * 60)
    print("# All protocol tests passed!")
    print("#" * 60 + "\n")
