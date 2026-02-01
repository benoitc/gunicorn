"""
Web Application - Flask app demonstrating Celery replacement.

This shows how to call dirty arbiter tasks from your web application,
replacing Celery's task.delay() and task.apply_async() patterns.
"""

import json
import os
from flask import Flask, request, jsonify, Response, stream_with_context

from gunicorn.dirty import get_dirty_client
from gunicorn.dirty.errors import (
    DirtyError,
    DirtyTimeoutError,
    DirtyAppNotFoundError,
)

app = Flask(__name__)

# Task worker import paths (like Celery task names)
EMAIL_WORKER = "examples.celery_alternative.tasks:EmailWorker"
IMAGE_WORKER = "examples.celery_alternative.tasks:ImageWorker"
DATA_WORKER = "examples.celery_alternative.tasks:DataWorker"
SCHEDULED_WORKER = "examples.celery_alternative.tasks:ScheduledWorker"


def get_client():
    """Get the dirty client for calling task workers."""
    return get_dirty_client()


# ============================================================================
# Email Tasks - Like Celery email tasks
# ============================================================================

@app.route("/api/email/send", methods=["POST"])
def send_email():
    """
    Send a single email.

    Celery equivalent:
        send_email.delay(to, subject, body)

    Request:
        POST /api/email/send
        {"to": "user@example.com", "subject": "Hello", "body": "World"}
    """
    data = request.get_json()

    try:
        client = get_client()
        result = client.execute(
            EMAIL_WORKER,
            "send_email",
            to=data["to"],
            subject=data["subject"],
            body=data["body"],
            html=data.get("html", False),
        )
        return jsonify(result)
    except DirtyTimeoutError:
        return jsonify({"error": "Task timed out"}), 504
    except DirtyError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/email/send-bulk", methods=["POST"])
def send_bulk_emails():
    """
    Send bulk emails with streaming progress.

    Celery equivalent:
        result = send_bulk.apply_async([recipients, subject, body])
        while not result.ready():
            print(result.info)  # Progress polling

    With dirty arbiters, progress is streamed in real-time!

    Request:
        POST /api/email/send-bulk
        {"recipients": ["a@x.com", "b@x.com"], "subject": "Hi", "body": "Hello"}
    """
    data = request.get_json()

    def generate():
        try:
            client = get_client()
            for progress in client.stream(
                EMAIL_WORKER,
                "send_bulk_emails",
                recipients=data["recipients"],
                subject=data["subject"],
                body=data["body"],
            ):
                yield f"data: {json.dumps(progress)}\n\n"
        except DirtyError as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/email/stats")
def email_stats():
    """Get email worker statistics."""
    try:
        client = get_client()
        result = client.execute(EMAIL_WORKER, "stats")
        return jsonify(result)
    except DirtyError as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# Image Tasks - Like Celery image processing tasks
# ============================================================================

@app.route("/api/image/resize", methods=["POST"])
def resize_image():
    """
    Resize an image.

    Celery equivalent:
        resize_image.delay(image_data, width, height)

    Request:
        POST /api/image/resize
        {"image_data": "base64...", "width": 800, "height": 600}
    """
    data = request.get_json()

    # Keep image_data as string (base64 encoded) for JSON serialization
    image_data = data.get("image_data", "")

    try:
        client = get_client()
        result = client.execute(
            IMAGE_WORKER,
            "resize",
            image_data=image_data,
            width=data.get("width", 800),
            height=data.get("height", 600),
        )
        return jsonify(result)
    except DirtyError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/image/thumbnail", methods=["POST"])
def generate_thumbnail():
    """Generate a thumbnail."""
    data = request.get_json()
    image_data = data.get("image_data", "")

    try:
        client = get_client()
        result = client.execute(
            IMAGE_WORKER,
            "generate_thumbnail",
            image_data=image_data,
            size=data.get("size", 150),
        )
        return jsonify(result)
    except DirtyError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/image/process-batch", methods=["POST"])
def process_image_batch():
    """
    Process multiple images with progress streaming.

    Request:
        POST /api/image/process-batch
        {
            "images": [{"id": "img1", "data": "..."}, ...],
            "operation": "resize",
            "width": 800,
            "height": 600
        }
    """
    data = request.get_json()

    def generate():
        try:
            client = get_client()
            for progress in client.stream(
                IMAGE_WORKER,
                "process_batch",
                images=data["images"],
                operation=data.get("operation", "resize"),
                width=data.get("width", 800),
                height=data.get("height", 600),
                size=data.get("size", 150),
            ):
                yield f"data: {json.dumps(progress)}\n\n"
        except DirtyError as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
    )


@app.route("/api/image/stats")
def image_stats():
    """Get image worker statistics."""
    try:
        client = get_client()
        result = client.execute(IMAGE_WORKER, "stats")
        return jsonify(result)
    except DirtyError as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# Data Tasks - Like Celery data processing tasks
# ============================================================================

