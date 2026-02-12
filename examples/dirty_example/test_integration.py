#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

#!/usr/bin/env python
"""
Integration test for the dirty example server.

This tests that the full gunicorn server with dirty workers responds
correctly to HTTP requests.

Run with:
    python examples/dirty_example/test_integration.py [base_url]

Default base_url is http://localhost:8000
"""

import sys
import os
import json
import urllib.request
import urllib.error


def test_endpoint(base, path, expected_key=None):
    """Test an endpoint and check for expected key in response."""
    url = base + path
    print(f"Testing: {url}")
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            print(f"  Response: {str(data)[:200]}")
            if expected_key and expected_key not in data:
                print(f"  ERROR: Expected key '{expected_key}' not found!")
                return False
            return True
    except urllib.error.HTTPError as e:
        print(f"  HTTP ERROR {e.code}: {e.reason}")
        return False
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def main():
    # Get base URL from env or command line
    base = os.environ.get("TEST_BASE_URL", "http://localhost:8000")
    if len(sys.argv) > 1:
        base = sys.argv[1]

    print(f"Testing dirty example server at: {base}")
    print("=" * 60)

    # Define tests: (path, expected_key_in_response)
    tests = [
        ("/", "endpoints"),
        ("/models", "models"),
        ("/load?name=test-model", "status"),
        ("/inference?model=default&data=hello", "prediction"),
        ("/fibonacci?n=20", "result"),
        ("/prime?n=17", "is_prime"),
        ("/stats", "ml_app"),
        ("/unload?name=test-model", "status"),
    ]

    failed = 0
    for path, key in tests:
        if not test_endpoint(base, path, key):
            failed += 1
        print()

    print("=" * 60)
    if failed:
        print(f"FAILED: {failed} tests failed")
        sys.exit(1)
    else:
        print("SUCCESS: All integration tests passed!")


if __name__ == "__main__":
    main()
