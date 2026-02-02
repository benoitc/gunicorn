"""
Web Application - FastAPI app demonstrating Celery replacement.

This shows how to call dirty arbiter tasks from your web application
using the async API, which doesn't block the event loop.

Key difference from sync (Flask/gthread):
- `await client.execute_async()` is non-blocking
- A single worker can handle many concurrent requests
- True async I/O - other requests proceed while waiting for task results
"""

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from gunicorn.dirty import get_dirty_client_async
from gunicorn.dirty.errors import (
    DirtyError,
    DirtyTimeoutError,
)


# Task worker import paths (like Celery task names)
EMAIL_WORKER = "examples.celery_alternative.tasks:EmailWorker"
IMAGE_WORKER = "examples.celery_alternative.tasks:ImageWorker"
DATA_WORKER = "examples.celery_alternative.tasks:DataWorker"
SCHEDULED_WORKER = "examples.celery_alternative.tasks:ScheduledWorker"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown."""
    yield


app = FastAPI(
    title="Celery Replacement Demo",
    description="Demonstrating Gunicorn dirty arbiters as Celery replacement with async ASGI",
    lifespan=lifespan,
)


# ============================================================================
# Request/Response Models
# ============================================================================

class EmailRequest(BaseModel):
    to: str
    subject: str
    body: str
    html: bool = False


class BulkEmailRequest(BaseModel):
    recipients: list[str]
    subject: str
    body: str


class ImageResizeRequest(BaseModel):
    image_data: str = ""
    width: int = 800
    height: int = 600


class ThumbnailRequest(BaseModel):
    image_data: str = ""
    size: int = 150


class ImageBatchRequest(BaseModel):
    images: list[dict]
    operation: str = "resize"
    width: int = 800
    height: int = 600
    size: int = 150


class AggregateRequest(BaseModel):
    data: list[dict]
    group_by: str
    agg_field: str
    agg_func: str = "sum"


class ETLRequest(BaseModel):
    source_data: list[dict]
    transformations: list[dict] = []


class QueryRequest(BaseModel):
    query_key: str
    ttl: int = 300


class CleanupRequest(BaseModel):
    directory: str = "/tmp"
    max_age_days: int = 7


class SyncRequest(BaseModel):
    source: str = "default"


# ============================================================================
# Email Tasks - Like Celery email tasks
# ============================================================================

@app.post("/api/email/send")
async def send_email(data: EmailRequest):
    """
    Send a single email.

    Celery equivalent:
        send_email.delay(to, subject, body)

    With async dirty client, this doesn't block the event loop!
    Other requests can be handled while waiting for the task.
    """
    try:
        client = await get_dirty_client_async()
        result = await client.execute_async(
            EMAIL_WORKER,
            "send_email",
            to=data.to,
            subject=data.subject,
            body=data.body,
            html=data.html,
        )
        return result
    except DirtyTimeoutError:
        raise HTTPException(status_code=504, detail="Task timed out")
    except DirtyError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/email/send-bulk")
async def send_bulk_emails(data: BulkEmailRequest):
    """
    Send bulk emails with streaming progress.

    Celery equivalent:
        result = send_bulk.apply_async([recipients, subject, body])
        while not result.ready():
            print(result.info)  # Progress polling

    With dirty arbiters, progress is streamed in real-time!
    """
    async def generate():
        try:
            client = await get_dirty_client_async()
            async for progress in client.stream_async(
                EMAIL_WORKER,
                "send_bulk_emails",
                recipients=data.recipients,
                subject=data.subject,
                body=data.body,
            ):
                yield f"data: {json.dumps(progress)}\n\n"
        except DirtyError as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/email/stats")
async def email_stats():
    """Get email worker statistics."""
    try:
        client = await get_dirty_client_async()
        result = await client.execute_async(EMAIL_WORKER, "stats")
        return result
    except DirtyError as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Image Tasks - Like Celery image processing tasks
# ============================================================================

@app.post("/api/image/resize")
async def resize_image(data: ImageResizeRequest):
    """
    Resize an image.

    Celery equivalent:
        resize_image.delay(image_data, width, height)
    """
    try:
        client = await get_dirty_client_async()
        result = await client.execute_async(
            IMAGE_WORKER,
            "resize",
            image_data=data.image_data,
            width=data.width,
            height=data.height,
        )
        return result
    except DirtyError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/image/thumbnail")
async def generate_thumbnail(data: ThumbnailRequest):
    """Generate a thumbnail."""
    try:
        client = await get_dirty_client_async()
        result = await client.execute_async(
            IMAGE_WORKER,
            "generate_thumbnail",
            image_data=data.image_data,
            size=data.size,
        )
        return result
    except DirtyError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/image/process-batch")
async def process_image_batch(data: ImageBatchRequest):
    """
    Process multiple images with progress streaming.
    """
    async def generate():
        try:
            client = await get_dirty_client_async()
            async for progress in client.stream_async(
                IMAGE_WORKER,
                "process_batch",
                images=data.images,
                operation=data.operation,
                width=data.width,
                height=data.height,
                size=data.size,
            ):
                yield f"data: {json.dumps(progress)}\n\n"
        except DirtyError as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
    )


@app.get("/api/image/stats")
async def image_stats():
    """Get image worker statistics."""
    try:
        client = await get_dirty_client_async()
        result = await client.execute_async(IMAGE_WORKER, "stats")
        return result
    except DirtyError as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Data Tasks - Like Celery data processing tasks
# ============================================================================

@app.post("/api/data/aggregate")
async def aggregate_data(data: AggregateRequest):
    """
    Aggregate data.

    Celery equivalent:
        aggregate_data.delay(data, group_by, agg_field, agg_func)
    """
    try:
        client = await get_dirty_client_async()
        result = await client.execute_async(
            DATA_WORKER,
            "aggregate",
            data=data.data,
            group_by=data.group_by,
            agg_field=data.agg_field,
            agg_func=data.agg_func,
        )
        return result
    except DirtyError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/data/etl")
async def run_etl(data: ETLRequest):
    """
    Run ETL pipeline with streaming progress.

    Celery equivalent:
        chain(extract.s(), transform.s(), load.s()).apply_async()
    """
    async def generate():
        try:
            client = await get_dirty_client_async()
            async for progress in client.stream_async(
                DATA_WORKER,
                "etl_pipeline",
                source_data=data.source_data,
                transformations=data.transformations,
            ):
                yield f"data: {json.dumps(progress)}\n\n"
        except DirtyError as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
    )


@app.post("/api/data/query")
async def cached_query(data: QueryRequest):
    """Execute a cached query."""
    try:
        client = await get_dirty_client_async()
        result = await client.execute_async(
            DATA_WORKER,
            "cached_query",
            query_key=data.query_key,
            ttl=data.ttl,
        )
        return result
    except DirtyError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/data/stats")
async def data_stats():
    """Get data worker statistics."""
    try:
        client = await get_dirty_client_async()
        result = await client.execute_async(DATA_WORKER, "stats")
        return result
    except DirtyError as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Scheduled Tasks - Like Celery Beat tasks
# ============================================================================

@app.post("/api/scheduled/cleanup")
async def run_cleanup(data: CleanupRequest = CleanupRequest()):
    """Run cleanup task (normally triggered by cron)."""
    try:
        client = await get_dirty_client_async()
        result = await client.execute_async(
            SCHEDULED_WORKER,
            "cleanup_old_files",
            directory=data.directory,
            max_age_days=data.max_age_days,
        )
        return result
    except DirtyError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/scheduled/daily-report")
async def run_daily_report():
    """Generate daily report."""
    try:
        client = await get_dirty_client_async()
        result = await client.execute_async(SCHEDULED_WORKER, "generate_daily_report")
        return result
    except DirtyError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/scheduled/sync")
async def run_sync(data: SyncRequest = SyncRequest()):
    """Sync external data."""
    try:
        client = await get_dirty_client_async()
        result = await client.execute_async(
            SCHEDULED_WORKER,
            "sync_external_data",
            source=data.source,
        )
        return result
    except DirtyError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/scheduled/stats")
async def scheduled_stats():
    """Get scheduled worker statistics."""
    try:
        client = await get_dirty_client_async()
        result = await client.execute_async(SCHEDULED_WORKER, "stats")
        return result
    except DirtyError as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Health & Info Endpoints
# ============================================================================

@app.get("/")
async def index():
    """API documentation."""
    return {
        "name": "Celery Replacement Demo",
        "description": "Demonstrating Gunicorn dirty arbiters as Celery replacement (async ASGI)",
        "docs": "/docs",
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
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    try:
        client = await get_dirty_client_async()
        # Quick ping to verify workers are running
        await client.execute_async(EMAIL_WORKER, "stats")
        return {"status": "healthy", "workers": "connected"}
    except DirtyError:
        raise HTTPException(
            status_code=503,
            detail={"status": "degraded", "workers": "unavailable"}
        )
