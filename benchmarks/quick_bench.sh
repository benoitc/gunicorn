#!/bin/bash
# Quick benchmark for gthread worker

set -e

cd "$(dirname "$0")"

echo "Starting gunicorn with gthread worker..."
../.venv/bin/python -m gunicorn \
    --worker-class gthread \
    --workers 2 \
    --threads 4 \
    --worker-connections 1000 \
    --bind 127.0.0.1:8765 \
    --access-logfile /dev/null \
    --error-logfile /dev/null \
    --log-level warning \
    simple_app:application &

GUNICORN_PID=$!
sleep 3

echo ""
echo "=== Benchmark: Simple requests (10000 requests, 100 concurrent) ==="
ab -n 10000 -c 100 -k http://127.0.0.1:8765/ 2>&1 | grep -E "(Requests per second|Time per request|Failed requests)"

echo ""
echo "=== Benchmark: High concurrency (5000 requests, 500 concurrent) ==="
ab -n 5000 -c 500 -k http://127.0.0.1:8765/ 2>&1 | grep -E "(Requests per second|Time per request|Failed requests)"

echo ""
echo "=== Benchmark: Large response (1000 requests, 50 concurrent) ==="
ab -n 1000 -c 50 -k http://127.0.0.1:8765/large 2>&1 | grep -E "(Requests per second|Time per request|Failed requests)"

echo ""
echo "Stopping gunicorn..."
kill $GUNICORN_PID 2>/dev/null || true
wait $GUNICORN_PID 2>/dev/null || true

echo "Done!"
