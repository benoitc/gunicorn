import json
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, HTMLResponse
from pydantic import BaseModel
from gunicorn.dirty.client import get_dirty_client_async


app = FastAPI(
    title="Streaming Chat Demo",
    description="Demonstrates dirty worker streaming with simulated LLM responses",
)


class ChatRequest(BaseModel):
    prompt: str
    thinking: bool = False


class ChatResponse(BaseModel):
    response: str


@app.post("/chat")
async def chat(request: ChatRequest):
    """Stream a chat response using Server-Sent Events.

    The response is streamed token-by-token, simulating LLM inference.
    Each token is sent as an SSE event with JSON data.

    Args:
        request: Chat request with prompt and optional thinking mode

    Returns:
        StreamingResponse with text/event-stream content type
    """
    client = await get_dirty_client_async()
    action = "generate_with_thinking" if request.thinking else "generate"

    async def stream():
        async for token in client.stream_async(
            "streaming_chat.chat_app:ChatApp",
            action,
            request.prompt
        ):
            data = json.dumps({"token": token})
            yield f"data: {data}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


@app.post("/chat/sync", response_model=ChatResponse)
async def chat_sync(request: ChatRequest):
    """Non-streaming chat endpoint for comparison.

    Waits for the complete response before returning.
    Useful for testing or when streaming isn't needed.

    Args:
        request: Chat request with prompt

    Returns:
        Complete response as JSON
    """
    client = await get_dirty_client_async()
    action = "generate_with_thinking" if request.thinking else "generate"

    tokens = []
    async for token in client.stream_async(
        "streaming_chat.chat_app:ChatApp",
        action,
        request.prompt
    ):
        tokens.append(token)

    return ChatResponse(response="".join(tokens))


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index():
    """Simple chat UI for testing streaming."""
    return """
<!DOCTYPE html>
<html>
<head>
    <title>Streaming Chat Demo</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background: #1a1a2e;
            color: #eee;
        }
        h1 { color: #00d9ff; }
        .chat-container {
            background: #16213e;
            border-radius: 8px;
            padding: 20px;
            margin: 20px 0;
        }
        #response {
            min-height: 100px;
            padding: 15px;
            background: #0f0f23;
            border-radius: 4px;
            white-space: pre-wrap;
            font-family: 'Monaco', 'Menlo', monospace;
            line-height: 1.6;
        }
        .input-group {
            display: flex;
            gap: 10px;
            margin-top: 15px;
        }
        input[type="text"] {
            flex: 1;
            padding: 12px;
            border: 1px solid #333;
            border-radius: 4px;
            background: #0f0f23;
            color: #eee;
            font-size: 16px;
        }
        button {
            padding: 12px 24px;
            background: #00d9ff;
            color: #000;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-weight: bold;
        }
        button:hover { background: #00b8d9; }
        button:disabled { background: #555; cursor: not-allowed; }
        .checkbox-group {
            margin-top: 10px;
        }
        label { cursor: pointer; }
        .suggestions {
            margin-top: 15px;
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }
        .suggestion {
            padding: 6px 12px;
            background: #333;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
        }
        .suggestion:hover { background: #444; }
        .cursor {
            display: inline-block;
            width: 8px;
            height: 18px;
            background: #00d9ff;
            animation: blink 1s infinite;
            vertical-align: text-bottom;
        }
        @keyframes blink {
            0%, 50% { opacity: 1; }
            51%, 100% { opacity: 0; }
        }
    </style>
</head>
<body>
    <h1>Streaming Chat Demo</h1>
    <p>This demo shows token-by-token streaming using Gunicorn's dirty workers.</p>

    <div class="chat-container">
        <div id="response"></div>
        <div class="input-group">
            <input type="text" id="prompt" placeholder="Type a message..."
                   onkeypress="if(event.key==='Enter') sendMessage()">
            <button onclick="sendMessage()" id="sendBtn">Send</button>
        </div>
        <div class="checkbox-group">
            <label>
                <input type="checkbox" id="thinking"> Show thinking phase
            </label>
        </div>
        <div class="suggestions">
            <span class="suggestion" onclick="setPrompt('hello')">hello</span>
            <span class="suggestion" onclick="setPrompt('explain dirty workers')">explain</span>
            <span class="suggestion" onclick="setPrompt('how does streaming work?')">streaming</span>
            <span class="suggestion" onclick="setPrompt('show me code')">code</span>
        </div>
    </div>

    <script>
        function setPrompt(text) {
            document.getElementById('prompt').value = text;
            sendMessage();
        }

        async function sendMessage() {
            const promptEl = document.getElementById('prompt');
            const responseEl = document.getElementById('response');
            const sendBtn = document.getElementById('sendBtn');
            const thinking = document.getElementById('thinking').checked;

            const prompt = promptEl.value.trim();
            if (!prompt) return;

            sendBtn.disabled = true;
            responseEl.innerHTML = '<span class="cursor"></span>';

            try {
                const response = await fetch('/chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({prompt, thinking})
                });

                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let text = '';

                while (true) {
                    const {done, value} = await reader.read();
                    if (done) break;

                    const chunk = decoder.decode(value);
                    const lines = chunk.split('\\n');

                    for (const line of lines) {
                        if (line.startsWith('data: ')) {
                            const data = line.slice(6);
                            if (data === '[DONE]') {
                                responseEl.textContent = text;
                            } else {
                                try {
                                    const parsed = JSON.parse(data);
                                    text += parsed.token;
                                    responseEl.innerHTML = text + '<span class="cursor"></span>';
                                } catch (e) {}
                            }
                        }
                    }
                }
            } catch (error) {
                responseEl.textContent = 'Error: ' + error.message;
            }

            sendBtn.disabled = false;
            promptEl.value = '';
            promptEl.focus();
        }

        document.getElementById('prompt').focus();
    </script>
</body>
</html>
"""
