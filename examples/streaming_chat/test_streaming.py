"""Integration tests for the streaming chat example."""

import json
import os
import requests


def test_health_endpoint():
    """Test the health check endpoint."""
    base_url = os.environ.get("STREAMING_CHAT_URL", "http://127.0.0.1:8000")
    response = requests.get(f"{base_url}/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    print("Health check: OK")


def test_streaming_chat():
    """Test that chat endpoint streams tokens via SSE."""
    base_url = os.environ.get("STREAMING_CHAT_URL", "http://127.0.0.1:8000")

    response = requests.post(
        f"{base_url}/chat",
        json={"prompt": "hello"},
        stream=True,
        headers={"Accept": "text/event-stream"}
    )
    assert response.status_code == 200
    assert response.headers.get("content-type") == "text/event-stream; charset=utf-8"

    tokens = []
    for line in response.iter_lines(decode_unicode=True):
        if line.startswith("data: "):
            data = line[6:]
            if data == "[DONE]":
                break
            parsed = json.loads(data)
            tokens.append(parsed["token"])

    # Verify we got multiple tokens (streaming worked)
    assert len(tokens) > 1, f"Expected multiple tokens, got {len(tokens)}"

    # Verify tokens form a coherent response
    full_response = "".join(tokens)
    assert len(full_response) > 10, "Response too short"
    assert "Hello" in full_response or "hello" in full_response.lower()

    print(f"Streaming chat: OK (received {len(tokens)} tokens)")


def test_sync_chat():
    """Test the non-streaming chat endpoint."""
    base_url = os.environ.get("STREAMING_CHAT_URL", "http://127.0.0.1:8000")

    response = requests.post(
        f"{base_url}/chat/sync",
        json={"prompt": "hello"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "response" in data
    assert len(data["response"]) > 10

    print("Sync chat: OK")


def test_thinking_mode():
    """Test streaming with thinking phase enabled."""
    base_url = os.environ.get("STREAMING_CHAT_URL", "http://127.0.0.1:8000")

    response = requests.post(
        f"{base_url}/chat",
        json={"prompt": "hello", "thinking": True},
        stream=True
    )
    assert response.status_code == 200

    tokens = []
    for line in response.iter_lines(decode_unicode=True):
        if line.startswith("data: "):
            data = line[6:]
            if data == "[DONE]":
                break
            parsed = json.loads(data)
            tokens.append(parsed["token"])

    full_response = "".join(tokens)
    assert "[thinking" in full_response, "Thinking phase not present"
    assert "...]" in full_response or "..]\n" in full_response.replace(".", ""), \
        "Thinking dots not present"

    print("Thinking mode: OK")


def test_different_prompts():
    """Test that different prompts get different responses."""
    base_url = os.environ.get("STREAMING_CHAT_URL", "http://127.0.0.1:8000")

    prompts = ["hello", "explain dirty workers", "how does streaming work?"]
    responses = []

    for prompt in prompts:
        response = requests.post(
            f"{base_url}/chat/sync",
            json={"prompt": prompt}
        )
        assert response.status_code == 200
        responses.append(response.json()["response"])

    # Verify responses are different
    assert len(set(responses)) == len(responses), \
        "Expected different responses for different prompts"

    print("Different prompts: OK")


def test_sse_format():
    """Test that SSE format is correct."""
    base_url = os.environ.get("STREAMING_CHAT_URL", "http://127.0.0.1:8000")

    response = requests.post(
        f"{base_url}/chat",
        json={"prompt": "hello"},
        stream=True
    )

    raw_lines = []
    for line in response.iter_lines(decode_unicode=True):
        raw_lines.append(line)

    # Check SSE format: lines should be "data: ..." or empty
    for line in raw_lines:
        assert line == "" or line.startswith("data: "), \
            f"Invalid SSE line: {line}"

    # Should end with [DONE]
    data_lines = [line for line in raw_lines if line.startswith("data: ")]
    assert data_lines[-1] == "data: [DONE]", "Missing [DONE] terminator"

    print("SSE format: OK")


if __name__ == "__main__":
    test_health_endpoint()
    test_streaming_chat()
    test_sync_chat()
    test_thinking_mode()
    test_different_prompts()
    test_sse_format()
    print("\nAll tests passed!")
