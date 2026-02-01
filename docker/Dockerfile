FROM python:3.12-slim

LABEL org.opencontainers.image.source=https://github.com/benoitc/gunicorn
LABEL org.opencontainers.image.description="Gunicorn Python WSGI HTTP Server"
LABEL org.opencontainers.image.licenses=MIT

# Create non-root user
RUN useradd --create-home --shell /bin/bash gunicorn

WORKDIR /app

# Install gunicorn from source
COPY pyproject.toml README.md LICENSE ./
COPY gunicorn/ ./gunicorn/
RUN pip install --no-cache-dir .

# Copy entrypoint script
COPY docker/docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Configuration via environment:
#   GUNICORN_BIND    - full bind address (default: 0.0.0.0:8000)
#   GUNICORN_HOST    - bind host (default: 0.0.0.0)
#   GUNICORN_PORT    - bind port (default: 8000)
#   GUNICORN_WORKERS - number of workers (default: 2 * CPU + 1)
#   GUNICORN_ARGS    - additional arguments (e.g., "--timeout 120")

USER gunicorn

EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["--help"]
