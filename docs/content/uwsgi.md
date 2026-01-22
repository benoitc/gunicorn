# uWSGI Protocol

Gunicorn supports the uWSGI binary protocol, allowing it to receive requests from
nginx using the `uwsgi_pass` directive. This provides efficient communication
between nginx and Gunicorn without HTTP overhead.

!!! note
    This is the **uWSGI binary protocol**, not the uWSGI server. Gunicorn
    implements the protocol to receive requests from nginx, similar to how
    the uWSGI server would.

## Quick Start

Enable uWSGI protocol support:

```bash
gunicorn myapp:app --protocol uwsgi --bind 127.0.0.1:8000
```

Configure nginx to forward requests:

```nginx
upstream gunicorn {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name example.com;

    location / {
        uwsgi_pass gunicorn;
        include uwsgi_params;
    }
}
```

## Why Use uWSGI Protocol?

The uWSGI binary protocol offers several advantages over HTTP proxying:

- **Lower overhead** - Binary format is more compact than HTTP headers
- **Better integration** - nginx's native uwsgi module is highly optimized
- **Simpler configuration** - No need to reconstruct HTTP headers

## Configuration

### Protocol Setting

Switch from HTTP to uWSGI protocol:

```bash
gunicorn myapp:app --protocol uwsgi
```

Or in a configuration file:

```python
# gunicorn.conf.py
protocol = "uwsgi"
```

### Allowed IPs

By default, uWSGI protocol requests are only accepted from localhost
(`127.0.0.1` and `::1`). This prevents unauthorized hosts from sending
requests directly to Gunicorn.

To allow additional IPs:

```bash
gunicorn myapp:app --protocol uwsgi --uwsgi-allow-from 10.0.0.1,10.0.0.2
```

To allow all IPs (not recommended for production):

```bash
gunicorn myapp:app --protocol uwsgi --uwsgi-allow-from '*'
```

!!! warning
    Only allow IPs from trusted sources. The uWSGI protocol does not provide
    authentication, so anyone who can connect can send requests.

!!! note
    UNIX socket connections are always allowed regardless of this setting.

### Using UNIX Sockets

For better performance and security, use UNIX sockets instead of TCP:

```bash
gunicorn myapp:app --protocol uwsgi --bind unix:/run/gunicorn.sock
```

Nginx configuration:

```nginx
upstream gunicorn {
    server unix:/run/gunicorn.sock;
}

server {
    listen 80;

    location / {
        uwsgi_pass gunicorn;
        include uwsgi_params;
    }
}
```

## Nginx Configuration

### Basic Setup

Create or verify the `uwsgi_params` file exists (usually at `/etc/nginx/uwsgi_params`):

```nginx
uwsgi_param  QUERY_STRING       $query_string;
uwsgi_param  REQUEST_METHOD     $request_method;
uwsgi_param  CONTENT_TYPE       $content_type;
uwsgi_param  CONTENT_LENGTH     $content_length;

uwsgi_param  REQUEST_URI        $request_uri;
uwsgi_param  PATH_INFO          $document_uri;
uwsgi_param  DOCUMENT_ROOT      $document_root;
uwsgi_param  SERVER_PROTOCOL    $server_protocol;
uwsgi_param  REQUEST_SCHEME     $scheme;
uwsgi_param  HTTPS              $https if_not_empty;

uwsgi_param  REMOTE_ADDR        $remote_addr;
uwsgi_param  REMOTE_PORT        $remote_port;
uwsgi_param  SERVER_PORT        $server_port;
uwsgi_param  SERVER_NAME        $server_name;
```

### With SSL Termination

When nginx handles SSL and forwards to Gunicorn:

```nginx
server {
    listen 443 ssl;
    server_name example.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        uwsgi_pass gunicorn;
        include uwsgi_params;
        uwsgi_param HTTPS on;
    }
}
```

### Load Balancing

Distribute requests across multiple Gunicorn instances:

```nginx
upstream gunicorn {
    least_conn;
    server 127.0.0.1:8000;
    server 127.0.0.1:8001;
    server 127.0.0.1:8002;
}

server {
    listen 80;

    location / {
        uwsgi_pass gunicorn;
        include uwsgi_params;
    }
}
```

### Static Files

Serve static files directly from nginx:

```nginx
server {
    listen 80;

    location /static/ {
        alias /path/to/static/;
    }

    location / {
        uwsgi_pass gunicorn;
        include uwsgi_params;
    }
}
```

## Protocol Details

The uWSGI protocol uses a compact binary format:

| Bytes | Field | Description |
|-------|-------|-------------|
| 0 | modifier1 | Packet type (0 = WSGI request) |
| 1-2 | datasize | Size of vars block (little-endian) |
| 3 | modifier2 | Additional flags (usually 0) |

After the header, the vars block contains CGI-style key-value pairs:

```
[2-byte key_size][key][2-byte val_size][value]...
```

Standard CGI variables like `REQUEST_METHOD`, `PATH_INFO`, and `QUERY_STRING`
are extracted from this block to construct the WSGI environ.

## Combining with HTTP

You can run Gunicorn with both HTTP and uWSGI protocol support by running
separate instances:

```bash
# HTTP for direct access
gunicorn myapp:app --bind 127.0.0.1:8080

# uWSGI for nginx
gunicorn myapp:app --protocol uwsgi --bind 127.0.0.1:8000
```

## Troubleshooting

### ForbiddenUWSGIRequest Error

If you see "Forbidden uWSGI request from IP", the connecting IP is not in
the allowed list. Either:

1. Add the IP to `--uwsgi-allow-from`
2. Use UNIX sockets instead
3. Ensure nginx is connecting from an allowed IP

### Invalid uWSGI Header

This usually means:

1. HTTP traffic is being sent to a uWSGI endpoint
2. The packet is malformed or truncated
3. Network issues caused data corruption

Verify that nginx is using `uwsgi_pass` (not `proxy_pass`) and that the
`uwsgi_params` file is being included.

### Headers Missing

If certain headers aren't reaching your application, verify they're included
in `uwsgi_params`. Custom headers should be passed as:

```nginx
uwsgi_param HTTP_X_CUSTOM_HEADER $http_x_custom_header;
```

## See Also

- [Settings Reference](reference/settings.md#protocol) - Protocol and uWSGI settings
- [Deploy](deploy.md) - General deployment guidance
- [Design](design.md) - Worker architecture overview
