FROM python:3.12-slim

WORKDIR /app

# Copy gunicorn source
COPY . /app/gunicorn-src

# Install gunicorn and test dependencies
# setproctitle is needed for process title changes (master, dirty-arbiter, etc.)
RUN pip install --no-cache-dir /app/gunicorn-src pytest requests setproctitle

# Copy test app files
COPY tests/docker/per_app_allocation/app.py /app/
COPY tests/docker/per_app_allocation/gunicorn_conf.py /app/

# Install procps for process inspection and curl for healthcheck
RUN apt-get update && apt-get install -y procps curl && rm -rf /var/lib/apt/lists/*

# Default command - run gunicorn
CMD ["gunicorn", "app:application", "-c", "gunicorn_conf.py"]
