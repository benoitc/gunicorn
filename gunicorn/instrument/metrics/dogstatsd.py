import logging
import os

from gunicorn.instrument.metrics.base import BaseMetricPlugin


class DogStatsDMetricPlugin(BaseMetricPlugin):
    """
    This new plugin is made specifically for DogstatsD that supports things like
    tags and different metric types natively
    """
    _statsd = None
    _host = os.environ.get("GUNICORN_DOGSTATSD_HOST", "127.0.0.1")
    _port = os.environ.get("GUNICORN_DOGSTATSD_PORT", 8125)

    def __init__(self, prefix=None, host=_host, port=_port, tags=None):
        if tags is None:
            tags = []
        self._host = host
        self._port = port

        self._REQUEST_DURATION_METRIC_NAME = "gunicorn.request.duration" if prefix is None else "%sgunicorn.request.duration" % prefix
        self._REQUEST_METRIC_NAME = "gunicorn.request" if prefix is None else "%sgunicorn.request" % prefix
        self._REQUEST_STATUS_METRIC_NAME = "gunicorn.request.status.%d" if prefix is None else "%sgunicorn.request.status.%%d" % prefix

    def post_worker_init(self, worker):
        from datadog import DogStatsd

        self._statsd = DogStatsd(host=self._host, port=self._port)

    def post_request_logging(self, resp, duration) -> None:
        status = resp.status
        if isinstance(status, str):
            status = int(status.split(None, 1)[0])
        self._statsd.histogram("gunicorn.request.duration", duration.total_seconds(), tags=[f"code:{status}"])
        self._statsd.increment("gunicorn.request", 1, tags=[f"code:{status}"])
