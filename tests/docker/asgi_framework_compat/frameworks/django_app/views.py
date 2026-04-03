"""
Django views for ASGI compatibility testing.
"""

import asyncio
import json

from django.http import (
    HttpRequest,
    HttpResponse,
    JsonResponse,
    StreamingHttpResponse,
)
from django.views.decorators.csrf import csrf_exempt


def serialize_scope(scope: dict) -> dict:
    """Convert ASGI scope to JSON-serializable dict."""
    result = {}
    for key, value in scope.items():
        if key == "headers":
            result[key] = [
                [h[0].decode("latin-1"), h[1].decode("latin-1")] for h in value
            ]
        elif key == "query_string":
            result[key] = value.decode("latin-1") if value else ""
        elif key == "server":
            result[key] = list(value) if value else None
        elif key == "client":
            result[key] = list(value) if value else None
        elif key == "asgi":
            result[key] = dict(value)
        elif key in ("state", "app", "lifespan_state", "url_route", "resolver_match"):
            continue
        elif isinstance(value, bytes):
            result[key] = value.decode("latin-1")
        else:
            try:
                json.dumps(value)
                result[key] = value
            except (TypeError, ValueError):
                continue
    return result


async def health(request: HttpRequest) -> HttpResponse:
    """Health check endpoint."""
    return HttpResponse("OK")


async def scope_view(request: HttpRequest) -> JsonResponse:
    """Return full ASGI scope as JSON."""
    # Access ASGI scope from request
    scope = request.scope if hasattr(request, "scope") else {}
    scope_data = serialize_scope(scope)
    return JsonResponse(scope_data)


@csrf_exempt
async def echo(request: HttpRequest) -> HttpResponse:
    """Echo request body back."""
    body = request.body
    content_type = request.content_type or "application/octet-stream"
    return HttpResponse(body, content_type=content_type)


async def headers_view(request: HttpRequest) -> JsonResponse:
    """Return request headers as JSON."""
    headers_dict = {}
    for key, value in request.headers.items():
        headers_dict[key.lower()] = value
    return JsonResponse(headers_dict)


async def status_view(request: HttpRequest, code: int) -> HttpResponse:
    """Return specific HTTP status code."""
    return HttpResponse(f"Status: {code}", status=code)


async def streaming_view(request: HttpRequest) -> StreamingHttpResponse:
    """Chunked streaming response."""

    async def generate():
        for i in range(10):
            yield f"chunk-{i}\n"
            await asyncio.sleep(0.01)

    return StreamingHttpResponse(generate(), content_type="text/plain")


async def sse_view(request: HttpRequest) -> StreamingHttpResponse:
    """Server-Sent Events endpoint."""

    async def generate():
        for i in range(5):
            yield f"event: message\ndata: {json.dumps({'count': i})}\n\n"
            await asyncio.sleep(0.01)
        yield "event: done\ndata: {}\n\n"

    response = StreamingHttpResponse(generate(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    return response


async def large_view(request: HttpRequest) -> HttpResponse:
    """Large response body."""
    size = int(request.GET.get("size", 1024))
    # Cap at 10MB for safety
    size = min(size, 10 * 1024 * 1024)
    return HttpResponse(b"x" * size, content_type="application/octet-stream")


async def delay_view(request: HttpRequest) -> HttpResponse:
    """Delayed response."""
    seconds = float(request.GET.get("seconds", 1))
    # Cap at 30 seconds
    seconds = min(seconds, 30)
    await asyncio.sleep(seconds)
    return HttpResponse(f"Delayed {seconds} seconds")


async def lifespan_state_view(request: HttpRequest) -> JsonResponse:
    """Return lifespan startup state."""
    # Get lifespan_state from scope
    lifespan_state = getattr(request, "scope", {}).get("lifespan_state", {})
    return JsonResponse(lifespan_state)


async def lifespan_counter_view(request: HttpRequest) -> JsonResponse:
    """Increment and return counter."""
    lifespan_state = getattr(request, "scope", {}).get("lifespan_state", {})
    if lifespan_state:
        lifespan_state["counter"] = lifespan_state.get("counter", 0) + 1
    return JsonResponse({"counter": lifespan_state.get("counter", 0)})
