#!/bin/bash
# Run ASGI Framework Compatibility Tests
#
# Usage:
#   ./scripts/run_tests.sh              # Run with auto loop detection
#   ./scripts/run_tests.sh asyncio      # Run with asyncio loop
#   ./scripts/run_tests.sh uvloop       # Run with uvloop
#   ./scripts/run_tests.sh both         # Run both and generate combined report

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"

cd "$BASE_DIR"

LOOP_TYPE="${1:-auto}"

echo "=== ASGI Framework Compatibility Test Suite ==="
echo "Loop type: $LOOP_TYPE"
echo ""

# Install test dependencies if needed
if ! python -c "import pytest" 2>/dev/null; then
    echo "Installing test dependencies..."
    pip install -r requirements.txt
fi

if [ "$LOOP_TYPE" = "both" ]; then
    echo "Running tests with asyncio loop..."
    ASGI_LOOP=asyncio docker compose up -d --build
    sleep 10  # Wait for services
    pytest tests/ -v --tb=short || true
    docker compose down

    echo ""
    echo "Running tests with uvloop..."
    ASGI_LOOP=uvloop docker compose up -d --build
    sleep 10  # Wait for services
    pytest tests/ -v --tb=short || true
    docker compose down

    echo ""
    echo "Generating combined report..."
    python scripts/generate_grid.py --loop both --skip-tests
else
    echo "Starting containers with $LOOP_TYPE loop..."
    ASGI_LOOP="$LOOP_TYPE" docker compose up -d --build

    echo "Waiting for services to be healthy..."
    sleep 15

    echo ""
    echo "Running tests..."
    pytest tests/ -v --tb=short

    echo ""
    echo "Generating compatibility grid..."
    python scripts/generate_grid.py --loop "$LOOP_TYPE"

    echo ""
    echo "Results saved to results/"
fi

echo ""
echo "Done!"
