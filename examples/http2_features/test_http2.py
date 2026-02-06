#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

#!/usr/bin/env python
"""
Test script for HTTP/2 features example.

This script tests:
- HTTP/2 connection establishment
- Stream priority access
- Response trailers

Run the server first:
    docker compose up --build

Then run tests:
    python test_http2.py

Or run directly against local server:
    python test_http2.py --url https://localhost:8443
"""

import argparse
import json
import ssl
import socket
import sys
from urllib.parse import urlparse


def create_h2_connection(host, port):
    """Create an HTTP/2 connection using the h2 library."""
    try:
        import h2.connection
        import h2.config
    except ImportError:
        print("Please install h2: pip install h2")
        sys.exit(1)

    # Create socket with SSL
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_alpn_protocols(['h2'])

    sock = ctx.wrap_socket(sock, server_hostname=host)
    sock.connect((host, port))
    sock.settimeout(10.0)

    # Verify ALPN
    alpn = sock.selected_alpn_protocol()
    if alpn != 'h2':
        raise RuntimeError(f"HTTP/2 not negotiated, got: {alpn}")

    # Create h2 connection
    config = h2.config.H2Configuration(client_side=True)
    h2_conn = h2.connection.H2Connection(config=config)
    h2_conn.initiate_connection()
    sock.sendall(h2_conn.data_to_send())

    # Receive server settings
    data = sock.recv(65536)
    h2_conn.receive_data(data)
    sock.sendall(h2_conn.data_to_send())

    return sock, h2_conn


def h2_request(sock, h2_conn, stream_id, method, path, authority):
    """Make an HTTP/2 request and return the response."""
    import h2.events

    # Send request
    h2_conn.send_headers(stream_id, [
        (':method', method),
        (':path', path),
        (':authority', authority),
        (':scheme', 'https'),
    ], end_stream=True)
    sock.sendall(h2_conn.data_to_send())

    # Collect response
    status = None
    headers = {}
    body = b''
    trailers = {}

    while True:
        data = sock.recv(65536)
        if not data:
            break

        events = h2_conn.receive_data(data)
        to_send = h2_conn.data_to_send()
        if to_send:
            sock.sendall(to_send)

        for event in events:
            if isinstance(event, h2.events.ResponseReceived):
                if event.stream_id == stream_id:
                    for name, value in event.headers:
                        if name == b':status':
                            status = int(value.decode())
                        else:
                            headers[name.decode()] = value.decode()

            elif isinstance(event, h2.events.DataReceived):
                if event.stream_id == stream_id:
                    body += event.data

            elif isinstance(event, h2.events.TrailersReceived):
                if event.stream_id == stream_id:
                    for name, value in event.headers:
                        trailers[name.decode()] = value.decode()

            elif isinstance(event, h2.events.StreamEnded):
                if event.stream_id == stream_id:
                    return {
                        'status': status,
                        'headers': headers,
                        'body': body,
                        'trailers': trailers,
                    }

            elif isinstance(event, h2.events.ConnectionTerminated):
                raise RuntimeError(f"Connection terminated: {event.error_code}")

    return None


def test_http2_connection(host, port):
    """Test that HTTP/2 is negotiated."""
    print("\n=== Testing HTTP/2 Connection ===")

    try:
        sock, h2_conn = create_h2_connection(host, port)
        print("HTTP/2 connection established successfully!")

        response = h2_request(sock, h2_conn, 1, 'GET', '/', f'{host}:{port}')
        print(f"Status: {response['status']}")

        data = json.loads(response['body'].decode())
        print(f"Extensions available: {data.get('extensions', [])}")

        sock.close()
        return response['status'] == 200
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def test_priority(host, port):
    """Test stream priority endpoint."""
    print("\n=== Testing Stream Priority ===")

    try:
        sock, h2_conn = create_h2_connection(host, port)

        response = h2_request(sock, h2_conn, 1, 'GET', '/priority', f'{host}:{port}')
        print(f"Status: {response['status']}")

        data = json.loads(response['body'].decode())
        print(f"Priority info: {data.get('priority')}")

        if data.get("priority"):
            print(f"  Weight: {data['priority']['weight']}")
            print(f"  Depends on: {data['priority']['depends_on']}")

        sock.close()
        return response['status'] == 200 and data.get("priority") is not None
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def test_trailers(host, port):
    """Test response trailers."""
    print("\n=== Testing Response Trailers ===")

    try:
        sock, h2_conn = create_h2_connection(host, port)

        response = h2_request(sock, h2_conn, 1, 'GET', '/trailers', f'{host}:{port}')
        print(f"Status: {response['status']}")
        print(f"Headers: {response['headers']}")

        if response['trailers']:
            print(f"Trailers received: {response['trailers']}")
            if 'content-md5' in response['trailers']:
                print(f"  Content-MD5: {response['trailers']['content-md5']}")
        else:
            print("Note: No trailers received (client may not have advertised support)")

        sock.close()
        return response['status'] == 200
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def test_combined(host, port):
    """Test combined priority and trailers."""
    print("\n=== Testing Combined Features ===")

    try:
        sock, h2_conn = create_h2_connection(host, port)

        response = h2_request(sock, h2_conn, 1, 'GET', '/combined', f'{host}:{port}')
        print(f"Status: {response['status']}")

        data = json.loads(response['body'].decode())
        print(f"Response: {json.dumps(data, indent=2)}")

        if response['trailers']:
            print(f"Trailers: {response['trailers']}")

        sock.close()
        return response['status'] == 200
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def test_multiple_streams(host, port):
    """Test multiple requests on the same connection."""
    print("\n=== Testing Multiple Streams ===")

    try:
        sock, h2_conn = create_h2_connection(host, port)

        # Make multiple requests on the same connection
        paths = ['/', '/priority', '/trailers', '/combined']
        for i, path in enumerate(paths):
            stream_id = i * 2 + 1  # Odd numbers for client-initiated streams
            response = h2_request(sock, h2_conn, stream_id, 'GET', path, f'{host}:{port}')
            print(f"  {path}: {response['status']}")

        sock.close()
        return True
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Test HTTP/2 features")
    parser.add_argument(
        "--url",
        default="https://localhost:8443",
        help="Base URL of the server (default: https://localhost:8443)"
    )
    args = parser.parse_args()

    parsed = urlparse(args.url)
    host = parsed.hostname or 'localhost'
    port = parsed.port or 8443

    print(f"Testing against: {host}:{port}")

    results = []

    try:
        results.append(("HTTP/2 Connection", test_http2_connection(host, port)))
        results.append(("Stream Priority", test_priority(host, port)))
        results.append(("Response Trailers", test_trailers(host, port)))
        results.append(("Combined Features", test_combined(host, port)))
        results.append(("Multiple Streams", test_multiple_streams(host, port)))
    except ConnectionRefusedError:
        print(f"\nConnection refused to {host}:{port}")
        print("Make sure the server is running: docker compose up --build")
        return 1
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        return 1

    print("\n=== Test Results ===")
    all_passed = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    if all_passed:
        print("\nAll tests passed!")
        return 0
    else:
        print("\nSome tests failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
