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

## Stream Priority

HTTP/2 allows clients to indicate the relative priority of streams using PRIORITY frames
(RFC 7540 Section 5.3). Gunicorn tracks stream priorities and exposes them to both
WSGI and ASGI applications.

### Accessing Priority in WSGI

Priority information is available in the WSGI environ for HTTP/2 requests:

```python
def app(environ, start_response):
    # Access stream priority (HTTP/2 only)
    weight = environ.get('gunicorn.http2.priority_weight')
    depends_on = environ.get('gunicorn.http2.priority_depends_on')

    if weight is not None:
        # This is an HTTP/2 request with priority info
        # Higher weight = client considers this more important
        print(f"Request priority: weight={weight}, depends_on={depends_on}")

    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b'OK']
```

| Environ Key | Range | Default | Description |
|-------------|-------|---------|-------------|
| `gunicorn.http2.priority_weight` | 1-256 | 16 | Higher weight = more resources |
| `gunicorn.http2.priority_depends_on` | Stream ID | 0 | Parent stream (0 = root) |

### Accessing Priority in ASGI

For ASGI applications, priority is available in the scope's `extensions` dict:

```python
async def app(scope, receive, send):
    if scope["type"] == "http":
        # Check for HTTP/2 priority extension
        extensions = scope.get("extensions", {})
        priority = extensions.get("http.response.priority")

        if priority:
            weight = priority["weight"]        # 1-256
            depends_on = priority["depends_on"]  # Parent stream ID
            print(f"Request priority: weight={weight}, depends_on={depends_on}")

        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"text/plain")],
        })
        await send({
            "type": "http.response.body",
            "body": b"OK",
        })
```

| Extension Key | Field | Range | Default | Description |
|---------------|-------|-------|---------|-------------|
| `http.response.priority` | `weight` | 1-256 | 16 | Higher weight = more resources |
| `http.response.priority` | `depends_on` | Stream ID | 0 | Parent stream (0 = root) |

!!! note
    Stream priority is advisory. Applications can use it for scheduling decisions,
    but Gunicorn does not enforce priority-based request ordering. Priority
    information is only present for HTTP/2 requests.

## Response Trailers

HTTP/2 supports trailing headers (trailers) sent after the response body.
This is commonly used for gRPC status codes, checksums, and timing information.

### WSGI Applications

For WSGI applications, use the `gunicorn.http2.send_trailers` callback in the environ:

```python
def app(environ, start_response):
    # Get trailer callback (HTTP/2 only)
    send_trailers = environ.get('gunicorn.http2.send_trailers')

    # Announce trailers in response headers
    headers = [
        ('Content-Type', 'application/grpc'),
        ('Trailer', 'grpc-status, grpc-message'),
    ]
    start_response('200 OK', headers)

    # Yield response body
    yield b'response data'

    # Send trailers after body (if available)
    if send_trailers:
        send_trailers([
            ('grpc-status', '0'),
            ('grpc-message', 'OK'),
        ])
```

### ASGI Applications

For ASGI applications, use the `http.response.trailers` extension:

```python
async def app(scope, receive, send):
    # Send response with trailers flag
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [
            (b"content-type", b"application/grpc"),
            (b"trailer", b"grpc-status, grpc-message"),
        ],
    })

    # Send body
    await send({
        "type": "http.response.body",
        "body": b"response data",
        "more_body": False,
    })

    # Send trailers (HTTP/2 only)
    if "http.response.trailers" in scope.get("extensions", {}):
        await send({
            "type": "http.response.trailers",
            "headers": [
                (b"grpc-status", b"0"),
                (b"grpc-message", b"OK"),
            ],
        })
```

### Trailer Rules (RFC 7540)

- Trailers MUST NOT include pseudo-headers (`:status`, `:path`, etc.)
- Announce trailers using the `Trailer` response header
- Trailers are only available in HTTP/2 (HTTP/1.1 chunked encoding not supported)

### Common Use Cases

| Use Case | Trailer Headers |
|----------|-----------------|
| gRPC | `grpc-status`, `grpc-message` |
| Checksums | `Content-MD5`, `Digest` |
| Timing | `Server-Timing` |
| Signatures | `Signature` |

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

## Complete Example

A complete HTTP/2 example demonstrating priority and trailers is available in the
`examples/http2_features/` directory. This includes:

- **http2_app.py**: ASGI application showing priority access and trailer sending
- **test_http2.py**: Test script verifying HTTP/2 features
- **Dockerfile** and **docker-compose.yml**: Docker setup for testing

To run the example:

```bash
cd examples/http2_features
docker compose up --build

# In another terminal:
docker compose exec http2-features python /app/http2_features/test_http2.py
```

The example demonstrates:

1. **Priority access**: Reading `http.response.priority` extension in ASGI scope
2. **Response trailers**: Sending `http.response.trailers` messages
3. **Combined features**: Using both priority and trailers in one response

## RFC Compliance

Gunicorn's HTTP/2 implementation is built on the [h2 library](https://github.com/python-hyper/h2)
and complies with the following specifications:

