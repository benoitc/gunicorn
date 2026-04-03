# ASGI Framework Compatibility Test Suite

This test suite validates gunicorn's native ASGI worker (`-k asgi`) against
multiple ASGI frameworks to ensure protocol compliance.

## Frameworks Tested

| Framework | Description |
|-----------|-------------|
| Django + Channels | Django with Channels for WebSocket |
| FastAPI | Modern, fast API framework (Starlette-based) |
| Starlette | Pure ASGI framework |
| Quart | Flask-like async framework |
| Litestar | Modern ASGI framework |
| BlackSheep | High-performance ASGI framework |

## Test Categories

- **HTTP Scope**: ASGI 3.0 HTTP scope compliance
- **HTTP Messages**: Request/response message handling
- **WebSocket**: WebSocket protocol compliance
- **Lifespan**: Startup/shutdown lifecycle
- **Streaming**: Chunked responses and SSE

## Quick Start

```bash
# Build and start all framework containers
docker compose up -d --build

# Run tests
pip install -r requirements.txt
pytest tests/ -v

# Generate compatibility grid
python scripts/generate_grid.py
```

## Testing Event Loop Variants

```bash
# Test with auto-detection (uvloop if available)
ASGI_LOOP=auto docker compose up -d --build
pytest tests/ -v

# Test with asyncio only
ASGI_LOOP=asyncio docker compose up -d --build
pytest tests/ -v

# Test with uvloop explicitly
ASGI_LOOP=uvloop docker compose up -d --build
pytest tests/ -v

# Generate combined report for both loop types
python scripts/generate_grid.py --loop both
```

## Single Framework Testing

```bash
# Test only FastAPI
pytest tests/ -v --framework fastapi

# Test only Django
pytest tests/ -v --framework django
```

## Directory Structure

```
asgi_framework_compat/
├── conftest.py           # Test fixtures
├── docker-compose.yml    # Container orchestration
├── requirements.txt      # Test dependencies
├── frameworks/
│   ├── contract.py       # Endpoint contract
│   ├── django_app/       # Django implementation
│   ├── fastapi_app/      # FastAPI implementation
│   ├── starlette_app/    # Starlette implementation
│   ├── quart_app/        # Quart implementation
│   ├── litestar_app/     # Litestar implementation
│   └── blacksheep_app/   # BlackSheep implementation
├── tests/
│   ├── test_http_scope.py
│   ├── test_http_messages.py
│   ├── test_websocket_scope.py
│   ├── test_lifespan_scope.py
│   └── test_streaming.py
├── scripts/
│   └── generate_grid.py  # Compatibility matrix
└── results/              # Generated reports
```

## Container Management

```bash
# Start containers
docker compose up -d --build

# View logs
docker compose logs -f

# Stop containers
docker compose down

# Rebuild specific framework
docker compose build fastapi
docker compose up -d fastapi
```

## Results

After running `generate_grid.py`, check the `results/` directory for:

- `compatibility_grid_*.md` - Markdown compatibility matrices
- `compatibility_grid_*.json` - JSON data for programmatic access
