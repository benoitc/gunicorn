from gunicorn.instrument.metrics.base import BaseMetricPlugin


class StatsDMetricPlugin(BaseMetricPlugin):
    """
    This plugin imitates the old implementation that was tied to log
    gunicorn.log metrics were dropped because there is no feasible way to gather them without all the problems
    with the previous implementation
    """
    _statsd = None

    def __init__(self, cfg):
        self._cfg = cfg

    def post_worker_init(self, worker):
        from gunicorn.instrument.statsd import Statsd
        self._statsd = Statsd(self._cfg)

    def post_request_logging(self, resp, duration) -> None:
        self._statsd.access(resp, duration)
