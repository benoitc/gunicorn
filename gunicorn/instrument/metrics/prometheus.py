import glob
import logging
import os.path

from gunicorn.instrument.metrics.base import BaseMetricPlugin

import http.server
import prometheus_client
import prometheus_client.multiprocess


class PrometheusMetricPlugin(BaseMetricPlugin):
    requests = None

    def __init__(self, *args, **kwargs):
        [os.unlink(x) for x in glob.glob(os.path.join("/tmp", "*_*.db"))]
        self._registry = prometheus_client.CollectorRegistry()
        self._collector = prometheus_client.multiprocess.MultiProcessCollector(registry=self._registry)

    def setup_metrics(self):
        self.requests = prometheus_client.Histogram("request_duration_seconds", "help", registry=self._registry)
        # pass

    def arbiter_startup_event(self):
        prometheus_client.start_wsgi_server(9090, registry=self._registry)

    def post_worker_init(self, worker):
        self.setup_metrics()

    def worker_exit_event(self, worker):
        logging.error("exiting")
        prometheus_client.multiprocess.mark_process_dead(worker.pid)
        logging.error("exited")

    def post_request_logging(self, status: int, duration_ms: int) -> None:
        self.requests.observe(duration_ms.total_seconds(), f"status:{status}")
        logging.error(duration_ms.total_seconds())

    def handle_worker_status_metrics(self):
        pass
