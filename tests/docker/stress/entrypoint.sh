#!/bin/sh
#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.
#
# Build the gunicorn argv from environment variables so one image serves every
# worker/topology/protocol combination in the stress suite.
set -eu

WORKER="${WORKER:-asgi}"
USE_SSL="${USE_SSL:-0}"
PROTOCOL="${PROTOCOL:-http}"
WORKERS="${WORKERS:-2}"
THREADS="${THREADS:-4}"
WORKER_CONNECTIONS="${WORKER_CONNECTIONS:-1000}"
MAX_REQUESTS="${MAX_REQUESTS:-0}"
MAX_REQUESTS_JITTER="${MAX_REQUESTS_JITTER:-0}"
HTTP_PROTOCOLS="${HTTP_PROTOCOLS:-h1}"
ASGI_LOOP="${ASGI_LOOP:-auto}"
GRACEFUL_TIMEOUT="${GRACEFUL_TIMEOUT:-30}"

if [ "$WORKER" = "asgi" ]; then
    APP="stress_app:asgi"
else
    APP="stress_app:wsgi"
fi

if [ "$USE_SSL" = "1" ]; then
    BIND="[::]:8443"
elif [ "$PROTOCOL" = "uwsgi" ]; then
    BIND="0.0.0.0:8000"
else
    BIND="[::]:8000"
fi

set -- gunicorn "$APP" \
    --bind "$BIND" \
    --worker-class "$WORKER" \
    --workers "$WORKERS" \
    --worker-connections "$WORKER_CONNECTIONS" \
    --max-requests "$MAX_REQUESTS" \
    --max-requests-jitter "$MAX_REQUESTS_JITTER" \
    --graceful-timeout "$GRACEFUL_TIMEOUT" \
    --access-logfile - --error-logfile - --log-level "${LOG_LEVEL:-info}"

if [ "$WORKER" = "gthread" ]; then
    set -- "$@" --threads "$THREADS"
fi

if [ "$WORKER" = "asgi" ]; then
    set -- "$@" --asgi-loop "$ASGI_LOOP" --asgi-disconnect-grace-period 0
fi

if [ "$PROTOCOL" = "uwsgi" ]; then
    set -- "$@" --protocol uwsgi --uwsgi-allow-from '*'
fi

if [ "$USE_SSL" = "1" ]; then
    set -- "$@" --certfile /certs/server.crt --keyfile /certs/server.key \
        --http-protocols "$HTTP_PROTOCOLS"
fi

echo "stress entrypoint: $*" >&2
exec "$@"
