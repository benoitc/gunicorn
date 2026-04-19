#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# We don't need to call super() in __init__ methods of our
# BaseException and Exception classes because we also define
# our own __str__ methods so there is no need to pass 'message'
# to the base class to get a meaningful output from 'str(exc)'.
# pylint: disable=super-init-not-called


class HaltServer(BaseException):
    """Exception to halt the Gunicorn server gracefully.

    This exception inherits from BaseException to ensure it is not
    caught by application-level exception handlers. Used to signal
    that the server should stop running.

    Args:
        reason: The reason for halting the server.
        exit_status: The exit status code to use when stopping.
    """
    def __init__(self, reason, exit_status=1):
        self.reason = reason
        self.exit_status = exit_status

    def __str__(self):
        return f"<HaltServer {self.reason!r} {self.exit_status}>"


class ConfigError(Exception):
    """Exception raised when there is a configuration error."""


class AppImportError(Exception):
    """Exception raised when there is an error loading an application."""
