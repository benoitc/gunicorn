"""
Integration Tests for Celery Replacement Example

These tests run against the full application with Gunicorn and dirty arbiters.
They can be run locally or in Docker.

Usage:
    # Local (with gunicorn running):
    APP_URL=http://localhost:8000 pytest tests/test_integration.py -v

    # Docker:
    docker compose --profile test up --build --abort-on-container-exit
"""

import json
import os
import time

import pytest
import requests

# Get app URL from environment or use default
APP_URL = os.environ.get("APP_URL", "http://localhost:8000")


def wait_for_app(timeout=30):
    """Wait for the application to be ready."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = requests.get(f"{APP_URL}/health", timeout=5)
            if resp.status_code == 200:
                return True
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(1)
    return False


@pytest.fixture(scope="module", autouse=True)
def ensure_app_running():
    """Ensure the application is running before tests."""
    if not wait_for_app():
        pytest.skip("Application not available")


class TestHealthEndpoint:
    """Test health check endpoint."""

    def test_health_check(self):
        """Test that health endpoint returns healthy status."""
        resp = requests.get(f"{APP_URL}/health")
        assert resp.status_code == 200

        data = resp.json()
        assert data["status"] == "healthy"
        assert data["workers"] == "connected"


class TestEmailTasks:
    """Integration tests for email tasks."""

    def test_send_single_email(self):
        """Test sending a single email via API."""
        resp = requests.post(
            f"{APP_URL}/api/email/send",
            json={
                "to": "test@example.com",
                "subject": "Integration Test",
                "body": "Hello from integration test",
            },
        )
        assert resp.status_code == 200

        data = resp.json()
        assert data["status"] == "sent"
        assert data["to"] == "test@example.com"
        assert "message_id" in data

    def test_send_bulk_emails_streaming(self):
        """Test bulk email sending with SSE streaming."""
        recipients = ["a@test.com", "b@test.com", "c@test.com"]

        resp = requests.post(
            f"{APP_URL}/api/email/send-bulk",
            json={
                "recipients": recipients,
                "subject": "Bulk Test",
                "body": "Hello all",
            },
            stream=True,
        )
        assert resp.status_code == 200

        events = []
        for line in resp.iter_lines():
            if line:
                line = line.decode("utf-8")
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    events.append(data)

        # Should have progress for each recipient + complete
        assert len(events) == len(recipients) + 1

        # Check progress events
        for i, event in enumerate(events[:-1]):
            assert event["type"] == "progress"
            assert event["current"] == i + 1

        # Check complete event
        assert events[-1]["type"] == "complete"
        assert events[-1]["sent"] == len(recipients)

    def test_email_stats(self):
        """Test email worker statistics endpoint."""
        # Send an email first
        requests.post(
            f"{APP_URL}/api/email/send",
            json={"to": "x@x.com", "subject": "S", "body": "B"},
        )

        resp = requests.get(f"{APP_URL}/api/email/stats")
        assert resp.status_code == 200

        data = resp.json()
        assert data["emails_sent"] >= 1
        assert data["smtp_connected"] is True
        assert "worker_pid" in data


class TestImageTasks:
    """Integration tests for image tasks."""

    def test_resize_image(self):
        """Test image resizing via API."""
        resp = requests.post(
            f"{APP_URL}/api/image/resize",
            json={
                "image_data": "base64_encoded_image_data",
                "width": 800,
                "height": 600,
            },
        )
        assert resp.status_code == 200

        data = resp.json()
        assert data["status"] == "resized"
        assert data["target_dimensions"] == "800x600"

    def test_generate_thumbnail(self):
        """Test thumbnail generation via API."""
        resp = requests.post(
            f"{APP_URL}/api/image/thumbnail",
            json={
                "image_data": "base64_image",
                "size": 150,
            },
        )
        assert resp.status_code == 200

        data = resp.json()
        assert data["status"] == "resized"
        assert data["target_dimensions"] == "150x150"

    def test_batch_processing_streaming(self):
        """Test batch image processing with streaming."""
        images = [
            {"id": "img1", "data": "data1"},
            {"id": "img2", "data": "data2"},
        ]

        resp = requests.post(
            f"{APP_URL}/api/image/process-batch",
            json={
                "images": images,
                "operation": "resize",
                "width": 400,
                "height": 300,
            },
            stream=True,
        )
        assert resp.status_code == 200

        events = []
        for line in resp.iter_lines():
            if line:
                line = line.decode("utf-8")
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))

        assert len(events) == len(images) + 1
        assert events[-1]["type"] == "complete"

    def test_image_stats(self):
        """Test image worker statistics."""
        resp = requests.get(f"{APP_URL}/api/image/stats")
        assert resp.status_code == 200

        data = resp.json()
        assert "images_processed" in data
        assert "worker_pid" in data


class TestDataTasks:
    """Integration tests for data processing tasks."""

    def test_aggregate_data(self):
        """Test data aggregation via API."""
        resp = requests.post(
            f"{APP_URL}/api/data/aggregate",
            json={
                "data": [
                    {"category": "A", "value": 10},
                    {"category": "B", "value": 20},
                    {"category": "A", "value": 30},
                ],
                "group_by": "category",
                "agg_field": "value",
                "agg_func": "sum",
            },
        )
        assert resp.status_code == 200

        data = resp.json()
        assert data["status"] == "completed"
        assert data["result"]["A"] == 40
        assert data["result"]["B"] == 20

    def test_etl_pipeline_streaming(self):
        """Test ETL pipeline with streaming progress."""
        resp = requests.post(
            f"{APP_URL}/api/data/etl",
            json={
                "source_data": [
                    {"name": "alice", "status": "active"},
                    {"name": "bob", "status": "inactive"},
                    {"name": "charlie", "status": "active"},
                ],
                "transformations": [
                    {"name": "filter", "type": "filter",
                     "field": "status", "value": "active"},
                ],
            },
            stream=True,
        )
        assert resp.status_code == 200

        events = []
        for line in resp.iter_lines():
            if line:
                line = line.decode("utf-8")
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))

        # extract + transform + load + complete
        assert len(events) == 4

        # Check phases
        phases = [e.get("phase") for e in events[:-1]]
        assert "extract" in phases
        assert "transform" in phases
        assert "load" in phases

        # Final result
        assert events[-1]["type"] == "complete"
        assert events[-1]["records_output"] == 2

    def test_cached_query(self):
        """Test cached query functionality."""
        query_key = f"test_query_{time.time()}"

        # First call - cache miss
        resp1 = requests.post(
            f"{APP_URL}/api/data/query",
            json={"query_key": query_key, "ttl": 300},
        )
        assert resp1.status_code == 200
        assert resp1.json()["status"] == "cache_miss"

        # Second call - cache hit
        resp2 = requests.post(
            f"{APP_URL}/api/data/query",
            json={"query_key": query_key, "ttl": 300},
        )
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "cache_hit"

    def test_data_stats(self):
        """Test data worker statistics."""
        resp = requests.get(f"{APP_URL}/api/data/stats")
        assert resp.status_code == 200

        data = resp.json()
        assert "tasks_completed" in data
        assert "cache_size" in data


class TestScheduledTasks:
    """Integration tests for scheduled tasks."""

    def test_cleanup_task(self):
        """Test cleanup task execution."""
        resp = requests.post(
            f"{APP_URL}/api/scheduled/cleanup",
            json={"directory": "/tmp/test", "max_age_days": 7},
        )
        assert resp.status_code == 200

        data = resp.json()
        assert data["status"] == "completed"
        assert "files_deleted" in data

    def test_daily_report(self):
        """Test daily report generation."""
        resp = requests.post(f"{APP_URL}/api/scheduled/daily-report")
        assert resp.status_code == 200

        data = resp.json()
        assert data["status"] == "completed"
        assert "metrics" in data

    def test_sync_task(self):
        """Test data sync task."""
        resp = requests.post(
            f"{APP_URL}/api/scheduled/sync",
            json={"source": "test_source"},
        )
        assert resp.status_code == 200

        data = resp.json()
        assert data["status"] == "completed"
        assert data["source"] == "test_source"

    def test_scheduled_stats(self):
        """Test scheduled worker statistics."""
        # Run a task first
        requests.post(f"{APP_URL}/api/scheduled/daily-report")

        resp = requests.get(f"{APP_URL}/api/scheduled/stats")
        assert resp.status_code == 200

        data = resp.json()
        assert "run_counts" in data
        assert "generate_daily_report" in data["run_counts"]


class TestConcurrency:
    """Test concurrent task execution."""

    def test_concurrent_requests(self):
        """Test that multiple concurrent requests are handled."""
        import concurrent.futures

        def send_email():
            return requests.post(
                f"{APP_URL}/api/email/send",
                json={"to": "x@x.com", "subject": "Concurrent", "body": "Test"},
            )

        # Send 10 concurrent requests
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(send_email) for _ in range(10)]
            results = [f.result() for f in futures]

        # All should succeed
        assert all(r.status_code == 200 for r in results)
        assert all(r.json()["status"] == "sent" for r in results)

    def test_mixed_task_types(self):
        """Test different task types running concurrently."""
        import concurrent.futures

        def email_task():
            return requests.post(
                f"{APP_URL}/api/email/send",
                json={"to": "x@x.com", "subject": "S", "body": "B"},
            )

        def image_task():
            return requests.post(
                f"{APP_URL}/api/image/resize",
                json={"image_data": "x", "width": 100, "height": 100},
            )

        def data_task():
            return requests.post(
                f"{APP_URL}/api/data/aggregate",
                json={
                    "data": [{"a": 1}],
                    "group_by": "a",
                    "agg_field": "a",
                    "agg_func": "sum",
                },
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=9) as executor:
            futures = []
            for _ in range(3):
                futures.append(executor.submit(email_task))
                futures.append(executor.submit(image_task))
                futures.append(executor.submit(data_task))

            results = [f.result() for f in futures]

        # All should succeed
        assert all(r.status_code == 200 for r in results)


class TestErrorHandling:
    """Test error handling scenarios."""

    def test_invalid_action(self):
        """Test that invalid actions return appropriate errors."""
        # This would require modifying the API to expose raw execute
        # For now, we test via a malformed request
        resp = requests.post(
            f"{APP_URL}/api/email/send",
            json={},  # Missing required fields
        )
        # Should get a 500 or validation error
        assert resp.status_code in [400, 500]
