FROM python:3.12-slim

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Copy gunicorn source and install from local
COPY gunicorn /gunicorn-src/gunicorn
COPY pyproject.toml /gunicorn-src/
COPY README.md /gunicorn-src/
RUN pip install --no-cache-dir /gunicorn-src

# Install other requirements
COPY tests/docker/asgi_framework_compat/frameworks/fastapi_app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tests/docker/asgi_framework_compat/frameworks/fastapi_app/app.py .

EXPOSE 8000

# Command specified in docker-compose.yml
CMD ["gunicorn", "app:app", "-k", "asgi", "-b", "0.0.0.0:8000"]
