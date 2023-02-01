class BaseMetricPlugin:
    def post_worker_init(self, worker):
        pass

    def post_request_logging(self, status: int, duration_ms: int) -> None:
        pass


class NoOpMetricPlugin(BaseMetricPlugin):
    pass
