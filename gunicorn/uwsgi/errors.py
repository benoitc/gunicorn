#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

# We don't need to call super() in __init__ methods of our
# BaseException and Exception classes because we also define
# our own __str__ methods so there is no need to pass 'message'
# to the base class to get a meaningful output from 'str(exc)'.
# pylint: disable=super-init-not-called


class UWSGIParseException(Exception):
    """Base exception for uWSGI protocol parsing errors."""


class InvalidUWSGIHeader(UWSGIParseException):
    """Raised when the uWSGI header is malformed."""

    def __init__(self, msg=""):
        self.msg = msg
        self.code = 400

    def __str__(self):
        return "Invalid uWSGI header: %s" % self.msg


class UnsupportedModifier(UWSGIParseException):
    """Raised when modifier1 is not 0 (WSGI request)."""

    def __init__(self, modifier):
        self.modifier = modifier
        self.code = 501

    def __str__(self):
        return "Unsupported uWSGI modifier1: %d" % self.modifier


class ForbiddenUWSGIRequest(UWSGIParseException):
    """Raised when source IP is not in the allow list."""

    def __init__(self, host):
        self.host = host
        self.code = 403

    def __str__(self):
        return "uWSGI request from %r not allowed" % self.host
