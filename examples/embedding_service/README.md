# Embedding Service Example

A FastAPI-based text embedding service using sentence-transformers, powered by
gunicorn's dirty workers for efficient ML model management.

## Overview

This example demonstrates how to build a production-ready embedding API that:
- Keeps ML models loaded in memory across requests (dirty workers)
- Handles HTTP efficiently with async FastAPI (ASGI workers)
- Provides batch embedding for multiple texts
- Includes Docker-based deployment and testing

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│  HTTP Clients   │────►│  FastAPI (ASGI)  │────►│  DirtyWorker        │
│                 │     │  - /embed        │     │  - sentence-        │
│                 │◄────│  - /health       │◄────│    transformers     │
└─────────────────┘     └──────────────────┘     │  - Model in memory  │
                                                  └─────────────────────┘
```

**Why dirty workers?**
- ML models are expensive to load (several seconds)
- Dirty workers load the model once at startup
- HTTP workers remain lightweight and responsive
- Model stays in memory, serving many requests

## Quick Start

### With Docker (recommended)

```bash
cd examples/embedding_service
docker compose up --build
```

### Local Development

```bash
# Install dependencies
pip install sentence-transformers fastapi pydantic

# Run with gunicorn
gunicorn examples.embedding_service.main:app \
  -c examples/embedding_service/gunicorn_conf.py
```

## API Reference

### POST /embed

Generate embeddings for a list of texts.

**Request:**
```json
{
  "texts": ["Hello world", "Another sentence"]
}
```

**Response:**
```json
{
  "embeddings": [
    [0.123, -0.456, ...],
    [0.789, -0.012, ...]
  ]
}
```

**Example:**
```bash
curl -X POST http://localhost:8000/embed \
  -H "Content-Type: application/json" \
  -d '{"texts": ["Hello world"]}'
```

### GET /health

Health check endpoint.

**Response:**
```json
{"status": "ok"}
```

## Configuration

Edit `gunicorn_conf.py` to adjust:

| Setting | Default | Description |
|---------|---------|-------------|
| `workers` | 2 | Number of HTTP workers |
| `dirty_workers` | 1 | Number of ML model workers |
| `dirty_timeout` | 60 | Max seconds per inference |
| `bind` | 0.0.0.0:8000 | Listen address |

## Model

Uses [all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2):
- 384-dimensional embeddings
- Fast inference (~14K sentences/sec on GPU)
- Good quality for semantic search
- ~90MB download

To use a different model, edit `embedding_app.py`:
```python
self.model = SentenceTransformer('your-model-name')
```

## Testing

Run the integration tests:

```bash
# Start the service first
docker compose up -d

# Run tests
pip install requests numpy
python test_embedding.py
```

## Production Considerations

1. **GPU Support**: Add CUDA to the Dockerfile for faster inference
2. **Scaling**: Increase `dirty_workers` for more concurrent embeddings
3. **Caching**: Add Redis caching for repeated texts
4. **Rate Limiting**: Add FastAPI middleware for rate limiting
5. **Monitoring**: Add Prometheus metrics endpoint
