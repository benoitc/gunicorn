"""
URL configuration for Django compatibility testing.
"""

from django.urls import path
from views import (
    health,
    scope_view,
    echo,
    headers_view,
    status_view,
    streaming_view,
    sse_view,
    large_view,
    delay_view,
    lifespan_state_view,
    lifespan_counter_view,
)

urlpatterns = [
    path("health", health, name="health"),
    path("scope", scope_view, name="scope"),
    path("echo", echo, name="echo"),
    path("headers", headers_view, name="headers"),
    path("status/<int:code>", status_view, name="status"),
    path("streaming", streaming_view, name="streaming"),
    path("sse", sse_view, name="sse"),
    path("large", large_view, name="large"),
    path("delay", delay_view, name="delay"),
    path("lifespan/state", lifespan_state_view, name="lifespan_state"),
    path("lifespan/counter", lifespan_counter_view, name="lifespan_counter"),
]
