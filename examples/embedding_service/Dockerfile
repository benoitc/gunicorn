FROM python:3.12-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir \
    sentence-transformers \
    fastapi \
    pydantic

# Copy gunicorn source
COPY . /app/gunicorn-src
RUN pip install /app/gunicorn-src

# Copy app
COPY examples/embedding_service /app/embedding_service

ENV PYTHONPATH=/app

EXPOSE 8000
CMD ["gunicorn", "embedding_service.main:app", "-c", "embedding_service/gunicorn_conf.py"]
