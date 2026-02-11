#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

FROM python:3.12-slim

WORKDIR /app

# Copy gunicorn source
COPY . /app/gunicorn-src

# Install gunicorn and dependencies
# setproctitle is needed for process title changes
RUN pip install --no-cache-dir /app/gunicorn-src setproctitle

# Copy example files
COPY examples/dirty_example/ /app/examples/dirty_example/

WORKDIR /app

# Expose the port
EXPOSE 8000

# Default command - run the example tests
CMD ["python", "-m", "pytest", "-v", "examples/dirty_example/"]
