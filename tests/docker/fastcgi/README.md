# FastCGI Protocol Integration Tests

This directory contains Docker-based integration tests for gunicorn's FastCGI
binary protocol support.

## Overview

These tests verify that gunicorn correctly implements the FastCGI binary
protocol by running actual requests through nginx's `fastcgi_pass` directive.

## Architecture

```
┌─────────────┐      FastCGI       ┌─────────────┐
│   nginx     │ ─────────────────> │  gunicorn   │
│  (port 8081)│                    │  (port 9000)│
└─────────────┘                    └─────────────┘
       │
       │ HTTP
       │
┌──────▼──────┐
│ pytest tests │
└─────────────┘
```

## Prerequisites

- Docker
- Docker Compose
- Python 3.8+ with pytest and requests

## Running the Tests

### From the repository root:

```bash
# Run FastCGI integration tests
pytest tests/docker/fastcgi/ -v

# Run with more verbose output
pytest tests/docker/fastcgi/ -v --tb=long
```

### Manual Testing

You can also start the containers manually:

```bash
cd tests/docker/fastcgi

# Build and start
docker compose up --build

# In another terminal, test with curl
curl http://localhost:8081/
curl http://localhost:8081/headers
curl -X POST -d "test body" http://localhost:8081/echo

# Stop containers
docker compose down -v
```

## Test Coverage

The tests cover:

- **Basic Requests**: GET, POST with various body types
- **Header Preservation**: Custom headers, Content-Type, User-Agent
- **Keep-Alive**: Multiple requests per connection
- **Error Responses**: Various HTTP error codes
- **Large Responses**: 1MB response bodies
- **Concurrent Requests**: Multiple simultaneous requests
- **WSGI Environ**: Correct population of environ variables

## Files

- `docker-compose.yml` - Docker Compose configuration
- `Dockerfile.gunicorn` - Gunicorn container with FastCGI protocol
- `Dockerfile.nginx` - Nginx container with fastcgi_pass
- `nginx.conf` - Nginx configuration for FastCGI proxy
- `app.py` - Test WSGI application
- `conftest.py` - pytest fixtures for Docker management
- `test_fastcgi_integration.py` - Integration test cases

## Troubleshooting

If tests fail, check the container logs:

```bash
cd tests/docker/fastcgi
docker compose logs gunicorn
docker compose logs nginx
```

Common issues:
- Port 8081 already in use: Stop other services or modify docker-compose.yml
- Docker not running: Start Docker Desktop or the Docker daemon
- Build failures: Check that gunicorn source is accessible
