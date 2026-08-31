h2spec conformance
==================

Runs `h2spec <https://github.com/summerwind/h2spec>`_ (RFC 7540 and HPACK
conformance, 146 cases) against gunicorn on each HTTP/2 capable worker:
``gthread``, ``gevent`` and ``asgi``. h2spec runs from its official image
inside the compose network, so nothing needs to be installed on the host
besides Docker.

Run it on its own or through the shared runner::

    PYTEST=".venv/bin/python -m pytest" scripts/run_docker_tests.sh h2spec

Each worker has a list of known failing cases in ``test_h2spec.py``. A case
failing outside that list fails the test; a listed case that starts passing
is reported as an expected failure so the list can be trimmed.

Ports 8451, 8452 and 8453 are bound on the host for manual runs, for
example with a locally installed binary::

    h2spec -h 127.0.0.1 -p 8451 -t -k
