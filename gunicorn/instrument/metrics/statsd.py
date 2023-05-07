from gunicorn.instrument.metrics.base import BaseMetricPlugin


class StatsDMetricPlugin(BaseMetricPlugin):
    """
    This plugin imitates the old implementation that was tied to log
    gunicorn.log metrics were dropped because there is no feasible way to gather them without all the problems
    with the previous implementation
    """
    _statsd = None

    def __init__(self, prefix, host, port, tags):
        self._prefix = prefix
        self._host = host
        self._port = port
        self._tags = tags

    def post_worker_init(self, worker):
        from gunicorn.instrument.statsd import Statsd
        self._statsd = Statsd(prefix=self._prefix, host=self._host, port=self._port, tags=self._tags)

    def post_request_logging(self, resp, duration) -> None:
        self._statsd.access(resp, duration)
