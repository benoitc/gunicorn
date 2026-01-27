# Streaming Chat Example

A FastAPI-based chat demo that simulates LLM token-by-token streaming, powered
by Gunicorn's dirty workers for efficient long-running operations.

## Overview

This example demonstrates how to build a streaming chat API that:
- Streams tokens word-by-word like ChatGPT (Server-Sent Events)
- Uses dirty workers for the "inference" workload
- Includes a browser-based chat UI for testing
- Requires no ML dependencies (simulated responses)

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│  Browser/curl   │────►│  FastAPI (ASGI)  │────►│  DirtyWorker        │
│  SSE stream     │     │  - /chat (SSE)   │     │  - ChatApp          │
│                 │◄────│  - /chat/sync    │◄────│  - Token generator  │
└─────────────────┘     └──────────────────┘     └─────────────────────┘
                              │
                              ▼
                        text/event-stream
                        data: {"token": "Hello"}
                        data: {"token": " "}
                        data: {"token": "world"}
                        data: [DONE]
```

**Why streaming with dirty workers?**
- Real LLM inference is slow (seconds to minutes)
- Users expect to see responses appear gradually
- Dirty workers keep the "model" loaded between requests
- HTTP workers remain responsive during streaming

## Quick Start

### With Docker (recommended)

```bash
cd examples/streaming_chat
docker compose up --build
```

Then open http://localhost:8000 in your browser.

### Local Development

```bash
# Install dependencies
pip install fastapi pydantic

# Run with gunicorn
gunicorn examples.streaming_chat.main:app \
  -c examples/streaming_chat/gunicorn_conf.py
```

## API Reference

### POST /chat

Stream a chat response using Server-Sent Events.

**Request:**
```json
{
  "prompt": "hello",
  "thinking": false
}
```

**Response:** `text/event-stream`
```
data: {"token": "Hello"}

data: {"token": "!"}

data: {"token": " "}

data: {"token": "I'm"}

...

data: [DONE]
```

**Example with curl:**
```bash
curl -N http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "hello"}'
```

### POST /chat/sync

Non-streaming version that returns the complete response.

**Request:**
```json
{
  "prompt": "hello"
}
```

**Response:**
```json
{
  "response": "Hello! I'm a simulated AI assistant..."
}
```

### GET /health

Health check endpoint.

**Response:**
```json
{"status": "ok"}
```

### GET /

Browser-based chat UI for testing.

## Configuration

Edit `gunicorn_conf.py` to adjust:

| Setting | Default | Description |
|---------|---------|-------------|
| `workers` | 2 | Number of HTTP workers |
| `dirty_workers` | 1 | Number of dirty workers |
| `dirty_timeout` | 60 | Max seconds per request |
| `bind` | 0.0.0.0:8000 | Listen address |

## Prompts

The simulated chat app responds to these keywords:

| Keyword | Response |
|---------|----------|
| `hello`, `hi`, `hey` | Greeting message |
| `explain` | Explanation of dirty workers |
| `streaming` | How streaming works |
| `code` | Example code snippet |
| (default) | Generic thoughtful response |

## Features Demonstrated

1. **Token streaming** - Word-by-word output via generators
2. **SSE protocol** - Browser-compatible event streaming
3. **Async generators** - Using `stream_async()` from dirty client
4. **Thinking mode** - Multi-phase streaming with visible "thinking"
5. **Browser UI** - Interactive chat with cursor animation

## Testing

Run the integration tests:

```bash
# Start the service first
docker compose up -d

# Run tests
pip install requests
python test_streaming.py
```

## Adapting for Real LLMs

To use a real LLM instead of simulated responses:

```python
# chat_app.py
from gunicorn.dirty.app import DirtyApp

class ChatApp(DirtyApp):
    def init(self):
        from transformers import pipeline
        self.generator = pipeline("text-generation", model="gpt2")

    def generate(self, prompt):
        for output in self.generator(prompt, max_new_tokens=100, do_sample=True):
            # Yield tokens as they're generated
            yield output["generated_text"]

    def close(self):
        del self.generator
```

Or with an API-based LLM:

```python
class ChatApp(DirtyApp):
    def init(self):
        import openai
        self.client = openai.OpenAI()

    async def generate(self, prompt):
        stream = self.client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            stream=True
        )
        for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
```

## Production Considerations

1. **Real LLM**: Replace `ChatApp` with actual model inference
2. **GPU Support**: Add CUDA to Dockerfile for faster inference
3. **Rate Limiting**: Add FastAPI middleware for rate limiting
4. **Authentication**: Add API key validation
5. **Monitoring**: Add Prometheus metrics endpoint
6. **Timeouts**: Adjust `dirty_timeout` based on max response length
