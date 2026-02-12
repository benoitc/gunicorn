FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install gunicorn from source
COPY . /gunicorn-src/
RUN pip install --no-cache-dir /gunicorn-src/

# Copy test app
COPY tests/docker/dirty_ttin_ttou/app.py /app/
COPY tests/docker/dirty_ttin_ttou/gunicorn_conf.py /app/

CMD ["gunicorn", "-c", "gunicorn_conf.py", "app:app"]
