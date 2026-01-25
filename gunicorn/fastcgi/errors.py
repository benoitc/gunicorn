#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# We don't need to call super() in __init__ methods of our
# BaseException and Exception classes because we also define
# our own __str__ methods so there is no need to pass 'message'
# to the base class to get a meaningful output from 'str(exc)'.
# pylint: disable=super-init-not-called


class FastCGIParseException(Exception):
    """Base exception for FastCGI protocol parsing errors."""


class InvalidFastCGIRecord(FastCGIParseException):
    """Raised when a FastCGI record is malformed."""

    def __init__(self, msg=""):
        self.msg = msg
        self.code = 400

    def __str__(self):
        return "Invalid FastCGI record: %s" % self.msg


class UnsupportedRole(FastCGIParseException):
    """Raised when the FastCGI role is not RESPONDER."""

    def __init__(self, role):
        self.role = role
        self.code = 501

    def __str__(self):
        return "Unsupported FastCGI role: %d" % self.role


class ForbiddenFastCGIRequest(FastCGIParseException):
    """Raised when source IP is not in the allow list."""

    def __init__(self, host):
        self.host = host
        self.code = 403

    def __str__(self):
        return "FastCGI request from %r not allowed" % self.host
