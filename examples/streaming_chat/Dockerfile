FROM python:3.12-slim

WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir \
    fastapi \
    pydantic

# Copy gunicorn source
COPY . /app/gunicorn-src
RUN pip install /app/gunicorn-src

# Copy app
COPY examples/streaming_chat /app/streaming_chat

ENV PYTHONPATH=/app

EXPOSE 8000
CMD ["gunicorn", "streaming_chat.main:app", "-c", "streaming_chat/gunicorn_conf.py"]
