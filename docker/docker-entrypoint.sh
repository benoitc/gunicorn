#!/bin/bash
set -e

# Allow running other commands (e.g., bash for debugging)
if [ "${1:0:1}" = '-' ] || [ -z "${1##*:*}" ]; then
    # First arg is a flag or contains ':' (app:callable), run gunicorn

    # Build bind address from GUNICORN_HOST and GUNICORN_PORT, or use GUNICORN_BIND
    PORT="${GUNICORN_PORT:-8000}"
    BIND="${GUNICORN_BIND:-${GUNICORN_HOST:-0.0.0.0}:${PORT}}"

    # Add bind if not specified in args or GUNICORN_ARGS
    if [[ ! " $* $GUNICORN_ARGS " =~ " --bind " ]] && [[ ! " $* $GUNICORN_ARGS " =~ " -b " ]] && [[ ! "$* $GUNICORN_ARGS" =~ --bind= ]] && [[ ! "$* $GUNICORN_ARGS" =~ -b= ]]; then
        set -- --bind "$BIND" "$@"
    fi

    # Add workers if not specified - default to (2 * CPU_COUNT) + 1
    if [[ ! " $* $GUNICORN_ARGS " =~ " --workers " ]] && [[ ! " $* $GUNICORN_ARGS " =~ " -w " ]] && [[ ! "$* $GUNICORN_ARGS" =~ --workers= ]] && [[ ! "$* $GUNICORN_ARGS" =~ -w= ]]; then
        WORKERS="${GUNICORN_WORKERS:-$(( 2 * $(nproc) + 1 ))}"
        set -- --workers "$WORKERS" "$@"
    fi

    # Append GUNICORN_ARGS if set
    if [ -n "$GUNICORN_ARGS" ]; then
        exec gunicorn $GUNICORN_ARGS "$@"
    fi

    exec gunicorn "$@"
fi

# Otherwise, run the command as-is (e.g., bash, sh, python)
exec "$@"
