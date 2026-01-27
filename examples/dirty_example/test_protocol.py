#!/usr/bin/env python
"""
Test script to demonstrate the Dirty Protocol layer.

Run with:
    python examples/dirty_example/test_protocol.py
"""

import sys
import os
import asyncio
import socket

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from gunicorn.dirty.protocol import (
    DirtyProtocol,
    make_request,
    make_response,
    make_error_response,
)
from gunicorn.dirty.errors import DirtyError, DirtyTimeoutError


def test_protocol_encode_decode():
    """Test protocol encoding and decoding."""
    print("=" * 60)
    print("Testing Protocol Encode/Decode")
    print("=" * 60)

    # Test request
    print("\n1. Creating a request message...")
    request = make_request(
        request_id="req-001",
        app_path="myapp.ml:MLApp",
        action="inference",
        args=("model1",),
        kwargs={"temperature": 0.7}
    )
    print(f"   Request: {request}")

    # Encode
    print("\n2. Encoding message...")
    encoded = DirtyProtocol.encode(request)
    print(f"   Encoded length: {len(encoded)} bytes")
    print(f"   Header (4 bytes): {encoded[:4].hex()}")

    # Decode
    print("\n3. Decoding payload...")
    payload = encoded[DirtyProtocol.HEADER_SIZE:]
    decoded = DirtyProtocol.decode(payload)
    print(f"   Decoded: {decoded}")
    print(f"   Match: {decoded == request}")


def test_protocol_response():
    """Test response message building."""
    print("\n" + "=" * 60)
    print("Testing Response Messages")
    print("=" * 60)

    # Success response
    print("\n1. Creating success response...")
    response = make_response("req-001", {"result": "Hello, World!", "confidence": 0.95})
    print(f"   Response: {response}")

    # Error response
    print("\n2. Creating error response...")
    error = DirtyTimeoutError("Operation timed out", timeout=30)
    error_response = make_error_response("req-001", error)
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
            request_id="socket-req-001",
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
        print(f"   Match: {received == request}")

        # Send a response
        print("\n3. Sending response...")
        response = make_response("socket-req-001", {"sum": 6})
        DirtyProtocol.write_message(server_sock, response)
        print(f"   Sent: {response}")

        # Receive the response
        print("\n4. Receiving response...")
        received = DirtyProtocol.read_message(client_sock)
        print(f"   Received: {received}")
        print(f"   Match: {received == response}")

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
            request_id="async-req-001",
            app_path="async:App",
            action="process",
            args=("data",),
            kwargs={"async": True}
        )

        # Write to pipe
        print("\n1. Writing async message...")
        encoded = DirtyProtocol.encode(request)
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
        print(f"   Match: {received == request}")

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
    print("# Dirty Protocol Demonstration")
    print("#" * 60)

    test_protocol_encode_decode()
    test_protocol_response()
    test_socket_communication()
    asyncio.run(test_async_communication())
    test_error_serialization()

    print("\n" + "#" * 60)
    print("# All protocol tests passed!")
    print("#" * 60 + "\n")
