# Dockerfile for Celery Replacement Example
#
# This demonstrates running a production-ready application with
# Gunicorn dirty arbiters replacing Celery for background tasks.
#
# Key difference from Celery deployment:
# - Celery: Needs separate web + worker containers + Redis/RabbitMQ
# - Dirty: Single container handles both HTTP and background tasks

FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy gunicorn source and install (from build context root)
COPY . /gunicorn-src
RUN pip install --no-cache-dir /gunicorn-src

# Copy example application
COPY examples/celery_alternative /app
RUN pip install --no-cache-dir flask

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/gunicorn-src
ENV GUNICORN_BIND=0.0.0.0:8000
ENV GUNICORN_WORKERS=4
ENV GUNICORN_THREADS=4
ENV DIRTY_WORKERS=9
ENV DIRTY_TIMEOUT=300
ENV LOG_LEVEL=info

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run gunicorn with dirty arbiters
CMD ["gunicorn", "-c", "gunicorn_conf.py", "app:app"]
