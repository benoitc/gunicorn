import logging

from gunicorn.instrument.metrics.base import BaseMetricPlugin

import http.server
import prometheus_client
import prometheus_client.multiprocess


class PrometheusMetricPlugin(BaseMetricPlugin):
    def __init__(self, *args, **kwargs):
        logging.error("ASS")
        self._registry = prometheus_client.CollectorRegistry()
        self._collector = prometheus_client.multiprocess.MultiProcessCollector(registry=self._registry)
        gauge = prometheus_client.Gauge(registry=self._registry)
        gauge.set(123)

    def background_arbiter_task(self):
        prometheus_client.start_wsgi_server(9090, registry=self._registry)

    def handle_request_metrics(self, status: int, duration_ms: int) -> None:
        logging.error("works")

    def handle_worker_status_metrics(self):
        pass
