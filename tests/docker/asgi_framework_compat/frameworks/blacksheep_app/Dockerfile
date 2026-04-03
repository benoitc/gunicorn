FROM python:3.12-slim

WORKDIR /app

# Install curl for healthcheck and git for pip install from git
RUN apt-get update && apt-get install -y curl git && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 8000

# Command specified in docker-compose.yml
CMD ["gunicorn", "app:app", "-k", "asgi", "-b", "0.0.0.0:8000"]
