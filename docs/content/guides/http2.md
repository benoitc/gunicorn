# HTTP/2 Support

!!! warning "Beta Feature"
    HTTP/2 support is a beta feature introduced in Gunicorn 25.0.0. While it has been tested,
    the API and behavior may change in future releases. Please report any issues on
    [GitHub](https://github.com/benoitc/gunicorn/issues).

Gunicorn supports HTTP/2 (RFC 7540) for improved performance with modern clients.
HTTP/2 provides multiplexed streams, header compression, and other optimizations
over HTTP/1.1.

## Quick Start

```bash
# Install gunicorn with HTTP/2 support
pip install gunicorn[http2]

# Run with HTTP/2 enabled (requires SSL)
gunicorn myapp:app \
    --worker-class gthread \
    --threads 4 \
    --certfile server.crt \
    --keyfile server.key \
    --http-protocols h2,h1
```

## Requirements

HTTP/2 support requires:

- **SSL/TLS**: HTTP/2 uses ALPN (Application-Layer Protocol Negotiation) which
  requires an encrypted connection
- **h2 library**: Install with `pip install gunicorn[http2]` or `pip install h2`
- **Compatible worker**: gthread, gevent, eventlet, or ASGI workers

## Configuration

### Enable HTTP/2

Enable HTTP/2 by setting the `--http-protocols` option:

```bash
gunicorn myapp:app --http-protocols h2,h1
```

Or in a configuration file:

```python
# gunicorn.conf.py
http_protocols = ["h2", "h1"]
```

The order matters for ALPN negotiation - protocols are tried in order of preference.

| Protocol | Description |
|----------|-------------|
| `h2`     | HTTP/2 over TLS |
| `h1`     | HTTP/1.1 (fallback) |

!!! note
    Always include `h1` as a fallback for clients that don't support HTTP/2.

### SSL/TLS Configuration

HTTP/2 requires SSL/TLS. Configure certificates:

```bash
gunicorn myapp:app \
    --certfile /path/to/server.crt \
    --keyfile /path/to/server.key \
    --http-protocols h2,h1
```

Or in a configuration file:

```python
# gunicorn.conf.py
certfile = "/path/to/server.crt"
keyfile = "/path/to/server.key"
http_protocols = ["h2", "h1"]
```

### HTTP/2 Settings

Fine-tune HTTP/2 behavior with these settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `http2_max_concurrent_streams` | 100 | Maximum concurrent streams per connection |
| `http2_initial_window_size` | 65535 | Initial flow control window size (bytes) |
| `http2_max_frame_size` | 16384 | Maximum frame size (bytes) |
| `http2_max_header_list_size` | 65536 | Maximum header list size (bytes) |

Example configuration:

```python
# gunicorn.conf.py
http_protocols = ["h2", "h1"]
http2_max_concurrent_streams = 200
http2_initial_window_size = 1048576  # 1MB
```

## Worker Compatibility

Not all workers support HTTP/2:

| Worker | HTTP/2 Support | Notes |
|--------|----------------|-------|
| `sync` | No | Single-threaded, cannot multiplex streams |
| `gthread` | Yes | Recommended for HTTP/2 |
| `gevent` | Yes | Requires gevent |
| `eventlet` | Yes | Requires eventlet |
| `asgi` | Yes | For async frameworks |
| `tornado` | No | Tornado handles its own protocol |

If you use the sync or tornado worker with HTTP/2 enabled, Gunicorn will log a
warning and fall back to HTTP/1.1.

### Recommended: gthread Worker

For HTTP/2, the gthread worker is recommended:

```bash
gunicorn myapp:app \
    --worker-class gthread \
    --threads 4 \
    --workers 2 \
    --http-protocols h2,h1 \
    --certfile server.crt \
    --keyfile server.key
```

## HTTP 103 Early Hints

Gunicorn supports HTTP 103 Early Hints (RFC 8297), allowing servers to send
resource hints before the final response. This enables browsers to preload
CSS, JavaScript, and other assets in parallel.

### WSGI Applications

Use the `wsgi.early_hints` callback in your WSGI application:

```python
def app(environ, start_response):
    # Send early hints if available
    if 'wsgi.early_hints' in environ:
        environ['wsgi.early_hints']([
            ('Link', '</style.css>; rel=preload; as=style'),
            ('Link', '</app.js>; rel=preload; as=script'),
        ])

    # Continue with the actual response
    start_response('200 OK', [('Content-Type', 'text/html')])
    return [b'<html>...</html>']
```

### ASGI Applications

Use the `http.response.informational` message type:

```python
async def app(scope, receive, send):
    # Send early hints
    await send({
        "type": "http.response.informational",
        "status": 103,
        "headers": [
            (b"link", b"</style.css>; rel=preload; as=style"),
            (b"link", b"</app.js>; rel=preload; as=script"),
        ],
    })

    # Send the actual response
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"text/html")],
    })
    await send({
        "type": "http.response.body",
        "body": b"<html>...</html>",
    })
```

!!! note
    Early hints are only sent to HTTP/1.1+ clients. HTTP/1.0 clients silently
    ignore the callback since they don't support 1xx responses.

## Production Deployment

### With Nginx

Configure nginx to proxy HTTP/2 connections to Gunicorn:

```nginx
upstream gunicorn {
    server 127.0.0.1:8443;
    keepalive 32;
}

server {
    listen 443 ssl;
    http2 on;
    server_name example.com;

    ssl_certificate /path/to/server.crt;
    ssl_certificate_key /path/to/server.key;
    ssl_protocols TLSv1.2 TLSv1.3;

    # Forward 103 Early Hints (requires nginx 1.29+)
    location / {
        proxy_pass https://gunicorn;
        proxy_http_version 1.1;
        proxy_ssl_verify off;

        early_hints $http2;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

!!! note
    For nginx to forward 103 Early Hints from upstream, you need nginx 1.29+
    and the [`early_hints`](https://nginx.org/en/docs/http/ngx_http_core_module.html#early_hints) directive.

### Direct TLS Termination

For simpler deployments, Gunicorn can terminate TLS directly:

```python
# gunicorn.conf.py
bind = "0.0.0.0:443"
worker_class = "gthread"
threads = 4
workers = 4

# SSL
certfile = "/etc/letsencrypt/live/example.com/fullchain.pem"
keyfile = "/etc/letsencrypt/live/example.com/privkey.pem"

# HTTP/2
http_protocols = ["h2", "h1"]
http2_max_concurrent_streams = 100
```

### Recommended Settings

For production HTTP/2 deployments:

```python
# gunicorn.conf.py
worker_class = "gthread"
workers = 4
threads = 4
keepalive = 120  # HTTP/2 connections are long-lived

# SSL/TLS
certfile = "/path/to/server.crt"
keyfile = "/path/to/server.key"
ssl_version = "TLSv1_2"  # Minimum TLS 1.2 for HTTP/2

# HTTP/2
http_protocols = ["h2", "h1"]
http2_max_concurrent_streams = 100
http2_initial_window_size = 65535
```

## Troubleshooting

### HTTP/2 not negotiated

If clients fall back to HTTP/1.1:

1. Verify SSL is configured correctly
2. Check that `h2` is in `--http-protocols`
3. Ensure the h2 library is installed: `pip install h2`
4. Verify ALPN support: `openssl s_client -alpn h2 -connect host:port`

### Worker doesn't support HTTP/2

If you see "HTTP/2 is not supported by the sync worker":

```bash
# Switch to gthread worker
gunicorn myapp:app --worker-class gthread --threads 4
```

### Connection errors with large requests

Increase flow control window sizes:

```python
http2_initial_window_size = 1048576  # 1MB
http2_max_frame_size = 32768  # 32KB
```

### Too many concurrent streams

If clients report stream limit errors:

```python
http2_max_concurrent_streams = 200  # Increase from default 100
```

## Testing HTTP/2

### Using curl

```bash
# Check HTTP/2 support
curl -v --http2 https://localhost:443/

# Force HTTP/2
curl --http2-prior-knowledge https://localhost:443/
```

### Using Python

```python
import httpx

with httpx.Client(http2=True, verify=False) as client:
    response = client.get("https://localhost:8443/")
    print(f"HTTP Version: {response.http_version}")
```

## See Also

- [Settings Reference](reference/settings.md#http2_max_concurrent_streams) - All HTTP/2 settings
- [ASGI Worker](asgi.md) - ASGI worker with HTTP/2 support
- [Deploy](deploy.md) - General deployment guidance
- [SSL Configuration](deploy.md#using-ssl) - SSL/TLS setup
