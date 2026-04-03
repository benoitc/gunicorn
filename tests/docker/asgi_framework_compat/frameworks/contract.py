"""
ASGI Framework Contract Definition

This module defines the required endpoints that each framework must implement
for compatibility testing with gunicorn's ASGI worker.
"""

# HTTP Endpoints Contract
HTTP_ENDPOINTS = {
    "health": {
        "path": "/health",
        "method": "GET",
        "description": "Health check endpoint",
        "expected_status": 200,
    },
    "scope": {
        "path": "/scope",
        "method": "GET",
        "description": "Return full ASGI scope as JSON",
        "expected_status": 200,
        "expected_content_type": "application/json",
    },
    "echo": {
        "path": "/echo",
        "method": "POST",
        "description": "Echo request body back",
        "expected_status": 200,
    },
    "headers": {
        "path": "/headers",
        "method": "GET",
        "description": "Return request headers as JSON",
        "expected_status": 200,
        "expected_content_type": "application/json",
    },
    "status": {
        "path": "/status/{code}",
        "method": "GET",
        "description": "Return specific HTTP status code",
    },
    "streaming": {
        "path": "/streaming",
        "method": "GET",
        "description": "Chunked streaming response",
        "expected_status": 200,
    },
    "sse": {
        "path": "/sse",
        "method": "GET",
        "description": "Server-Sent Events stream",
        "expected_status": 200,
        "expected_content_type": "text/event-stream",
    },
    "large": {
        "path": "/large",
        "method": "GET",
        "description": "Large response body (size in query param)",
        "expected_status": 200,
    },
    "delay": {
        "path": "/delay",
        "method": "GET",
        "description": "Delayed response (seconds in query param)",
        "expected_status": 200,
    },
}

# WebSocket Endpoints Contract
WEBSOCKET_ENDPOINTS = {
    "echo": {
        "path": "/ws/echo",
        "description": "Echo text messages",
    },
    "echo_binary": {
        "path": "/ws/echo-binary",
        "description": "Echo binary messages",
    },
    "scope": {
        "path": "/ws/scope",
        "description": "Send WebSocket scope on connect",
    },
    "subprotocol": {
        "path": "/ws/subprotocol",
        "description": "Subprotocol negotiation",
    },
    "close": {
        "path": "/ws/close",
        "description": "Close with specific code (code in query param)",
    },
}

# Lifespan Endpoints Contract
LIFESPAN_ENDPOINTS = {
    "state": {
        "path": "/lifespan/state",
        "method": "GET",
        "description": "Return startup state",
        "expected_status": 200,
    },
    "counter": {
        "path": "/lifespan/counter",
        "method": "GET",
        "description": "Increment and return counter (state persistence test)",
        "expected_status": 200,
    },
}

# ASGI 3.0 Scope Required Keys
ASGI_HTTP_SCOPE_REQUIRED_KEYS = [
    "type",
    "asgi",
    "http_version",
    "method",
    "scheme",
    "path",
    "query_string",
    "headers",
    "server",
]

ASGI_WEBSOCKET_SCOPE_REQUIRED_KEYS = [
    "type",
    "asgi",
    "http_version",
    "scheme",
    "path",
    "query_string",
    "headers",
    "server",
]

# Valid WebSocket close codes per RFC 6455
VALID_WEBSOCKET_CLOSE_CODES = [
    1000,  # Normal closure
    1001,  # Going away
    1002,  # Protocol error
    1003,  # Unsupported data
    1007,  # Invalid frame payload data
    1008,  # Policy violation
    1009,  # Message too big
    1010,  # Mandatory extension
    1011,  # Internal server error
]
