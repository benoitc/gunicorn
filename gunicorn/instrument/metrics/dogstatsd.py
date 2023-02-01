import logging

from gunicorn.instrument.metrics.base import BaseMetricPlugin

from datadog import initialize, statsd


class DogStatsDMetricPlugin(BaseMetricPlugin):
    def post_worker_init(self, worker):
        options = {
            "statsd_host": "127.0.0.1",
            "statsd_port": 8125
        }
        initialize(**options)

    def post_request_logging(self, status: int, duration_ms: int) -> None:
        statsd.histogram("test.blah", duration_ms.total_seconds(), tags=[f"status:{status}", "asd:123"])

    def handle_worker_status_metrics(self):
        pass