@app.route("/api/data/aggregate", methods=["POST"])
def aggregate_data():
    """
    Aggregate data.

    Celery equivalent:
        aggregate_data.delay(data, group_by, agg_field, agg_func)

    Request:
        POST /api/data/aggregate
        {
            "data": [{"category": "A", "value": 10}, ...],
            "group_by": "category",
            "agg_field": "value",
            "agg_func": "sum"
        }
    """
    data = request.get_json()

    try:
        client = get_client()
        result = client.execute(
            DATA_WORKER,
            "aggregate",
            data=data["data"],
            group_by=data["group_by"],
            agg_field=data["agg_field"],
            agg_func=data.get("agg_func", "sum"),
        )
        return jsonify(result)
    except DirtyError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/data/etl", methods=["POST"])
def run_etl():
    """
    Run ETL pipeline with streaming progress.

    Celery equivalent:
        chain(extract.s(), transform.s(), load.s()).apply_async()

    Request:
        POST /api/data/etl
        {
            "source_data": [...],
            "transformations": [
                {"name": "filter_active", "type": "filter", "field": "status", "value": "active"},
                {"name": "uppercase_name", "type": "map", "field": "name", "func": "upper"}
            ]
        }
    """
    data = request.get_json()

    def generate():
        try:
            client = get_client()
            for progress in client.stream(
                DATA_WORKER,
                "etl_pipeline",
                source_data=data["source_data"],
                transformations=data.get("transformations", []),
            ):
                yield f"data: {json.dumps(progress)}\n\n"
        except DirtyError as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
    )


@app.route("/api/data/query", methods=["POST"])
def cached_query():
    """
    Execute a cached query.

    Request:
        POST /api/data/query
        {"query_key": "sales_2024", "ttl": 300}
    """
    data = request.get_json()

    try:
        client = get_client()
        result = client.execute(
            DATA_WORKER,
            "cached_query",
            query_key=data["query_key"],
            ttl=data.get("ttl", 300),
        )
        return jsonify(result)
    except DirtyError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/data/stats")
def data_stats():
    """Get data worker statistics."""
    try:
        client = get_client()
        result = client.execute(DATA_WORKER, "stats")
        return jsonify(result)
    except DirtyError as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# Scheduled Tasks - Like Celery Beat tasks
# ============================================================================

@app.route("/api/scheduled/cleanup", methods=["POST"])
def run_cleanup():
    """
    Run cleanup task (normally triggered by cron).

    Request:
        POST /api/scheduled/cleanup
        {"directory": "/tmp/uploads", "max_age_days": 7}
    """
    data = request.get_json() or {}

    try:
        client = get_client()
        result = client.execute(
            SCHEDULED_WORKER,
            "cleanup_old_files",
            directory=data.get("directory", "/tmp"),
            max_age_days=data.get("max_age_days", 7),
        )
        return jsonify(result)
    except DirtyError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/scheduled/daily-report", methods=["POST"])
def run_daily_report():
    """Generate daily report."""
    try:
        client = get_client()
        result = client.execute(SCHEDULED_WORKER, "generate_daily_report")
        return jsonify(result)
    except DirtyError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/scheduled/sync", methods=["POST"])
def run_sync():
    """
    Sync external data.

    Request:
        POST /api/scheduled/sync
        {"source": "external_api"}
    """
    data = request.get_json() or {}

    try:
        client = get_client()
        result = client.execute(
            SCHEDULED_WORKER,
            "sync_external_data",
            source=data.get("source", "default"),
        )
        return jsonify(result)
    except DirtyError as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/scheduled/stats")
def scheduled_stats():
    """Get scheduled worker statistics."""
    try:
        client = get_client()
        result = client.execute(SCHEDULED_WORKER, "stats")
        return jsonify(result)
    except DirtyError as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# Health & Info Endpoints
# ============================================================================

@app.route("/")
def index():
    """API documentation."""
    return jsonify({
        "name": "Celery Replacement Demo",
        "description": "Demonstrating Gunicorn dirty arbiters as Celery replacement",
        "endpoints": {
            "email": {
                "POST /api/email/send": "Send single email",
                "POST /api/email/send-bulk": "Send bulk emails (streaming)",
                "GET /api/email/stats": "Email worker stats",
            },
            "image": {
                "POST /api/image/resize": "Resize image",
                "POST /api/image/thumbnail": "Generate thumbnail",
                "POST /api/image/process-batch": "Batch process (streaming)",
                "GET /api/image/stats": "Image worker stats",
            },
            "data": {
                "POST /api/data/aggregate": "Aggregate data",
                "POST /api/data/etl": "Run ETL pipeline (streaming)",
                "POST /api/data/query": "Cached query",
                "GET /api/data/stats": "Data worker stats",
            },
            "scheduled": {
                "POST /api/scheduled/cleanup": "Run cleanup",
                "POST /api/scheduled/daily-report": "Generate report",
                "POST /api/scheduled/sync": "Sync external data",
                "GET /api/scheduled/stats": "Scheduled worker stats",
            },
        },
    })


@app.route("/health")
def health():
    """Health check endpoint."""
    try:
        client = get_client()
        # Quick ping to verify workers are running
        client.execute(EMAIL_WORKER, "stats")
        return jsonify({"status": "healthy", "workers": "connected"})
    except DirtyError:
        return jsonify({"status": "degraded", "workers": "unavailable"}), 503


if __name__ == "__main__":
    app.run(debug=True, port=8000)
