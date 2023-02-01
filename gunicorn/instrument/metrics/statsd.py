from gunicorn.instrument.metrics.base import BaseMetricPlugin


class StatsDMetricPlugin(BaseMetricPlugin):
    _statsd = None

    def __init__(self, prefix, host, port, tags):
        self._host = host
        self._port = port
        self._tags = tags

        self._REQUEST_DURATION_METRIC_NAME = "gunicorn.request.duration" if prefix is None else "%sgunicorn.request.duration" % prefix
        self._REQUEST_METRIC_NAME = "gunicorn.request" if prefix is None else "%sgunicorn.request" % prefix
        self._REQUEST_STATUS_METRIC_NAME = "gunicorn.request.status.%d" if prefix is None else "%sgunicorn.request.status.%%d" % prefix

    def post_worker_init(self, worker):
        from datadog import DogStatsd
        self._statsd = DogStatsd(host=self._host, port=self._port)

    def post_request_logging(self, resp, duration) -> None:
        duration_ms = duration.total_seconds() * 1000
        status = resp.status
        if isinstance(status, str):
            status = int(status.split(None, 1)[0])
        self._statsd.histogram(self._REQUEST_DURATION_METRIC_NAME, duration_ms, tags=self._tags)
        self._statsd.increment(self._REQUEST_METRIC_NAME, 1, tags=self._tags)
        self._statsd.increment(self._REQUEST_STATUS_METRIC_NAME % status, 1, self._tags)
