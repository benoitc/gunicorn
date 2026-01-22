# uWSGI Protocol Docker Integration Tests

This directory contains Docker-based integration tests that verify gunicorn's
uWSGI binary protocol implementation works correctly with nginx's `uwsgi_pass`
directive.

## Architecture

```
[pytest] --HTTP--> [nginx:8080] --uwsgi_pass--> [gunicorn:8000]
```

The tests make HTTP requests to nginx, which proxies them to gunicorn using the
uWSGI binary protocol. This validates the complete request/response cycle through
the protocol.

## Prerequisites

- Docker
- Docker Compose (v2)
- Python 3.8+
- pytest
- requests

## Running Tests

### From repository root:

```bash
# Run all uWSGI integration tests
pytest tests/docker/uwsgi/ -v

# Run specific test class
pytest tests/docker/uwsgi/ -v -k TestBasicRequests

# Skip Docker tests (for CI environments without Docker)
pytest tests/ -v -m "not docker"
```

### Manual testing:

```bash
cd tests/docker/uwsgi

# Start services
docker compose up -d

# Wait for services to be healthy
docker compose ps

# Test endpoints
curl http://localhost:8080/
curl -X POST -d "test body" http://localhost:8080/echo
curl http://localhost:8080/headers
curl "http://localhost:8080/query?foo=bar"
curl http://localhost:8080/environ
curl http://localhost:8080/error/404
curl http://localhost:8080/large > /dev/null  # 1MB response

# View logs
docker compose logs gunicorn
docker compose logs nginx

# Stop services
docker compose down -v
```

## Test Categories

| Category | Description |
|----------|-------------|
| `TestBasicRequests` | GET, POST, query strings, large bodies |
| `TestHeaderPreservation` | Custom headers, Host, Content-Type, User-Agent |
| `TestKeepAlive` | Multiple requests per connection |
| `TestErrorResponses` | HTTP error codes (400, 404, 500, etc.) |
| `TestEnvironVariables` | WSGI environ: REQUEST_METHOD, PATH_INFO, etc. |
| `TestLargeResponses` | 1MB response body streaming |
| `TestConcurrency` | Parallel request handling |
| `TestSpecialCases` | Edge cases: binary data, unicode, long headers |

## Files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Orchestrates nginx + gunicorn containers |
| `Dockerfile.gunicorn` | Builds gunicorn image with test app |
| `Dockerfile.nginx` | Builds nginx with uwsgi config |
| `nginx.conf` | nginx configuration using `uwsgi_pass` |
| `uwsgi_params` | Standard uwsgi parameter mappings |
| `app.py` | Test WSGI application with multiple endpoints |
| `conftest.py` | pytest fixtures for Docker lifecycle |
| `test_uwsgi_integration.py` | Test cases |

## Test App Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Basic hello response |
| `/echo` | POST | Echo request body |
| `/headers` | GET/POST | Return received headers as JSON |
| `/environ` | GET/POST | Return WSGI environ as JSON |
| `/query` | GET | Return query params as JSON |
| `/json` | POST | Parse and echo JSON body |
| `/error/{code}` | GET | Return specified HTTP error |
| `/large` | GET | Return 1MB response |

## Gunicorn Configuration

The gunicorn container runs with:

```bash
gunicorn \
  --protocol uwsgi \
  --uwsgi-allow-from "*" \
  --bind 0.0.0.0:8000 \
  --workers 2 \
  --log-level debug \
  app:application
```

Key settings:
- `--protocol uwsgi`: Enable uWSGI binary protocol
- `--uwsgi-allow-from "*"`: Accept connections from Docker network IPs

## Troubleshooting

### Services won't start

Check Docker logs:
```bash
docker compose logs
```

### Connection refused

Wait for health checks:
```bash
docker compose ps  # Check health status
```

### Tests timing out

Increase `STARTUP_TIMEOUT` in `conftest.py` or check if ports are in use:
```bash
lsof -i :8080
lsof -i :8000
```

### Rebuild after code changes

```bash
docker compose build --no-cache
docker compose up -d
```
