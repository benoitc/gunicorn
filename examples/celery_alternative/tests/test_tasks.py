"""
Unit Tests for Task Workers

These tests verify the task worker logic without running Gunicorn.
They test the DirtyApp classes directly.
"""

import pytest
from examples.celery_alternative.tasks import (
    EmailWorker,
    ImageWorker,
    DataWorker,
    ScheduledWorker,
)


class TestEmailWorker:
    """Tests for EmailWorker task class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.worker = EmailWorker()
        self.worker.init()

    def test_send_email(self):
        """Test sending a single email."""
        result = self.worker("send_email",
                             to="test@example.com",
                             subject="Test",
                             body="Hello")

        assert result["status"] == "sent"
        assert result["to"] == "test@example.com"
        assert result["subject"] == "Test"
        assert "message_id" in result
        assert "timestamp" in result

    def test_send_email_increments_counter(self):
        """Test that email counter increments."""
        initial_count = self.worker.emails_sent

        self.worker("send_email", to="a@x.com", subject="S", body="B")
        self.worker("send_email", to="b@x.com", subject="S", body="B")

        assert self.worker.emails_sent == initial_count + 2

    def test_send_bulk_emails_streaming(self):
        """Test bulk email sending with progress streaming."""
        recipients = ["a@x.com", "b@x.com", "c@x.com"]

        results = list(self.worker("send_bulk_emails",
                                   recipients=recipients,
                                   subject="Bulk",
                                   body="Hello all"))

        # Should have progress updates + final complete
        assert len(results) == len(recipients) + 1

        # Check progress updates
        for i, r in enumerate(results[:-1]):
            assert r["type"] == "progress"
            assert r["current"] == i + 1
            assert r["total"] == len(recipients)

        # Check final result
        final = results[-1]
        assert final["type"] == "complete"
        assert final["total"] == len(recipients)
        assert final["sent"] == len(recipients)

    def test_stats(self):
        """Test worker statistics."""
        self.worker("send_email", to="x@x.com", subject="S", body="B")

        stats = self.worker("stats")

        assert stats["emails_sent"] >= 1
        assert stats["smtp_connected"] is True
        assert "worker_pid" in stats

    def test_unknown_action_raises(self):
        """Test that unknown actions raise ValueError."""
        with pytest.raises(ValueError, match="Unknown action"):
            self.worker("nonexistent_action")

    def test_private_method_raises(self):
        """Test that private methods cannot be called."""
        with pytest.raises(ValueError, match="Unknown action"):
            self.worker("_connect_smtp")


class TestImageWorker:
    """Tests for ImageWorker task class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.worker = ImageWorker()
        self.worker.init()

    def test_resize_image(self):
        """Test image resizing."""
        result = self.worker("resize",
                             image_data="fake_image_data",
                             width=800,
                             height=600)

        assert result["status"] == "resized"
        assert result["target_dimensions"] == "800x600"
        assert "result_id" in result

    def test_generate_thumbnail(self):
        """Test thumbnail generation."""
        result = self.worker("generate_thumbnail",
                             image_data="fake_image_data",
                             size=150)

        assert result["status"] == "resized"
        assert result["target_dimensions"] == "150x150"

    def test_process_batch_streaming(self):
        """Test batch processing with progress streaming."""
        images = [
            {"id": "img1", "data": b"data1"},
            {"id": "img2", "data": b"data2"},
            {"id": "img3", "data": b"data3"},
        ]

        results = list(self.worker("process_batch",
                                   images=images,
                                   operation="resize",
                                   width=800,
                                   height=600))

        # Progress for each image + complete
        assert len(results) == len(images) + 1

        # Check progress updates
        for i, r in enumerate(results[:-1]):
            assert r["type"] == "progress"
            assert r["image_id"] == f"img{i+1}"
            assert "result" in r

        # Check final result
        final = results[-1]
        assert final["type"] == "complete"

    def test_stats(self):
        """Test worker statistics."""
        self.worker("resize", image_data=b"x", width=100, height=100)

        stats = self.worker("stats")

        assert stats["images_processed"] >= 1
        assert "pil_available" in stats
        assert "worker_pid" in stats


