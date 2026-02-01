"""
Task Workers - Celery Replacement using Gunicorn Dirty Arbiters

This module demonstrates how to replace Celery with Gunicorn's dirty arbiter
feature for background task processing. Key benefits:

1. No external broker (Redis/RabbitMQ) needed - uses Unix sockets
2. Stateful workers - maintain connections, models, caches across requests
3. Integrated with your WSGI/ASGI app - no separate process management
4. Streaming support for progress reporting
5. Per-task-type worker allocation for memory optimization

Comparison with Celery:
- Celery: @app.task decorator -> Dirty: DirtyApp class with methods
- Celery: task.delay() -> Dirty: client.execute()
- Celery: task.apply_async() -> Dirty: client.execute() with timeout
- Celery: task progress -> Dirty: client.stream() with generators
"""

import hashlib
import json
import os
import random
import smtplib
import time
from datetime import datetime
from email.mime.text import MIMEText
from typing import Any, Generator

from gunicorn.dirty.app import DirtyApp


class EmailWorker(DirtyApp):
    """
    Email task worker - like Celery's @app.task for email sending.

    Maintains SMTP connection pool across requests for efficiency.
    In Celery, you'd create a new connection per task or manage it manually.
    """

    # Limit to 2 workers since email sending is I/O bound
    workers = 2

    def __init__(self):
        self.smtp_connection = None
        self.emails_sent = 0
        self.last_connected = None

    def init(self):
        """Called once when worker starts - establish SMTP connection."""
        self._connect_smtp()

    def _connect_smtp(self):
        """Establish SMTP connection (simulated for demo)."""
        # In production, connect to real SMTP server:
        # self.smtp_connection = smtplib.SMTP('smtp.example.com', 587)
        # self.smtp_connection.starttls()
        # self.smtp_connection.login(user, password)
        self.last_connected = datetime.now().isoformat()
        self.smtp_connection = "connected"  # Simulated

    def __call__(self, action: str, *args, **kwargs) -> Any:
        """Dispatch to action methods."""
        method = getattr(self, action, None)
        if method is None or action.startswith('_'):
            raise ValueError(f"Unknown action: {action}")
        return method(*args, **kwargs)

    def send_email(self, to: str, subject: str, body: str,
                   html: bool = False) -> dict:
        """
        Send a single email.

        Equivalent to Celery:
            @app.task
            def send_email(to, subject, body):
                ...
        """
        # Simulate email sending delay
        time.sleep(random.uniform(0.1, 0.3))

        self.emails_sent += 1

        return {
            "status": "sent",
            "to": to,
            "subject": subject,
            "message_id": f"msg-{self.emails_sent}-{int(time.time())}",
            "timestamp": datetime.now().isoformat(),
        }

    def send_bulk_emails(self, recipients: list, subject: str,
                         body: str) -> Generator[dict, None, None]:
        """
        Send bulk emails with progress streaming.

        This is where dirty arbiters shine over Celery - real-time
        progress without polling or WebSockets.

        Equivalent to Celery:
            @app.task(bind=True)
            def send_bulk(self, recipients, subject, body):
                for i, to in enumerate(recipients):
                    send_email(to, subject, body)
                    self.update_state(state='PROGRESS',
                                      meta={'current': i, 'total': len(recipients)})
        """
        total = len(recipients)
        sent = 0
        failed = 0

        for i, to in enumerate(recipients):
            try:
                result = self.send_email(to, subject, body)
                sent += 1
                yield {
                    "type": "progress",
                    "current": i + 1,
                    "total": total,
                    "percent": int((i + 1) / total * 100),
                    "last_sent": to,
                    "status": "sent",
                }
            except Exception as e:
                failed += 1
                yield {
                    "type": "progress",
                    "current": i + 1,
                    "total": total,
                    "percent": int((i + 1) / total * 100),
                    "last_sent": to,
                    "status": "failed",
                    "error": str(e),
                }

        # Final summary
        yield {
            "type": "complete",
            "total": total,
            "sent": sent,
            "failed": failed,
        }

    def stats(self) -> dict:
        """Get worker statistics."""
        return {
            "emails_sent": self.emails_sent,
            "smtp_connected": self.smtp_connection is not None,
            "last_connected": self.last_connected,
            "worker_pid": os.getpid(),
        }

    def close(self):
        """Cleanup on shutdown."""
        if self.smtp_connection and self.smtp_connection != "connected":
            self.smtp_connection.quit()


