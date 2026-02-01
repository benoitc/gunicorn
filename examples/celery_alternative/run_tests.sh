#!/bin/bash
# Run tests for Celery Replacement example

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUNICORN_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Add gunicorn to Python path
export PYTHONPATH="$GUNICORN_ROOT:$PYTHONPATH"

cd "$SCRIPT_DIR"

echo "=========================================="
echo "Running Unit Tests"
echo "=========================================="
python -m pytest tests/test_tasks.py -v --tb=short

echo ""
echo "=========================================="
echo "Unit tests passed!"
echo "=========================================="

# Check if integration tests should run
if [ "$1" == "--integration" ] || [ "$1" == "-i" ]; then
    APP_URL="${APP_URL:-http://localhost:8000}"
    echo ""
    echo "=========================================="
    echo "Running Integration Tests against $APP_URL"
    echo "=========================================="
    python -m pytest tests/test_integration.py -v --tb=short
fi

echo ""
echo "All tests completed successfully!"
