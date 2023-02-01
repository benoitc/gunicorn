from abc import ABC, abstractmethod


class BaseMetricPlugin(ABC):
    @abstractmethod
    def post_worker_init(self, worker):
        pass

    @abstractmethod
    def post_request_logging(self, status: int, duration_ms: int) -> None:
        pass

    @abstractmethod
    def handle_worker_status_metrics(self):
        pass


class NoOpMetricPlugin(BaseMetricPlugin):
    def post_worker_init(self, worker):
        pass

    def post_request_logging(self, status: int, duration_ms: int) -> None:
        pass

    def handle_worker_status_metrics(self):
        pass