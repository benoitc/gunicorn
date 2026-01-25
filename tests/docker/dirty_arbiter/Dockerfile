FROM python:3.12-slim

WORKDIR /app

# Copy gunicorn source
COPY . /app/gunicorn-src

# Install gunicorn and test dependencies
# setproctitle is needed for process title changes (master, dirty-arbiter, etc.)
RUN pip install --no-cache-dir /app/gunicorn-src pytest requests setproctitle

# Copy test app files
COPY tests/docker/dirty_arbiter/app.py /app/
COPY tests/docker/dirty_arbiter/gunicorn_conf.py /app/

# Install procps for process inspection
RUN apt-get update && apt-get install -y procps && rm -rf /var/lib/apt/lists/*

# Default command - run gunicorn
CMD ["gunicorn", "app:application", "-c", "gunicorn_conf.py"]
