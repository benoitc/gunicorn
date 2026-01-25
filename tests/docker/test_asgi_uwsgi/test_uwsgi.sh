#!/bin/bash
# Integration test for ASGI uWSGI protocol support
#
# This script tests that gunicorn's ASGI worker correctly handles
# the uWSGI protocol when nginx forwards requests using uwsgi_pass.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Use IPv4 explicitly to avoid Docker IPv6 issues
BASE_URL="http://127.0.0.1:8080"

cleanup() {
    echo "Cleaning up..."
    docker compose down -v 2>/dev/null || true
}

trap cleanup EXIT

echo "=== Building and starting containers ==="
docker compose up -d --build

echo "=== Waiting for services to be ready ==="
sleep 5

echo "=== Running tests ==="

# Test 1: Simple GET request
echo "Test 1: Simple GET request"
RESPONSE=$(curl -s "$BASE_URL/")
if echo "$RESPONSE" | grep -q "Method: GET"; then
    echo "  PASS: GET request works"
else
    echo "  FAIL: GET request failed"
    echo "  Response: $RESPONSE"
    exit 1
fi

# Test 2: GET with query string
echo "Test 2: GET with query string"
RESPONSE=$(curl -s "$BASE_URL/search?q=test&page=1")
if echo "$RESPONSE" | grep -q "Query: q=test&page=1"; then
    echo "  PASS: Query string works"
else
    echo "  FAIL: Query string failed"
    echo "  Response: $RESPONSE"
    exit 1
fi

# Test 3: POST with body
echo "Test 3: POST with body"
RESPONSE=$(curl -s -X POST -d "hello=world" "$BASE_URL/submit")
if echo "$RESPONSE" | grep -q "Method: POST" && echo "$RESPONSE" | grep -q "Body: hello=world"; then
    echo "  PASS: POST with body works"
else
    echo "  FAIL: POST with body failed"
    echo "  Response: $RESPONSE"
    exit 1
fi

# Test 4: Path handling
echo "Test 4: Path handling"
RESPONSE=$(curl -s "$BASE_URL/api/v1/users")
if echo "$RESPONSE" | grep -q "Path: /api/v1/users"; then
    echo "  PASS: Path handling works"
else
    echo "  FAIL: Path handling failed"
    echo "  Response: $RESPONSE"
    exit 1
fi

# Test 5: Multiple requests (keepalive)
echo "Test 5: Multiple requests (keepalive)"
for i in 1 2 3; do
    RESPONSE=$(curl -s "$BASE_URL/request/$i")
    if ! echo "$RESPONSE" | grep -q "Path: /request/$i"; then
        echo "  FAIL: Request $i failed"
        exit 1
    fi
done
echo "  PASS: Multiple requests work"

echo ""
echo "=== All tests passed! ==="
