from abc import ABC, abstractmethod


class BaseMetricPlugin(ABC):
    @abstractmethod
    def background_arbiter_task(self):
        pass

    @abstractmethod
    def handle_request_metrics(self, status: int, duration_ms: int) -> None:
        pass

    @abstractmethod
    def handle_worker_status_metrics(self):
        pass


class NoOpMetricPlugin(BaseMetricPlugin):
    def background_arbiter_task(self):
        pass

    def handle_request_metrics(self, status: int, duration_ms: int) -> None:
        pass

    def handle_worker_status_metrics(self):
        pass
