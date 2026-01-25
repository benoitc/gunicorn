FROM python:3.11-slim

WORKDIR /build

# Copy gunicorn source
COPY . /build/

# Install gunicorn from source
RUN pip install --no-cache-dir -e .

# Copy test app
WORKDIR /app
COPY tests/docker/asgi/app.py /app/

# Expose HTTP port
EXPOSE 8000

CMD ["gunicorn", "--worker-class", "asgi", "--bind", "0.0.0.0:8000", "app:app"]
