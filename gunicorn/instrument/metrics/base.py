class BaseMetricPlugin:
    """
    To implement your own metrics, inherit from this class and implement
    callbacks, for reference you can use other implementations in gunicorn itself
    """
    def post_worker_init(self, worker):
        """
        This is called post worker initialization, so things like gevent is patched
        and you can initialize your metric client here
        """
        pass

    def post_request_logging(self, status: int, duration_ms: int) -> None:
        """
        This is called at the time the worker logs the request
        Use this to record the request timings with your metric client
        """
        pass


class NoOpMetricPlugin(BaseMetricPlugin):
    """
    the default plugin that does nothing
    """
    pass
