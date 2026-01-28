# HTTP/2 with Gevent Worker Example

This example demonstrates how to run Gunicorn with HTTP/2 support using the gevent async worker.

## Features

- HTTP/2 protocol with ALPN negotiation
- Gevent-based async worker for high concurrency
- Connection multiplexing (multiple streams per connection)
- Flow control for large transfers
- SSL/TLS encryption (required for HTTP/2)

## Quick Start

### 1. Generate SSL Certificates

HTTP/2 requires TLS. Generate self-signed certificates for testing:

```bash
chmod +x generate_certs.sh
./generate_certs.sh
```

### 2. Start with Docker Compose

```bash
docker compose up -d
```

### 3. Test the Server

Using curl with HTTP/2:

```bash
# Basic request
curl -k --http2 https://localhost:8443/

# Check HTTP version
curl -k --http2 -w "HTTP Version: %{http_version}\n" https://localhost:8443/

# Test echo endpoint
curl -k --http2 -X POST -d "Hello HTTP/2" https://localhost:8443/echo

# Get server info
curl -k --http2 https://localhost:8443/info | jq
```

### 4. Run Tests

```bash
# Install test dependencies
pip install httpx[http2] pytest pytest-asyncio

# Run tests
python test_http2_gevent.py

# Or with pytest for more detail
pytest test_http2_gevent.py -v
```

## Running Locally (Without Docker)

### Prerequisites

```bash
pip install gunicorn[gevent,http2]
```

### Generate Certificates

```bash
./generate_certs.sh
```

### Start Server

```bash
gunicorn --config gunicorn_conf.py app:app
```

Or with command-line options:

```bash
gunicorn app:app \
    --bind 0.0.0.0:8443 \
    --worker-class gevent \
    --workers 4 \
    --worker-connections 1000 \
    --http-protocols h2,h1 \
    --certfile certs/server.crt \
    --keyfile certs/server.key
```

## Configuration Options

### HTTP/2 Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `http_protocols` | `['h1']` | Enable protocols: `['h2', 'h1']` for HTTP/2 |
| `http2_max_concurrent_streams` | 100 | Max streams per connection |
| `http2_initial_window_size` | 65535 | Flow control window size (bytes) |
| `http2_max_frame_size` | 16384 | Max frame size (bytes) |
| `http2_max_header_list_size` | 65536 | Max header list size (bytes) |

### Gevent Worker Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `worker_class` | `sync` | Set to `gevent` for async |
| `workers` | 1 | Number of worker processes |
| `worker_connections` | 1000 | Max clients per worker |

## Endpoints

| Path | Method | Description |
|------|--------|-------------|
| `/` | GET | Hello message |
| `/health` | GET | Health check |
| `/echo` | POST | Echo request body |
| `/info` | GET | Server/request info as JSON |
| `/large` | GET | 1MB response (test streaming) |
| `/stream` | GET | Server-sent events stream |
| `/delay?seconds=N` | GET | Delayed response |
| `/priority` | GET | HTTP/2 priority info |

## Performance Tips

1. **Worker Count**: Use `2 * CPU cores + 1` workers for I/O-bound apps
2. **Connections**: Increase `worker_connections` for high concurrency
3. **Window Size**: Larger `http2_initial_window_size` improves throughput for large transfers
4. **Streams**: Increase `http2_max_concurrent_streams` for many parallel requests

## Troubleshooting

### Certificate Issues

```bash
# Regenerate certificates
rm -rf certs/
./generate_certs.sh
```

### Connection Refused

```bash
# Check if server is running
docker compose ps

# View logs
docker compose logs -f
```

### HTTP/2 Not Negotiated

Ensure:
- SSL/TLS is configured (certfile and keyfile)
- `http_protocols` includes `'h2'`
- Client supports HTTP/2 over TLS (curl with `--http2`, not `--http2-prior-knowledge`)

## License

MIT License - See the main Gunicorn repository for details.
