# Docker Deployment

Running Gunicorn in Docker containers is the most common deployment pattern
for modern Python applications. This guide covers best practices for
containerizing Gunicorn applications.

## Official Docker Image

Gunicorn provides an official Docker image on GitHub Container Registry:

```bash
docker pull ghcr.io/benoitc/gunicorn:latest
```

### Quick Start

Mount your application directory and run:

```bash
docker run -p 8000:8000 -v $(pwd):/app ghcr.io/benoitc/gunicorn app:app
```

### Running in Background

Use `-d` (detached mode) to run the container in the background:

```bash
# Start in background
docker run -d --name myapp -p 8000:8000 -v $(pwd):/app ghcr.io/benoitc/gunicorn app:app

# View logs
docker logs myapp

# Follow logs in real-time
docker logs -f myapp

# Stop the container
docker stop myapp

# Start it again
docker start myapp

# Remove the container
docker rm myapp
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GUNICORN_BIND` | Full bind address | `0.0.0.0:8000` |
| `GUNICORN_HOST` | Bind host | `0.0.0.0` |
| `GUNICORN_PORT` | Bind port | `8000` |
| `GUNICORN_WORKERS` | Number of workers | `(2 * CPU) + 1` |
| `GUNICORN_ARGS` | Additional arguments | (none) |

### With Configuration

```bash
docker run -p 9000:9000 -v $(pwd):/app \
  -e GUNICORN_PORT=9000 \
  -e GUNICORN_WORKERS=4 \
  -e GUNICORN_ARGS="--timeout 120 --access-logfile -" \
  ghcr.io/benoitc/gunicorn app:app
```

### As Base Image (Recommended for Production)

```dockerfile
FROM ghcr.io/benoitc/gunicorn:24.1.0

# Install app dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY --chown=gunicorn:gunicorn . .

CMD ["myapp:app", "--workers", "4"]
```

### With Docker Compose

```yaml
services:
  web:
    image: ghcr.io/benoitc/gunicorn:latest
    ports:
      - "8000:8000"
    volumes:
      - ./app:/app
    command: ["myapp:app", "--workers", "4"]
```

### Available Tags

- `ghcr.io/benoitc/gunicorn:latest` - Latest release
- `ghcr.io/benoitc/gunicorn:24.1.0` - Specific version
- `ghcr.io/benoitc/gunicorn:24.1` - Minor version
- `ghcr.io/benoitc/gunicorn:24` - Major version

## Building Your Own Image

For more control, build a custom image using the patterns below.

## Basic Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Run gunicorn
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000"]
```

Build and run:

```bash
docker build -t myapp .
docker run -p 8000:8000 myapp
```

## Production Configuration

### Environment Variables

Use environment variables for configuration:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Configuration via environment
ENV GUNICORN_WORKERS=4
ENV GUNICORN_BIND=0.0.0.0:8000

CMD gunicorn app:app \
    --workers ${GUNICORN_WORKERS} \
    --bind ${GUNICORN_BIND}
```

Or use `GUNICORN_CMD_ARGS`:

```dockerfile
ENV GUNICORN_CMD_ARGS="--workers=4 --bind=0.0.0.0:8000"
CMD ["gunicorn", "app:app"]
```

### Worker Count

In containers, determine workers based on available CPU:

```python
# gunicorn.conf.py
import multiprocessing

workers = multiprocessing.cpu_count() * 2 + 1
bind = "0.0.0.0:8000"
```

Or let Kubernetes/Docker limit CPU and calculate accordingly:

```bash
# At runtime
gunicorn app:app --workers $(( 2 * $(nproc) + 1 ))
```

### Non-Root User

Run as a non-root user for security:

```dockerfile
FROM python:3.12-slim

# Create non-root user
RUN useradd --create-home appuser
WORKDIR /home/appuser/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=appuser:appuser . .

USER appuser

CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000"]
```

### Health Checks

Add a health check endpoint and Docker health check:

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1
```

## Multi-Stage Build

Reduce image size with multi-stage builds:

```dockerfile
# Build stage
FROM python:3.12 AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# Runtime stage
FROM python:3.12-slim

WORKDIR /app

# Copy wheels and install
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

COPY . .

CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000", "--workers", "4"]
```

## Docker Compose

Example `docker-compose.yml`:

```yaml
services:
  web:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgres://db:5432/myapp
    depends_on:
      - db
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 512M

  db:
    image: postgres:15
    environment:
      - POSTGRES_DB=myapp
      - POSTGRES_PASSWORD=secret
    volumes:
      - postgres_data:/var/lib/postgresql/data

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
    depends_on:
      - web

volumes:
  postgres_data:
```

## Kubernetes Deployment

Example Kubernetes deployment:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: myapp
spec:
  replicas: 3
  selector:
    matchLabels:
      app: myapp
  template:
    metadata:
      labels:
        app: myapp
    spec:
      containers:
      - name: myapp
        image: myapp:latest
        ports:
        - containerPort: 8000
        env:
        - name: GUNICORN_WORKERS
          value: "4"
        resources:
          limits:
            cpu: "1"
            memory: "512Mi"
          requests:
            cpu: "500m"
            memory: "256Mi"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: myapp
spec:
  selector:
    app: myapp
  ports:
  - port: 80
    targetPort: 8000
```

## Graceful Shutdown

Gunicorn handles `SIGTERM` gracefully by default. Configure the timeout:

```dockerfile
CMD ["gunicorn", "app:app", \
     "--bind", "0.0.0.0:8000", \
     "--graceful-timeout", "30", \
     "--timeout", "120"]
```

Match Docker's stop timeout:

```yaml
# docker-compose.yml
services:
  web:
    stop_grace_period: 30s
```

## Logging

Log to stdout/stderr for Docker log collection:

```python
# gunicorn.conf.py
accesslog = "-"
errorlog = "-"
loglevel = "info"
```

Use JSON logging for log aggregation:

```python
# gunicorn.conf.py
import json
import datetime

class JsonFormatter:
    def format(self, record):
        return json.dumps({
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
        })

logconfig_dict = {
    "version": 1,
    "formatters": {
        "json": {"()": JsonFormatter}
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "stream": "ext://sys.stdout"
        }
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO"
    }
}
```

## Troubleshooting

### Worker Timeout

If workers are killed with `[CRITICAL] WORKER TIMEOUT`, increase the timeout:

```bash
gunicorn app:app --timeout 120
```

Or investigate slow requests in your application.

### Out of Memory

If containers are OOM-killed:

1. Reduce worker count
2. Use `--max-requests` to restart workers periodically
3. Increase container memory limits

```bash
gunicorn app:app --workers 2 --max-requests 1000 --max-requests-jitter 100
```

### Connection Reset

If you see connection resets, ensure:

1. Load balancer health checks match your `/health` endpoint
2. Graceful timeout is sufficient for in-flight requests
3. Keepalive settings match between Gunicorn and upstream proxy

## See Also

- [Deploy](../deploy.md) - General deployment patterns
- [Settings](../reference/settings.md) - All configuration options
