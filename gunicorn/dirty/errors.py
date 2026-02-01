#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

"""
Dirty Arbiters Error Classes

Exception hierarchy for dirty worker pool operations.
"""


class DirtyError(Exception):
    """Base exception for all dirty arbiter errors."""

    def __init__(self, message, details=None):
        self.message = message
        self.details = details or {}
        super().__init__(message)

    def __str__(self):
        if self.details:
            return f"{self.message}: {self.details}"
        return self.message

    def to_dict(self):
        """Serialize error for protocol transmission."""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data):
        """Deserialize error from protocol transmission.

        Creates an error instance from a serialized dict. The returned
        error will be an instance of the appropriate subclass based on
        the error_type field, but constructed using the base DirtyError
        __init__ to preserve all details.
        """
        error_classes = {
            "DirtyError": DirtyError,
            "DirtyTimeoutError": DirtyTimeoutError,
            "DirtyConnectionError": DirtyConnectionError,
            "DirtyWorkerError": DirtyWorkerError,
            "DirtyAppError": DirtyAppError,
            "DirtyAppNotFoundError": DirtyAppNotFoundError,
            "DirtyNoWorkersAvailableError": DirtyNoWorkersAvailableError,
            "DirtyProtocolError": DirtyProtocolError,
        }
        error_type = data.get("error_type", "DirtyError")
        error_class = error_classes.get(error_type, DirtyError)

        # Create instance and set attributes directly to bypass
        # subclass __init__ complexity while preserving error type
        error = Exception.__new__(error_class)
        error.message = data.get("message", "Unknown error")
        error.details = data.get("details") or {}
        Exception.__init__(error, error.message)

        # Set subclass-specific attributes from details
        if error_class == DirtyTimeoutError:
            error.timeout = error.details.get("timeout")
        elif error_class == DirtyConnectionError:
            error.socket_path = error.details.get("socket_path")
        elif error_class == DirtyWorkerError:
            error.worker_id = error.details.get("worker_id")
            error.traceback = error.details.get("traceback")
        elif error_class in (DirtyAppError, DirtyAppNotFoundError):
            error.app_path = error.details.get("app_path")
            error.action = error.details.get("action")
            error.traceback = error.details.get("traceback")
        elif error_class == DirtyNoWorkersAvailableError:
            error.app_path = error.details.get("app_path")

        return error


class DirtyTimeoutError(DirtyError):
    """Raised when a dirty operation times out."""

    def __init__(self, message="Operation timed out", timeout=None):
        details = {"timeout": timeout} if timeout else {}
        super().__init__(message, details)
        self.timeout = timeout


class DirtyConnectionError(DirtyError):
    """Raised when connection to dirty arbiter fails."""

    def __init__(self, message="Connection failed", socket_path=None):
        details = {"socket_path": socket_path} if socket_path else {}
        super().__init__(message, details)
        self.socket_path = socket_path


class DirtyWorkerError(DirtyError):
    """Raised when a dirty worker encounters an error."""

    def __init__(self, message, worker_id=None, traceback=None):
        details = {}
        if worker_id is not None:
            details["worker_id"] = worker_id
        if traceback:
            details["traceback"] = traceback
        super().__init__(message, details)
        self.worker_id = worker_id
        self.traceback = traceback


class DirtyAppError(DirtyError):
    """Raised when a dirty app encounters an error during execution."""

    def __init__(self, message, app_path=None, action=None, traceback=None):
        details = {}
        if app_path:
            details["app_path"] = app_path
        if action:
            details["action"] = action
        if traceback:
            details["traceback"] = traceback
        super().__init__(message, details)
        self.app_path = app_path
        self.action = action
        self.traceback = traceback


class DirtyAppNotFoundError(DirtyAppError):
    """Raised when a dirty app is not found."""

    def __init__(self, app_path):
        super().__init__(f"Dirty app not found: {app_path}", app_path=app_path)


class DirtyNoWorkersAvailableError(DirtyError):
    """
    Raised when no workers are available for the requested app.

    This exception is raised when a request targets an app that has
    worker limits configured, and no workers with that app are currently
    available (e.g., all workers for that app crashed and haven't been
    respawned yet).

    Web applications can catch this exception to provide graceful
    degradation, such as queuing requests for retry or showing a
    maintenance page.

    Example::

        from gunicorn.dirty import get_dirty_client
        from gunicorn.dirty.errors import DirtyNoWorkersAvailableError

        def my_view(request):
            client = get_dirty_client()
            try:
                result = client.execute("myapp.ml:HeavyModel", "predict", data)
            except DirtyNoWorkersAvailableError as e:
                return {"error": "Service temporarily unavailable",
                        "app": e.app_path}
    """

    def __init__(self, app_path, message=None):
        if message is None:
            message = f"No workers available for app: {app_path}"
        super().__init__(message, details={"app_path": app_path})
        self.app_path = app_path


class DirtyProtocolError(DirtyError):
    """Raised when there is a protocol-level error."""

    def __init__(self, message="Protocol error", raw_data=None):
        details = {}
        if raw_data is not None:
            # Truncate raw data for safety
            if isinstance(raw_data, bytes):
                raw_data = raw_data[:100].hex()
            details["raw_data"] = str(raw_data)[:200]
        super().__init__(message, details)