| Feature | RFC | Status | Notes |
|---------|-----|--------|-------|
| HTTP/2 Protocol | [RFC 7540](https://tools.ietf.org/html/rfc7540) | Compliant | Core protocol support |
| HTTP/2 Semantics | [RFC 9113](https://tools.ietf.org/html/rfc9113) | Compliant | Updated HTTP/2 spec |
| HPACK Compression | [RFC 7541](https://tools.ietf.org/html/rfc7541) | Compliant | Via h2 library |
| Stream State Machine | RFC 7540 Section 5.1 | Compliant | Full state transitions |
| Flow Control | RFC 7540 Section 6.9 | Compliant | Stream and connection level |
| Stream Priority | RFC 7540 Section 5.3 | Compliant | Weight and dependency tracking |
| Frame Size Limits | RFC 7540 Section 6.2 | Compliant | Validated 16384-16777215 bytes |
| Pseudo-Headers | RFC 9113 Section 8.3 | Compliant | All required headers supported |
| `:authority` Handling | RFC 9113 Section 8.3.1 | Compliant | Takes precedence over Host |
| Response Trailers | RFC 9110 Section 6.5 | Compliant | Pseudo-headers forbidden |
| GOAWAY Handling | RFC 7540 Section 6.8 | Compliant | Graceful shutdown |
| RST_STREAM Handling | RFC 7540 Section 6.4 | Compliant | Stream reset |
| Early Hints | [RFC 8297](https://tools.ietf.org/html/rfc8297) | Compliant | 103 informational responses |
| Server Push | RFC 7540 Section 6.6 | Not Implemented | Optional feature, rarely used |

!!! note
    Server Push (PUSH_PROMISE) is not implemented. This is an optional HTTP/2 feature that is
    being deprecated in HTTP/3 and is rarely used in practice.

## Security Considerations

HTTP/2 introduces new attack vectors compared to HTTP/1.1. Gunicorn includes several
protections against known vulnerabilities.

### Built-in Protections

| Attack | Protection | Setting |
|--------|------------|---------|
| Stream Multiplexing Abuse | Limit concurrent streams | `http2_max_concurrent_streams` (default: 100) |
| HPACK Bomb | Header size limits | `http2_max_header_list_size` (default: 65536) |
| Large Frame Attack | Frame size limits | `http2_max_frame_size` (validated: 16384-16777215) |
| Resource Exhaustion | Flow control windows | `http2_initial_window_size` (default: 65535) |
| Slow Read (Slowloris) | Connection timeouts | `timeout` and `keepalive` settings |

### Recommended Security Settings

```python
# gunicorn.conf.py - Security-hardened HTTP/2 configuration

# Limit concurrent streams to prevent resource exhaustion
http2_max_concurrent_streams = 100

# Limit header size to prevent HPACK bomb attacks
http2_max_header_list_size = 65536  # 64KB

# Standard frame size (RFC minimum)
http2_max_frame_size = 16384

# Reasonable flow control window
http2_initial_window_size = 65535  # 64KB

# Connection timeouts to prevent slow attacks
timeout = 30
keepalive = 120
graceful_timeout = 30

# Limit request sizes
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190
```

### Additional Recommendations

1. **Use a reverse proxy**: Deploy behind nginx, HAProxy, or a cloud load balancer
   for additional DDoS protection and rate limiting.

2. **Enable rate limiting**: Use your reverse proxy to limit requests per client.

3. **Monitor connections**: Watch for clients opening many streams or holding
   connections open without sending data.

4. **Keep dependencies updated**: Regularly update the `h2` library for security fixes.

For more information on HTTP/2 security vulnerabilities, see:

- [Imperva HTTP/2 Vulnerability Report](https://www.imperva.com/docs/Imperva_HII_HTTP2.pdf)
- [NGINX HTTP/2 Security Advisory](https://www.nginx.com/blog/the-imperva-http2-vulnerability-report-and-nginx/)

## Compliance Testing

### h2spec

[h2spec](https://github.com/summerwind/h2spec) is the standard conformance testing tool
for HTTP/2 implementations. It tests compliance with RFC 7540 and RFC 7541.

```bash
# Install h2spec
# macOS
brew install h2spec

# Linux (download from releases)
curl -L https://github.com/summerwind/h2spec/releases/download/v2.6.0/h2spec_linux_amd64.tar.gz | tar xz

# Run against your server
h2spec -h localhost -p 8443 -t -k

# Options:
#   -t    Use TLS
#   -k    Skip certificate verification
#   -S    Strict mode (test SHOULD requirements)
#   -v    Verbose output
#   -j    Generate JUnit report
```

Example output:
```
Generic tests for HTTP/2 server
  1. Starting HTTP/2
    ✓ Sends a client connection preface
    ...

Hypertext Transfer Protocol Version 2 (HTTP/2)
  3. Starting HTTP/2
    3.5. HTTP/2 Connection Preface
      ✓ Sends invalid connection preface
      ...

94 tests, 94 passed, 0 skipped, 0 failed
```

### nghttp2 Tools

[nghttp2](https://nghttp2.org/) provides useful debugging tools:

```bash
# Install nghttp2
# macOS
brew install nghttp2

# Linux
apt-get install nghttp2-client

# Test HTTP/2 connection
nghttp -v https://localhost:8443/

# Benchmark with h2load
h2load -n 1000 -c 10 https://localhost:8443/
```

### Online Testing

For public servers, you can use online tools:

- [KeyCDN HTTP/2 Test](https://tools.keycdn.com/http2-test)
- [HTTP/2 Check](https://http.dev/2/test)

## See Also

- [Settings Reference](reference/settings.md#http2_max_concurrent_streams) - All HTTP/2 settings
- [ASGI Worker](asgi.md) - ASGI worker with HTTP/2 support
- [Deploy](deploy.md) - General deployment guidance
- [SSL Configuration](deploy.md#using-ssl) - SSL/TLS setup