class ImageWorker(DirtyApp):
    """
    Image processing worker - demonstrates CPU-intensive tasks.

    Like Celery tasks for image resizing, thumbnails, watermarks.
    Keeps image processing libraries loaded in memory.
    """

    # Limit to 2 workers - image processing is memory intensive
    workers = 2

    def __init__(self):
        self.pil_available = False
        self.images_processed = 0

    def init(self):
        """Load image processing libraries once at startup."""
        try:
            # Try to import PIL - optional dependency
            from PIL import Image
            self.pil_available = True
        except ImportError:
            self.pil_available = False

    def __call__(self, action: str, *args, **kwargs) -> Any:
        method = getattr(self, action, None)
        if method is None or action.startswith('_'):
            raise ValueError(f"Unknown action: {action}")
        return method(*args, **kwargs)

    def resize(self, image_data: str, width: int, height: int) -> dict:
        """
        Resize an image.

        Equivalent to Celery:
            @app.task
            def resize_image(image_path, width, height):
                img = Image.open(image_path)
                img.thumbnail((width, height))
                img.save(output_path)
        """
        # Simulate image processing
        time.sleep(random.uniform(0.2, 0.5))

        self.images_processed += 1

        # Create a fake "processed" result
        # In production, image_data would be base64 decoded
        data_size = len(image_data) if isinstance(image_data, str) else len(image_data)
        result_hash = hashlib.md5(
            f"{data_size}{width}{height}".encode()
        ).hexdigest()[:16]

        return {
            "status": "resized",
            "original_size": data_size,
            "target_dimensions": f"{width}x{height}",
            "result_id": f"img-{result_hash}",
            "pil_used": self.pil_available,
        }

    def generate_thumbnail(self, image_data: str, size: int = 150) -> dict:
        """Generate a thumbnail."""
        return self.resize(image_data, size, size)

    def process_batch(self, images: list, operation: str,
                      **params) -> Generator[dict, None, None]:
        """
        Process multiple images with progress streaming.
        """
        total = len(images)

        for i, img_info in enumerate(images):
            try:
                # Simulate fetching image data
                image_data = img_info.get("data", b"fake_image_data")

                if operation == "resize":
                    result = self.resize(
                        image_data,
                        params.get("width", 800),
                        params.get("height", 600)
                    )
                elif operation == "thumbnail":
                    result = self.generate_thumbnail(
                        image_data,
                        params.get("size", 150)
                    )
                else:
                    result = {"error": f"Unknown operation: {operation}"}

                yield {
                    "type": "progress",
                    "current": i + 1,
                    "total": total,
                    "percent": int((i + 1) / total * 100),
                    "image_id": img_info.get("id", f"img-{i}"),
                    "result": result,
                }
            except Exception as e:
                yield {
                    "type": "error",
                    "current": i + 1,
                    "total": total,
                    "image_id": img_info.get("id", f"img-{i}"),
                    "error": str(e),
                }

        yield {
            "type": "complete",
            "total": total,
            "processed": self.images_processed,
        }

    def stats(self) -> dict:
        return {
            "images_processed": self.images_processed,
            "pil_available": self.pil_available,
            "worker_pid": os.getpid(),
        }


