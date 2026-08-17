#!/bin/sh
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.
#
# Run the Docker integration suites, one at a time.
#
# Each suite under tests/docker/ ships its own docker-compose.yml and binds
# fixed host ports, so they cannot share a pytest run: `pytest tests/docker`
# starts them all at once and they answer each other's requests, producing
# failures that have nothing to do with the code. (tests/docker is in
# norecursedirs, so a plain `pytest tests/` skips them entirely.)
#
# Usage:
#   scripts/run_docker_tests.sh              # every suite
#   scripts/run_docker_tests.sh uwsgi http2  # named suites only
#
# Set PYTEST to choose the runner, e.g. PYTEST=".venv/bin/python -m pytest".

set -u

cd "$(dirname "$0")/.." || exit 1

PYTEST="${PYTEST:-python -m pytest}"
DOCKER_DIR="tests/docker"

if [ "$#" -gt 0 ]; then
    suites="$*"
else
    suites=""
    for path in "$DOCKER_DIR"/*/; do
        name=$(basename "$path")
        # Suites are pytest directories; the rest are shell-driven demos.
        if ls "$path"test_*.py >/dev/null 2>&1 ||
            ls "$path"tests/test_*.py >/dev/null 2>&1; then
            suites="$suites $name"
        fi
    done
fi

failed=""
for suite in $suites; do
    dir="$DOCKER_DIR/$suite"
    if [ ! -d "$dir" ]; then
        echo "no such suite: $suite" >&2
        failed="$failed $suite"
        continue
    fi

    echo
    echo "=== $suite ==="
    if ! $PYTEST "$dir"; then
        failed="$failed $suite"
    fi

    if [ -f "$dir/docker-compose.yml" ]; then
        docker compose -f "$dir/docker-compose.yml" down --remove-orphans \
            >/dev/null 2>&1
    fi
done

echo
if [ -n "$failed" ]; then
    echo "FAILED:$failed"
    exit 1
fi
echo "all suites passed"