class TestDataWorker:
    """Tests for DataWorker task class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.worker = DataWorker()
        self.worker.init()

    def test_aggregate_sum(self):
        """Test data aggregation with sum."""
        data = [
            {"category": "A", "value": 10},
            {"category": "B", "value": 20},
            {"category": "A", "value": 30},
        ]

        result = self.worker("aggregate",
                             data=data,
                             group_by="category",
                             agg_field="value",
                             agg_func="sum")

        assert result["status"] == "completed"
        assert result["result"]["A"] == 40
        assert result["result"]["B"] == 20

    def test_aggregate_count(self):
        """Test data aggregation with count."""
        data = [
            {"category": "A", "value": 10},
            {"category": "B", "value": 20},
            {"category": "A", "value": 30},
        ]

        result = self.worker("aggregate",
                             data=data,
                             group_by="category",
                             agg_field="value",
                             agg_func="count")

        assert result["result"]["A"] == 2
        assert result["result"]["B"] == 1

    def test_etl_pipeline_streaming(self):
        """Test ETL pipeline with progress streaming."""
        source_data = [
            {"name": "alice", "status": "active"},
            {"name": "bob", "status": "inactive"},
            {"name": "charlie", "status": "active"},
        ]
        transformations = [
            {"name": "filter_active", "type": "filter",
             "field": "status", "value": "active"},
            {"name": "uppercase", "type": "map",
             "field": "name", "func": "upper"},
        ]

        results = list(self.worker("etl_pipeline",
                                   source_data=source_data,
                                   transformations=transformations))

        # extract + transforms + load + complete
        expected_steps = 1 + len(transformations) + 1 + 1
        assert len(results) == expected_steps

        # Check phases
        assert results[0]["phase"] == "extract"
        assert results[1]["phase"] == "transform"
        assert results[2]["phase"] == "transform"
        assert results[3]["phase"] == "load"
        assert results[4]["type"] == "complete"

        # Final should have 2 records (filtered)
        assert results[4]["records_output"] == 2

    def test_cached_query_miss_then_hit(self):
        """Test query caching - miss then hit."""
        # First call - cache miss
        result1 = self.worker("cached_query", query_key="test_query", ttl=300)
        assert result1["status"] == "cache_miss"

        # Second call - cache hit
        result2 = self.worker("cached_query", query_key="test_query", ttl=300)
        assert result2["status"] == "cache_hit"

    def test_stats(self):
        """Test worker statistics."""
        self.worker("aggregate",
                    data=[{"a": 1}],
                    group_by="a",
                    agg_field="a")

        stats = self.worker("stats")

        assert stats["tasks_completed"] >= 1
        assert "cache_size" in stats
        assert stats["db_connected"] is True


class TestScheduledWorker:
    """Tests for ScheduledWorker task class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.worker = ScheduledWorker()

    def test_cleanup_old_files(self):
        """Test file cleanup task."""
        result = self.worker("cleanup_old_files",
                             directory="/tmp/test",
                             max_age_days=7)

        assert result["status"] == "completed"
        assert result["directory"] == "/tmp/test"
        assert "files_deleted" in result
        assert "space_freed_mb" in result

    def test_generate_daily_report(self):
        """Test daily report generation."""
        result = self.worker("generate_daily_report")

        assert result["status"] == "completed"
        assert "report_date" in result
        assert "metrics" in result
        assert "active_users" in result["metrics"]
        assert "new_signups" in result["metrics"]
        assert "revenue" in result["metrics"]

    def test_sync_external_data(self):
        """Test external data sync."""
        result = self.worker("sync_external_data", source="test_api")

        assert result["status"] == "completed"
        assert result["source"] == "test_api"
        assert "records_synced" in result

    def test_stats_tracks_runs(self):
        """Test that stats tracks task runs."""
        self.worker("cleanup_old_files", directory="/tmp", max_age_days=1)
        self.worker("cleanup_old_files", directory="/tmp", max_age_days=1)
        self.worker("generate_daily_report")

        stats = self.worker("stats")

        assert stats["run_counts"]["cleanup_old_files"] == 2
        assert stats["run_counts"]["generate_daily_report"] == 1
        assert "cleanup_old_files" in stats["last_runs"]