class DataWorker(DirtyApp):
    """
    Data processing worker - demonstrates stateful data operations.

    Maintains database connections, caches, and processing state.
    Perfect for ETL tasks, report generation, data aggregation.
    """

    # More workers for data tasks - they're often parallelizable
    workers = 4

    def __init__(self):
        self.cache = {}
        self.db_connection = None
        self.tasks_completed = 0

    def init(self):
        """Initialize database connection and cache."""
        # In production: self.db_connection = create_engine(DATABASE_URL)
        self.db_connection = "connected"
        self.cache = {}

    def __call__(self, action: str, *args, **kwargs) -> Any:
        method = getattr(self, action, None)
        if method is None or action.startswith('_'):
            raise ValueError(f"Unknown action: {action}")
        return method(*args, **kwargs)

    def aggregate(self, data: list, group_by: str,
                  agg_field: str, agg_func: str = "sum") -> dict:
        """
        Aggregate data - like a Celery task for report generation.

        Equivalent to Celery:
            @app.task
            def aggregate_sales(data, group_by, agg_field):
                df = pd.DataFrame(data)
                return df.groupby(group_by)[agg_field].sum().to_dict()
        """
        # Simulate aggregation
        time.sleep(random.uniform(0.1, 0.3))

        result = {}
        for item in data:
            key = item.get(group_by, "unknown")
            value = item.get(agg_field, 0)

            if key not in result:
                if agg_func in ("sum", "count"):
                    result[key] = 0
                else:
                    result[key] = []

            if agg_func == "sum":
                result[key] += value
            elif agg_func == "count":
                result[key] += 1
            elif agg_func == "list":
                result[key].append(value)

        self.tasks_completed += 1

        return {
            "status": "completed",
            "group_by": group_by,
            "agg_func": agg_func,
            "result": result,
            "record_count": len(data),
        }

    def etl_pipeline(self, source_data: list,
                     transformations: list) -> Generator[dict, None, None]:
        """
        Run an ETL pipeline with progress streaming.

        This replaces Celery chains/chords for multi-step processing:
            chain(extract.s(), transform.s(), load.s())
        """
        total_steps = len(transformations) + 2  # +2 for extract and load
        current_step = 0
        data = source_data

        # Extract phase
        yield {
            "type": "progress",
            "phase": "extract",
            "step": current_step + 1,
            "total_steps": total_steps,
            "message": f"Extracting {len(data)} records",
        }
        time.sleep(0.2)  # Simulate extraction
        current_step += 1

        # Transform phases
        for i, transform in enumerate(transformations):
            transform_name = transform.get("name", f"transform_{i}")
            transform_type = transform.get("type", "passthrough")

            yield {
                "type": "progress",
                "phase": "transform",
                "step": current_step + 1,
                "total_steps": total_steps,
                "message": f"Applying {transform_name}",
            }

            # Apply transformation
            if transform_type == "filter":
                field = transform.get("field")
                value = transform.get("value")
                data = [d for d in data if d.get(field) == value]
            elif transform_type == "map":
                field = transform.get("field")
                func = transform.get("func", "upper")
                for d in data:
                    if field in d and isinstance(d[field], str):
                        if func == "upper":
                            d[field] = d[field].upper()
                        elif func == "lower":
                            d[field] = d[field].lower()

            time.sleep(0.2)  # Simulate transformation
            current_step += 1

        # Load phase
        yield {
            "type": "progress",
            "phase": "load",
            "step": current_step + 1,
            "total_steps": total_steps,
            "message": f"Loading {len(data)} records",
        }
        time.sleep(0.2)  # Simulate loading

        self.tasks_completed += 1

        # Final result
        yield {
            "type": "complete",
            "records_processed": len(source_data),
            "records_output": len(data),
            "transformations_applied": len(transformations),
        }

    def cached_query(self, query_key: str, ttl: int = 300) -> dict:
        """
        Execute a cached query - demonstrates stateful caching.

        Unlike Celery where you'd use Redis for caching,
        the dirty worker maintains its own in-memory cache.
        """
        now = time.time()

        if query_key in self.cache:
            cached = self.cache[query_key]
            if now - cached["timestamp"] < ttl:
                return {
                    "status": "cache_hit",
                    "data": cached["data"],
                    "cached_at": cached["timestamp"],
                    "age_seconds": int(now - cached["timestamp"]),
                }

        # Simulate query execution
        time.sleep(random.uniform(0.2, 0.4))

        # Generate fake result
        result_data = {
            "query": query_key,
            "rows": random.randint(10, 100),
            "computed_at": now,
        }

        self.cache[query_key] = {
            "data": result_data,
            "timestamp": now,
        }

        return {
            "status": "cache_miss",
            "data": result_data,
            "cached_at": now,
        }

    def stats(self) -> dict:
        return {
            "tasks_completed": self.tasks_completed,
            "cache_size": len(self.cache),
            "db_connected": self.db_connection is not None,
            "worker_pid": os.getpid(),
        }

    def close(self):
        """Cleanup on shutdown."""
        self.cache.clear()
        if self.db_connection and self.db_connection != "connected":
            self.db_connection.close()


class ScheduledWorker(DirtyApp):
    """
    Scheduled task worker - for periodic/scheduled tasks.

    While dirty arbiters don't have built-in scheduling like Celery Beat,
    you can call these from a simple cron job or scheduler.
    """

    workers = 1  # Single worker for scheduled tasks

    def __init__(self):
        self.last_runs = {}
        self.run_counts = {}

    def __call__(self, action: str, *args, **kwargs) -> Any:
        method = getattr(self, action, None)
        if method is None or action.startswith('_'):
            raise ValueError(f"Unknown action: {action}")

        # Track runs
        self.last_runs[action] = datetime.now().isoformat()
        self.run_counts[action] = self.run_counts.get(action, 0) + 1

        return method(*args, **kwargs)

    def cleanup_old_files(self, directory: str, max_age_days: int = 7) -> dict:
        """
        Cleanup old files - like a Celery periodic task.

        Equivalent to Celery Beat:
            @app.task
            def cleanup():
                ...

            app.conf.beat_schedule = {
                'cleanup-every-hour': {
                    'task': 'tasks.cleanup',
                    'schedule': 3600.0,
                },
            }
        """
        # Simulate cleanup
        time.sleep(0.3)

        files_deleted = random.randint(0, 10)

        return {
            "status": "completed",
            "directory": directory,
            "files_deleted": files_deleted,
            "space_freed_mb": files_deleted * random.uniform(0.1, 5.0),
        }

    def generate_daily_report(self) -> dict:
        """Generate daily report."""
        time.sleep(0.5)

        return {
            "status": "completed",
            "report_date": datetime.now().strftime("%Y-%m-%d"),
            "metrics": {
                "active_users": random.randint(100, 1000),
                "new_signups": random.randint(10, 50),
                "revenue": random.uniform(1000, 10000),
            },
        }

    def sync_external_data(self, source: str) -> dict:
        """Sync data from external source."""
        time.sleep(0.4)

        return {
            "status": "completed",
            "source": source,
            "records_synced": random.randint(50, 500),
            "sync_time": datetime.now().isoformat(),
        }

    def stats(self) -> dict:
        return {
            "last_runs": self.last_runs,
            "run_counts": self.run_counts,
            "worker_pid": os.getpid(),
        }
