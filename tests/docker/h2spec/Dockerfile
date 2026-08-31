FROM python:3.14-slim

RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . /gunicorn-src/
RUN pip install --no-cache-dir "/gunicorn-src/[http2,gevent]"

EXPOSE 8443
