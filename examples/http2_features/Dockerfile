FROM python:3.12-slim

WORKDIR /app

# Install h2 for HTTP/2 support and httpx for testing
RUN pip install --no-cache-dir h2 httpx

# Copy gunicorn source and install
COPY . /app/gunicorn-src
RUN pip install /app/gunicorn-src

# Copy example app
COPY examples/http2_features /app/http2_features

# Copy SSL certificates
COPY examples/server.crt /app/certs/server.crt
COPY examples/server.key /app/certs/server.key

ENV PYTHONPATH=/app

EXPOSE 8443
CMD ["gunicorn", "http2_features.http2_app:app", "-c", "http2_features/gunicorn_conf.py"]
