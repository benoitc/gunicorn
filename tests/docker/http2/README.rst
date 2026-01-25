HTTP/2 Docker Integration Tests
================================

This directory contains Docker-based integration tests for HTTP/2 support
in Gunicorn. These tests verify real HTTP/2 connections using actual HTTP/2
clients, both directly to Gunicorn and through an nginx reverse proxy.

Prerequisites
-------------

- Docker and Docker Compose
- OpenSSL (for generating test certificates)
- Python with ``httpx[http2]`` installed

Running the Tests
-----------------

1. Install test dependencies::

    pip install -e ".[testing]"

2. Generate SSL certificates (done automatically by tests, or manually)::

    cd tests/docker/http2
    openssl req -x509 -newkey rsa:2048 \
        -keyout certs/server.key \
        -out certs/server.crt \
        -days 1 -nodes \
        -subj "/CN=localhost"

3. Run the Docker integration tests::

    # From the project root
    pytest tests/docker/http2/ -v

   Or with Docker Compose manually::

    cd tests/docker/http2
    docker compose up -d
    pytest -v
    docker compose down -v

Test Categories
---------------

- **TestDirectHTTP2Connection**: Direct HTTP/2 connections to Gunicorn
- **TestConcurrentStreams**: HTTP/2 multiplexing with concurrent streams
- **TestHTTP2BehindProxy**: HTTP/2 through nginx reverse proxy
- **TestHTTP2Protocol**: ALPN negotiation and protocol fallback
- **TestHTTP2ErrorHandling**: Error responses over HTTP/2
- **TestHTTP2Headers**: HTTP/2 header handling
- **TestHTTP2Performance**: Performance-related tests

Architecture
------------

::

    +--------+     HTTP/2      +-----------+
    | Client | --------------> | Gunicorn  |
    +--------+                 | (port 8443)|
         |                     +-----------+
         |
         |     HTTP/2      +-------+    HTTPS     +-----------+
         +---------------> | nginx | -----------> | Gunicorn  |
                           | proxy |              | (port 8443)|
                           | (8444)|              +-----------+
                           +-------+

Files
-----

- ``docker-compose.yml`` - Service definitions
- ``Dockerfile.gunicorn`` - Gunicorn container with HTTP/2
- ``Dockerfile.nginx`` - nginx HTTP/2 proxy
- ``nginx.conf`` - nginx configuration
- ``app.py`` - Test WSGI application
- ``conftest.py`` - Pytest fixtures for Docker
- ``test_http2_docker.py`` - Integration tests

Troubleshooting
---------------

If tests fail to start:

1. Check Docker is running::

    docker info

2. Check service logs::

    cd tests/docker/http2
    docker compose logs gunicorn-h2
    docker compose logs nginx-h2

3. Verify certificates::

    openssl x509 -in certs/server.crt -text -noout

4. Test manually with curl::

    curl -k --http2 https://localhost:8443/
    curl -k --http2 https://localhost:8444/
